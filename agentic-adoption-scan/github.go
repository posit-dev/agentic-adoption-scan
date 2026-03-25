package main

import (
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"math/rand"
	"net/http"
	"net/url"
	"os"
	"strconv"
	"strings"
	"sync"
	"time"
)

// RateLimitTracker tracks per-user rate limit state, keyed by a hash of the token.
// It can be shared across multiple GitHubClient instances (e.g. in the MCP HTTP server).
type RateLimitTracker struct {
	mu      sync.Mutex
	perUser map[string]*userRateState
}

type userRateState struct {
	mu              sync.Mutex // per-user mutex to avoid blocking other users
	searchLastCall  time.Time
	rateLimitRemain int
	rateLimitReset  time.Time
	lastSeen        time.Time
}

// NewRateLimitTracker creates a new RateLimitTracker.
func NewRateLimitTracker() *RateLimitTracker {
	return &RateLimitTracker{
		perUser: make(map[string]*userRateState),
	}
}

// getOrCreate returns the rate state for a token key, creating it if absent.
func (t *RateLimitTracker) getOrCreate(tokenKey string) *userRateState {
	t.mu.Lock()
	defer t.mu.Unlock()
	if s, ok := t.perUser[tokenKey]; ok {
		s.lastSeen = time.Now()
		return s
	}
	s := &userRateState{
		rateLimitRemain: 100, // assume budget until told otherwise
		lastSeen:        time.Now(),
	}
	t.perUser[tokenKey] = s
	return s
}

// CleanupStale removes entries that haven't been used within maxAge.
func (t *RateLimitTracker) CleanupStale(maxAge time.Duration) {
	t.mu.Lock()
	defer t.mu.Unlock()
	cutoff := time.Now().Add(-maxAge)
	for k, s := range t.perUser {
		if s.lastSeen.Before(cutoff) {
			delete(t.perUser, k)
		}
	}
}

// StartCleanup runs periodic cleanup of stale entries in a background goroutine.
// The goroutine runs until the provided stop channel is closed.
func (t *RateLimitTracker) StartCleanup(interval, maxAge time.Duration, stop <-chan struct{}) {
	go func() {
		ticker := time.NewTicker(interval)
		defer ticker.Stop()
		for {
			select {
			case <-ticker.C:
				t.CleanupStale(maxAge)
			case <-stop:
				return
			}
		}
	}()
}

// tokenKey returns a short, stable key for a token (sha256, first 16 hex chars).
func tokenKey(token string) string {
	h := sha256.Sum256([]byte(token))
	return fmt.Sprintf("%x", h[:8])
}

// GitHubClient wraps the GitHub API with rate limiting.
type GitHubClient struct {
	mu               sync.Mutex // local mutex, used when rateLimitTracker is nil
	logger           *log.Logger
	token            string
	httpClient       *http.Client
	searchMinDelay   time.Duration // minimum delay between code search calls
	rateLimitRemain  int           // local fallback when tracker is nil
	rateLimitReset   time.Time     // local fallback when tracker is nil
	searchLastCall   time.Time     // local fallback when tracker is nil
	rateLimitTracker *RateLimitTracker
}

// Repo represents a GitHub repository from the API.
type Repo struct {
	Name       string `json:"name"`
	FullName   string `json:"full_name"`
	Archived   bool   `json:"archived"`
	Visibility string `json:"visibility"`
	Language   string `json:"language"`
	PushedAt   string `json:"pushed_at"`
}

// SearchResult represents a code search hit.
type SearchResult struct {
	TotalCount int `json:"total_count"`
	Items      []struct {
		Name    string `json:"name"`
		Path    string `json:"path"`
		HTMLURL string `json:"html_url"`
	} `json:"items"`
}

// NewGitHubClient creates a client that reads the token from GH_TOKEN or GITHUB_TOKEN env vars.
func NewGitHubClient(logger *log.Logger) *GitHubClient {
	token := os.Getenv("GH_TOKEN")
	if token == "" {
		token = os.Getenv("GITHUB_TOKEN")
	}
	return NewGitHubClientWithToken(token, logger)
}

// NewGitHubClientWithToken creates a client using the provided token.
func NewGitHubClientWithToken(token string, logger *log.Logger) *GitHubClient {
	return &GitHubClient{
		logger:          logger,
		token:           token,
		httpClient:      &http.Client{Timeout: 30 * time.Second},
		searchMinDelay:  2100 * time.Millisecond, // stay under 30 req/min for code search
		rateLimitRemain: 100,                      // assume we have budget until told otherwise
	}
}

const githubAPIBase = "https://api.github.com"

// ghAPI calls the GitHub REST API and returns the raw response body.
// It handles rate limiting (HTTP 403/429) and retries with backoff.
// The accept parameter overrides the Accept header if non-empty.
func (c *GitHubClient) ghAPI(method, endpoint, accept string) ([]byte, *http.Response, error) {
	c.waitForRateLimit()

	// Build the full URL. Endpoints from callers start with "/".
	rawURL := githubAPIBase + endpoint

	if accept == "" {
		accept = "application/vnd.github+json"
	}

	var lastErr error
	for attempt := 0; attempt < 4; attempt++ {
		if attempt > 0 {
			backoff := time.Duration(1<<uint(attempt)) * time.Second
			jitter := time.Duration(rand.Intn(500)) * time.Millisecond
			c.logger.Printf("Rate limited, retrying in %v (attempt %d)", backoff+jitter, attempt+1)
			time.Sleep(backoff + jitter)
		}

		req, err := http.NewRequest(method, rawURL, nil)
		if err != nil {
			return nil, nil, fmt.Errorf("building request: %w", err)
		}

		req.Header.Set("Accept", accept)
		req.Header.Set("X-GitHub-Api-Version", "2022-11-28")
		if c.token != "" {
			req.Header.Set("Authorization", "Bearer "+c.token)
		}

		resp, err := c.httpClient.Do(req)
		if err != nil {
			lastErr = fmt.Errorf("http request: %w", err)
			continue
		}

		body, err := io.ReadAll(resp.Body)
		resp.Body.Close()
		if err != nil {
			lastErr = fmt.Errorf("reading response body: %w", err)
			continue
		}

		// Update rate limit state from response headers
		c.updateRateLimit(resp)

		// Handle rate limiting
		if resp.StatusCode == 403 || resp.StatusCode == 429 {
			lastErr = fmt.Errorf("rate limited (HTTP %d): %s", resp.StatusCode, string(body))
			continue
		}

		if resp.StatusCode >= 400 {
			return nil, resp, fmt.Errorf("github api error (HTTP %d): %s", resp.StatusCode, string(body))
		}

		return body, resp, nil
	}
	return nil, nil, fmt.Errorf("exhausted retries: %w", lastErr)
}

// ghAPIPaginated fetches all pages of a paginated endpoint, using the Link header.
func (c *GitHubClient) ghAPIPaginated(endpoint string) ([]json.RawMessage, error) {
	var allItems []json.RawMessage

	// Build initial URL with per_page=100
	sep := "?"
	if strings.Contains(endpoint, "?") {
		sep = "&"
	}
	currentEndpoint := endpoint + sep + "per_page=100"

	for currentEndpoint != "" {
		out, resp, err := c.ghAPI("GET", currentEndpoint, "")
		if err != nil {
			return nil, err
		}

		var items []json.RawMessage
		if err := json.Unmarshal(out, &items); err != nil {
			return nil, fmt.Errorf("failed to parse paginated response: %w", err)
		}

		allItems = append(allItems, items...)

		// Parse Link header for next page
		nextURL := parseLinkNext(resp.Header.Get("Link"))
		if nextURL == "" {
			break
		}
		// The Link header returns full URLs; strip the base to get an endpoint
		currentEndpoint = strings.TrimPrefix(nextURL, githubAPIBase)
	}

	return allItems, nil
}

// parseLinkNext extracts the URL for rel="next" from a Link header value.
func parseLinkNext(header string) string {
	if header == "" {
		return ""
	}
	// Link: <https://api.github.com/...?page=2>; rel="next", <...>; rel="last"
	for _, part := range strings.Split(header, ",") {
		part = strings.TrimSpace(part)
		segments := strings.Split(part, ";")
		if len(segments) < 2 {
			continue
		}
		urlPart := strings.TrimSpace(segments[0])
		relPart := strings.TrimSpace(segments[1])
		if relPart == `rel="next"` {
			// Strip angle brackets
			urlPart = strings.TrimPrefix(urlPart, "<")
			urlPart = strings.TrimSuffix(urlPart, ">")
			return urlPart
		}
	}
	return ""
}

// ListOrgRepos lists all repositories in an organization.
func (c *GitHubClient) ListOrgRepos(org string) ([]Repo, error) {
	c.logger.Printf("Listing repos for org: %s", org)

	raw, err := c.ghAPIPaginated(fmt.Sprintf("/orgs/%s/repos?sort=pushed&direction=desc", org))
	if err != nil {
		return nil, fmt.Errorf("listing org repos: %w", err)
	}

	var repos []Repo
	for _, item := range raw {
		var r Repo
		if err := json.Unmarshal(item, &r); err != nil {
			c.logger.Printf("Warning: failed to parse repo: %v", err)
			continue
		}
		repos = append(repos, r)
	}

	c.logger.Printf("Found %d repos in %s", len(repos), org)
	return repos, nil
}

// CheckPathExists checks if a file or directory exists in a repo.
// Returns (exists, isDir, error).
func (c *GitHubClient) CheckPathExists(owner, repo, path string) (bool, bool, error) {
	c.logger.Printf("Checking path: %s/%s/%s", owner, repo, path)

	out, resp, err := c.ghAPI("GET", fmt.Sprintf("/repos/%s/%s/contents/%s", owner, repo, path), "")
	if err != nil {
		if resp != nil && resp.StatusCode == 404 {
			return false, false, nil
		}
		errStr := err.Error()
		if strings.Contains(errStr, "404") || strings.Contains(errStr, "Not Found") {
			return false, false, nil
		}
		return false, false, err
	}

	// If it's a directory, the response is an array
	trimmed := strings.TrimSpace(string(out))
	if len(trimmed) > 0 && trimmed[0] == '[' {
		return true, true, nil
	}

	// Single file response
	var content struct {
		Type string `json:"type"`
	}
	if err := json.Unmarshal(out, &content); err == nil {
		return true, content.Type == "dir", nil
	}

	return true, false, nil
}

// SearchCode searches for code patterns in a specific repo using the Code Search API.
func (c *GitHubClient) SearchCode(org, repo, query string) (*SearchResult, error) {
	c.throttleSearch()
	c.logger.Printf("Code search in %s/%s: %s", org, repo, query)

	fullQuery := fmt.Sprintf("%s repo:%s/%s", query, org, repo)
	encodedQuery := url.QueryEscape(fullQuery)

	out, _, err := c.ghAPI("GET", "/search/code?q="+encodedQuery, "")
	if err != nil {
		return nil, err
	}

	var result SearchResult
	if err := json.Unmarshal(out, &result); err != nil {
		return nil, fmt.Errorf("parsing search results: %w", err)
	}

	return &result, nil
}

// SearchCodeInWorkflows searches for patterns specifically in workflow files.
func (c *GitHubClient) SearchCodeInWorkflows(org, repo, query string) (*SearchResult, error) {
	return c.SearchCode(org, repo, fmt.Sprintf("%s path:.github/workflows", query))
}

// GetFileContent fetches the raw content of a file from a repo.
func (c *GitHubClient) GetFileContent(owner, repo, path string) ([]byte, error) {
	c.logger.Printf("Fetching content: %s/%s/%s", owner, repo, path)

	endpoint := fmt.Sprintf("/repos/%s/%s/contents/%s", owner, repo, path)
	out, _, err := c.ghAPI("GET", endpoint, "application/vnd.github.raw+json")
	if err != nil {
		return nil, fmt.Errorf("fetching file content: %w", err)
	}
	return out, nil
}

// throttleSearch enforces the code search rate limit (30 req/min).
func (c *GitHubClient) throttleSearch() {
	if c.rateLimitTracker != nil {
		key := tokenKey(c.token)
		state := c.rateLimitTracker.getOrCreate(key)

		// Read state under per-user lock, then sleep outside
		state.mu.Lock()
		elapsed := time.Since(state.searchLastCall)
		state.mu.Unlock()

		if elapsed < c.searchMinDelay {
			wait := c.searchMinDelay - elapsed
			c.logger.Printf("Throttling search: waiting %v", wait)
			time.Sleep(wait)
		}

		state.mu.Lock()
		state.searchLastCall = time.Now()
		state.mu.Unlock()
		return
	}

	c.mu.Lock()
	defer c.mu.Unlock()

	elapsed := time.Since(c.searchLastCall)
	if elapsed < c.searchMinDelay {
		wait := c.searchMinDelay - elapsed
		c.logger.Printf("Throttling search: waiting %v", wait)
		time.Sleep(wait)
	}
	c.searchLastCall = time.Now()
}

// waitForRateLimit checks if we're close to the rate limit and waits if needed.
func (c *GitHubClient) waitForRateLimit() {
	if c.rateLimitTracker != nil {
		key := tokenKey(c.token)
		state := c.rateLimitTracker.getOrCreate(key)

		// Read state under per-user lock, then sleep outside
		state.mu.Lock()
		shouldWait := state.rateLimitRemain < 10 && time.Now().Before(state.rateLimitReset)
		var wait time.Duration
		if shouldWait {
			wait = time.Until(state.rateLimitReset) + time.Second
		}
		state.mu.Unlock()

		if shouldWait {
			c.logger.Printf("Rate limit low, waiting %v until reset", wait)
			time.Sleep(wait)
		}
		return
	}

	c.mu.Lock()
	defer c.mu.Unlock()

	if c.rateLimitRemain < 10 && time.Now().Before(c.rateLimitReset) {
		wait := time.Until(c.rateLimitReset) + time.Second
		c.logger.Printf("Rate limit low (%d remaining), waiting %v until reset", c.rateLimitRemain, wait)
		time.Sleep(wait)
	}
}

// updateRateLimit parses X-RateLimit-Remaining and X-RateLimit-Reset from HTTP response headers.
func (c *GitHubClient) updateRateLimit(resp *http.Response) {
	remainStr := resp.Header.Get("X-RateLimit-Remaining")
	resetStr := resp.Header.Get("X-RateLimit-Reset")

	if remainStr == "" && resetStr == "" {
		return
	}

	remain, err := strconv.Atoi(remainStr)
	if err != nil {
		remain = -1
	}

	var reset time.Time
	if resetUnix, err := strconv.ParseInt(resetStr, 10, 64); err == nil {
		reset = time.Unix(resetUnix, 0)
	}

	if c.rateLimitTracker != nil {
		key := tokenKey(c.token)
		state := c.rateLimitTracker.getOrCreate(key)
		state.mu.Lock()
		defer state.mu.Unlock()
		if remain >= 0 {
			state.rateLimitRemain = remain
		}
		if !reset.IsZero() {
			state.rateLimitReset = reset
		}
		return
	}

	c.mu.Lock()
	defer c.mu.Unlock()
	if remain >= 0 {
		c.rateLimitRemain = remain
	}
	if !reset.IsZero() {
		c.rateLimitReset = reset
	}
}

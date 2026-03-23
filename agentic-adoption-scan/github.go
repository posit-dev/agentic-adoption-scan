package main

import (
	"encoding/json"
	"fmt"
	"log"
	"math/rand"
	"os/exec"
	"strconv"
	"strings"
	"sync"
	"time"
)

// GitHubClient wraps the gh CLI with rate limiting.
type GitHubClient struct {
	mu              sync.Mutex
	logger          *log.Logger
	searchLastCall  time.Time
	searchMinDelay  time.Duration // minimum delay between code search calls
	rateLimitRemain int
	rateLimitReset  time.Time
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

func NewGitHubClient(logger *log.Logger) *GitHubClient {
	return &GitHubClient{
		logger:          logger,
		searchMinDelay:  2100 * time.Millisecond, // stay under 30 req/min for code search
		rateLimitRemain: 100,                      // assume we have budget until told otherwise
	}
}

// ghAPI calls the GitHub API via the gh CLI and returns raw JSON output.
// It handles rate limiting and retries.
func (c *GitHubClient) ghAPI(method, endpoint string, fields ...string) ([]byte, error) {
	c.waitForRateLimit()

	args := []string{"api", "--method", method}
	args = append(args, "-H", "Accept: application/vnd.github+json")
	args = append(args, "-H", "X-GitHub-Api-Version: 2022-11-28")
	for _, f := range fields {
		args = append(args, "-f", f)
	}
	args = append(args, endpoint)

	var lastErr error
	for attempt := 0; attempt < 4; attempt++ {
		if attempt > 0 {
			backoff := time.Duration(1<<uint(attempt)) * time.Second
			jitter := time.Duration(rand.Intn(500)) * time.Millisecond
			c.logger.Printf("Rate limited, retrying in %v (attempt %d)", backoff+jitter, attempt+1)
			time.Sleep(backoff + jitter)
		}

		cmd := exec.Command("gh", args...)
		out, err := cmd.CombinedOutput()
		if err != nil {
			outStr := string(out)
			// Check for rate limiting
			if strings.Contains(outStr, "rate limit") || strings.Contains(outStr, "403") || strings.Contains(outStr, "secondary rate limit") {
				lastErr = fmt.Errorf("rate limited: %s", outStr)
				continue
			}
			lastErr = fmt.Errorf("gh api error: %w\n%s", err, outStr)
			// Only retry on rate limits, not other errors
			return nil, lastErr
		}

		c.updateRateLimit(out)
		return out, nil
	}
	return nil, fmt.Errorf("exhausted retries: %w", lastErr)
}

// ghAPIPaginated fetches all pages of a paginated endpoint.
func (c *GitHubClient) ghAPIPaginated(endpoint string) ([]json.RawMessage, error) {
	var allItems []json.RawMessage
	page := 1
	perPage := 100

	for {
		sep := "?"
		if strings.Contains(endpoint, "?") {
			sep = "&"
		}
		pagedEndpoint := fmt.Sprintf("%s%sper_page=%d&page=%d", endpoint, sep, perPage, page)

		out, err := c.ghAPI("GET", pagedEndpoint)
		if err != nil {
			return nil, err
		}

		var items []json.RawMessage
		if err := json.Unmarshal(out, &items); err != nil {
			return nil, fmt.Errorf("failed to parse response page %d: %w", page, err)
		}

		if len(items) == 0 {
			break
		}

		allItems = append(allItems, items...)

		if len(items) < perPage {
			break
		}
		page++
	}

	return allItems, nil
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

	out, err := c.ghAPI("GET", fmt.Sprintf("/repos/%s/%s/contents/%s", owner, repo, path))
	if err != nil {
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

	out, err := c.ghAPI("GET", fmt.Sprintf("/search/code?q=%s", urlEncode(fullQuery)))
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

	args := []string{"api", "--method", "GET",
		"-H", "Accept: application/vnd.github.raw+json",
		"-H", "X-GitHub-Api-Version: 2022-11-28",
		fmt.Sprintf("/repos/%s/%s/contents/%s", owner, repo, path),
	}

	cmd := exec.Command("gh", args...)
	out, err := cmd.CombinedOutput()
	if err != nil {
		return nil, fmt.Errorf("fetching file content: %w\n%s", err, string(out))
	}

	return out, nil
}

// throttleSearch enforces the code search rate limit (30 req/min).
func (c *GitHubClient) throttleSearch() {
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
	c.mu.Lock()
	defer c.mu.Unlock()

	if c.rateLimitRemain < 10 && time.Now().Before(c.rateLimitReset) {
		wait := time.Until(c.rateLimitReset) + time.Second
		c.logger.Printf("Rate limit low (%d remaining), waiting %v until reset", c.rateLimitRemain, wait)
		time.Sleep(wait)
	}
}

// updateRateLimit parses rate limit info from response headers embedded in gh output.
// Note: gh CLI doesn't directly expose headers, so we track via search throttling primarily.
func (c *GitHubClient) updateRateLimit(body []byte) {
	// gh CLI doesn't expose response headers directly.
	// We rely on the search throttle and error-based retry for rate limiting.
}

// urlEncode does minimal URL encoding for search queries.
func urlEncode(s string) string {
	s = strings.ReplaceAll(s, " ", "+")
	s = strings.ReplaceAll(s, ":", "%3A")
	s = strings.ReplaceAll(s, "/", "%2F")
	s = strings.ReplaceAll(s, "@", "%40")
	return s
}

// parseRateLimitHeader parses a rate limit header value.
func parseRateLimitHeader(headers map[string]string, key string) int {
	if v, ok := headers[key]; ok {
		n, _ := strconv.Atoi(v)
		return n
	}
	return -1
}

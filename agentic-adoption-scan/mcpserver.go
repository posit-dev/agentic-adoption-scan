package main

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"strings"
	"time"

	"github.com/mark3labs/mcp-go/mcp"
	"github.com/mark3labs/mcp-go/server"
)

// MCPServerConfig holds shared state for MCP tool handlers.
type MCPServerConfig struct {
	Logger    *log.Logger
	CacheDir  string
	ConfigPath string
}

// newMCPServer creates an MCP server with all tools registered.
func newMCPServer(cfg MCPServerConfig) *server.MCPServer {
	s := server.NewMCPServer(
		"agentic-adoption-scan",
		"1.0.0",
		server.WithToolCapabilities(false),
	)

	s.AddTool(scanOrgTool(), makeScanHandler(cfg))
	s.AddTool(inspectRepoTool(), makeInspectHandler(cfg))
	s.AddTool(listIndicatorsTool(), makeListIndicatorsHandler(cfg))
	s.AddTool(getRepoSummaryTool(), makeRepoSummaryHandler(cfg))
	s.AddTool(getAdoptionSummaryTool(), makeAdoptionSummaryHandler(cfg))

	return s
}

// StartMCPServer creates and runs the MCP server over stdio.
func StartMCPServer(cfg MCPServerConfig) error {
	return server.ServeStdio(newMCPServer(cfg))
}

// StartMCPHTTPServer creates and runs the MCP server over Streamable HTTP with
// stateless mode. This is the required transport for Posit Connect deployments.
// The MCP endpoint is mounted at /mcp per the Posit Connect convention.
func StartMCPHTTPServer(cfg MCPServerConfig, addr string) error {
	httpServer := server.NewStreamableHTTPServer(newMCPServer(cfg),
		server.WithStateLess(true),
		server.WithEndpointPath("/mcp"),
	)

	cfg.Logger.Printf("Starting MCP HTTP server on %s/mcp", addr)
	return httpServer.Start(addr)
}

// --- Tool definitions ---

func scanOrgTool() mcp.Tool {
	return mcp.NewTool("scan_org",
		mcp.WithDescription("Scan a GitHub organization for agentic coding adoption indicators. Returns structured results showing which repos have CLAUDE.md, MCP configs, AI workflows, evals, and other agentic coding signals."),
		mcp.WithString("org", mcp.Required(), mcp.Description("GitHub organization name to scan")),
		mcp.WithNumber("days", mcp.Description("Only include repos with activity in last N days (default: 90)")),
		mcp.WithBoolean("include_archived", mcp.Description("Include archived repos (default: false)")),
		mcp.WithBoolean("force", mcp.Description("Bypass cache and rescan everything (default: false)")),
		mcp.WithBoolean("found_only", mcp.Description("Only return results where indicator was found (default: true)")),
	)
}

func inspectRepoTool() mcp.Tool {
	return mcp.NewTool("inspect_repo",
		mcp.WithDescription("Deeply inspect the content of agentic coding indicator files found in a specific repo. Fetches and summarizes files like CLAUDE.md, MCP configs, workflow files, etc."),
		mcp.WithString("org", mcp.Required(), mcp.Description("GitHub organization name")),
		mcp.WithString("repo", mcp.Required(), mcp.Description("Repository name to inspect")),
	)
}

func listIndicatorsTool() mcp.Tool {
	return mcp.NewTool("list_indicators",
		mcp.WithDescription("List all agentic coding indicators that the scanner checks for, grouped by category."),
	)
}

func getRepoSummaryTool() mcp.Tool {
	return mcp.NewTool("get_repo_summary",
		mcp.WithDescription("Get a summary of agentic coding adoption for a specific repo from the most recent scan. Shows which indicators were found."),
		mcp.WithString("org", mcp.Required(), mcp.Description("GitHub organization name")),
		mcp.WithString("repo", mcp.Required(), mcp.Description("Repository name")),
	)
}

func getAdoptionSummaryTool() mcp.Tool {
	return mcp.NewTool("get_adoption_summary",
		mcp.WithDescription("Get an aggregate summary of agentic coding adoption across an entire org from the most recent scan. Shows adoption counts by category and top repos."),
		mcp.WithString("org", mcp.Required(), mcp.Description("GitHub organization name")),
	)
}

// --- Tool handlers ---

func makeScanHandler(cfg MCPServerConfig) server.ToolHandlerFunc {
	return func(ctx context.Context, req mcp.CallToolRequest) (*mcp.CallToolResult, error) {
		org, err := req.RequireString("org")
		if err != nil {
			return mcp.NewToolResultError(err.Error()), nil
		}

		days := req.GetInt("days", 90)
		includeArchived := req.GetBool("include_archived", false)
		force := req.GetBool("force", false)
		foundOnly := req.GetBool("found_only", true)

		ghClient := NewGitHubClient(cfg.Logger)

		cache, err := LoadCache(cfg.CacheDir)
		if err != nil {
			cache = NewCache(cfg.CacheDir)
		}

		indicators, err := resolveIndicatorsFromConfig(cfg.ConfigPath)
		if err != nil {
			return mcp.NewToolResultError(fmt.Sprintf("config error: %v", err)), nil
		}

		cutoff := time.Now().AddDate(0, 0, -days)

		scanner := &Scanner{
			Client:          ghClient,
			Cache:           cache,
			Org:             org,
			Indicators:      indicators,
			ActiveSince:     cutoff,
			IncludeArchived: includeArchived,
			Force:           force,
			Logger:          cfg.Logger,
		}

		results, err := scanner.Scan()
		if err != nil {
			return mcp.NewToolResultError(fmt.Sprintf("scan error: %v", err)), nil
		}

		if err := cache.Save(); err != nil {
			cfg.Logger.Printf("Warning: could not save cache: %v", err)
		}

		if foundOnly {
			var filtered []ScanResult
			for _, r := range results {
				if r.Found {
					filtered = append(filtered, r)
				}
			}
			results = filtered
		}

		// Build structured response
		response := ScanResponse{
			Org:        org,
			TotalRepos: countUniqueRepos(results),
			TotalFound: len(results),
			ScanTime:   time.Now().UTC().Format(time.RFC3339),
			Results:    results,
		}

		return marshalToolResult(response)
	}
}

func makeInspectHandler(cfg MCPServerConfig) server.ToolHandlerFunc {
	return func(ctx context.Context, req mcp.CallToolRequest) (*mcp.CallToolResult, error) {
		org, err := req.RequireString("org")
		if err != nil {
			return mcp.NewToolResultError(err.Error()), nil
		}
		repo, err := req.RequireString("repo")
		if err != nil {
			return mcp.NewToolResultError(err.Error()), nil
		}

		ghClient := NewGitHubClient(cfg.Logger)

		// First scan the repo to find indicators
		indicators, err := resolveIndicatorsFromConfig(cfg.ConfigPath)
		if err != nil {
			return mcp.NewToolResultError(fmt.Sprintf("config error: %v", err)), nil
		}

		cache, _ := LoadCache(cfg.CacheDir)
		if cache == nil {
			cache = NewCache(cfg.CacheDir)
		}

		scanner := &Scanner{
			Client:     ghClient,
			Cache:      cache,
			Org:        org,
			Indicators: indicators,
			ActiveSince: time.Time{}, // no time filter for single-repo
			Force:      true,
			Logger:     cfg.Logger,
		}

		// Get the repo info first
		repos, err := ghClient.ListOrgRepos(org)
		if err != nil {
			return mcp.NewToolResultError(fmt.Sprintf("error listing repos: %v", err)), nil
		}

		var targetRepo *Repo
		for _, r := range repos {
			if r.Name == repo {
				targetRepo = &r
				break
			}
		}
		if targetRepo == nil {
			return mcp.NewToolResultError(fmt.Sprintf("repo %s not found in org %s", repo, org)), nil
		}

		// Scan the single repo
		scanResults := scanner.scanRepo(*targetRepo, time.Now().UTC().Format(time.RFC3339))

		// Inspect found indicators
		var inspectResults []InspectResult
		inspector := &Inspector{
			Client: ghClient,
			Org:    org,
			Logger: cfg.Logger,
		}

		for _, sr := range scanResults {
			if !sr.Found || sr.FilePath == "" {
				continue
			}
			paths := strings.Split(sr.FilePath, "; ")
			for _, path := range paths {
				path = strings.TrimSpace(path)
				if path == "" {
					continue
				}
				content, err := inspector.Client.GetFileContent(org, repo, path)
				if err != nil {
					continue
				}
				summary := summarizeContent(sr.Category, sr.Indicator, string(content))
				inspectResults = append(inspectResults, InspectResult{
					ScanTimestamp:  time.Now().UTC().Format(time.RFC3339),
					Org:            org,
					Repo:           repo,
					Category:       sr.Category,
					Indicator:      sr.Indicator,
					FilePath:       path,
					ContentSize:    len(content),
					ContentSummary: summary,
					RawContent:     string(content),
				})
			}
		}

		return marshalToolResult(inspectResults)
	}
}

func makeListIndicatorsHandler(cfg MCPServerConfig) server.ToolHandlerFunc {
	return func(ctx context.Context, req mcp.CallToolRequest) (*mcp.CallToolResult, error) {
		indicators, err := resolveIndicatorsFromConfig(cfg.ConfigPath)
		if err != nil {
			return mcp.NewToolResultError(fmt.Sprintf("config error: %v", err)), nil
		}

		type indicatorInfo struct {
			Category    string `json:"category"`
			Name        string `json:"name"`
			SearchType  string `json:"search_type"`
			Target      string `json:"target"`
			Description string `json:"description"`
		}

		grouped := make(map[string][]indicatorInfo)
		for _, ind := range indicators {
			grouped[ind.Category] = append(grouped[ind.Category], indicatorInfo{
				Category:    ind.Category,
				Name:        ind.Name,
				SearchType:  searchTypeName(ind.SearchType),
				Target:      ind.Target,
				Description: ind.Description,
			})
		}

		return marshalToolResult(grouped)
	}
}

func makeRepoSummaryHandler(cfg MCPServerConfig) server.ToolHandlerFunc {
	return func(ctx context.Context, req mcp.CallToolRequest) (*mcp.CallToolResult, error) {
		org, err := req.RequireString("org")
		if err != nil {
			return mcp.NewToolResultError(err.Error()), nil
		}
		repo, err := req.RequireString("repo")
		if err != nil {
			return mcp.NewToolResultError(err.Error()), nil
		}

		cache, err := LoadCache(cfg.CacheDir)
		if err != nil {
			return mcp.NewToolResultError(fmt.Sprintf("no cached data available: %v", err)), nil
		}

		results := cache.GetRepoResults(org, repo)
		if results == nil {
			return mcp.NewToolResultError(fmt.Sprintf("no cached scan data for %s/%s — run scan_org first", org, repo)), nil
		}

		type repoSummary struct {
			Org        string            `json:"org"`
			Repo       string            `json:"repo"`
			Found      []CachedIndicator `json:"found_indicators"`
			TotalFound int               `json:"total_found"`
		}

		var found []CachedIndicator
		for _, r := range results {
			if r.Found {
				found = append(found, r)
			}
		}

		return marshalToolResult(repoSummary{
			Org:        org,
			Repo:       repo,
			Found:      found,
			TotalFound: len(found),
		})
	}
}

func makeAdoptionSummaryHandler(cfg MCPServerConfig) server.ToolHandlerFunc {
	return func(ctx context.Context, req mcp.CallToolRequest) (*mcp.CallToolResult, error) {
		org, err := req.RequireString("org")
		if err != nil {
			return mcp.NewToolResultError(err.Error()), nil
		}

		cache, err := LoadCache(cfg.CacheDir)
		if err != nil {
			return mcp.NewToolResultError(fmt.Sprintf("no cached data available: %v", err)), nil
		}

		type categoryCount struct {
			Category  string `json:"category"`
			RepoCount int    `json:"repo_count"`
		}
		type repoScore struct {
			Repo           string `json:"repo"`
			IndicatorCount int    `json:"indicator_count"`
		}
		type adoptionSummary struct {
			Org           string          `json:"org"`
			TotalRepos    int             `json:"total_repos"`
			ReposWithAny  int             `json:"repos_with_any_indicator"`
			ByCategory    []categoryCount `json:"by_category"`
			TopRepos      []repoScore     `json:"top_repos"`
		}

		categoryRepos := make(map[string]map[string]bool) // category -> set of repos
		repoIndicators := make(map[string]int)             // repo -> count of found indicators
		totalRepos := 0

		prefix := org + "/"
		for key, cached := range cache.data {
			if !strings.HasPrefix(key, prefix) {
				continue
			}
			repoName := strings.TrimPrefix(key, prefix)
			totalRepos++

			for _, ind := range cached.Indicators {
				if !ind.Found {
					continue
				}
				repoIndicators[repoName]++
				if categoryRepos[ind.Category] == nil {
					categoryRepos[ind.Category] = make(map[string]bool)
				}
				categoryRepos[ind.Category][repoName] = true
			}
		}

		var categories []categoryCount
		for cat, repos := range categoryRepos {
			categories = append(categories, categoryCount{
				Category:  cat,
				RepoCount: len(repos),
			})
		}

		var topRepos []repoScore
		for repo, count := range repoIndicators {
			topRepos = append(topRepos, repoScore{
				Repo:           repo,
				IndicatorCount: count,
			})
		}
		// Sort by count descending (simple bubble for small lists)
		for i := 0; i < len(topRepos); i++ {
			for j := i + 1; j < len(topRepos); j++ {
				if topRepos[j].IndicatorCount > topRepos[i].IndicatorCount {
					topRepos[i], topRepos[j] = topRepos[j], topRepos[i]
				}
			}
		}
		if len(topRepos) > 20 {
			topRepos = topRepos[:20]
		}

		reposWithAny := len(repoIndicators)

		return marshalToolResult(adoptionSummary{
			Org:          org,
			TotalRepos:   totalRepos,
			ReposWithAny: reposWithAny,
			ByCategory:   categories,
			TopRepos:     topRepos,
		})
	}
}

// --- Helpers ---

// ScanResponse is the structured response for the scan_org tool.
type ScanResponse struct {
	Org        string       `json:"org"`
	TotalRepos int          `json:"total_repos"`
	TotalFound int          `json:"total_found"`
	ScanTime   string       `json:"scan_time"`
	Results    []ScanResult `json:"results"`
}

func marshalToolResult(data any) (*mcp.CallToolResult, error) {
	jsonBytes, err := json.MarshalIndent(data, "", "  ")
	if err != nil {
		return mcp.NewToolResultError(fmt.Sprintf("marshal error: %v", err)), nil
	}
	return mcp.NewToolResultText(string(jsonBytes)), nil
}

func resolveIndicatorsFromConfig(configPath string) ([]Indicator, error) {
	var cfg *Config
	if configPath != "" {
		var err error
		cfg, err = LoadConfig(configPath)
		if err != nil {
			return nil, err
		}
	}
	return ResolveIndicators(cfg)
}

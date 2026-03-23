package main

import (
	"context"
	"encoding/csv"
	"fmt"
	"log"
	"os"
	"strings"
	"time"
)

// InspectResult represents one file's inspected content.
type InspectResult struct {
	ScanTimestamp  string
	Org            string
	Repo           string
	Category       string
	Indicator      string
	FilePath       string
	ContentSize    int
	ContentSummary string
	RawContent     string
}

// Inspector handles the deep content inspection mode.
type Inspector struct {
	Client *GitHubClient
	Org    string
	Logger *log.Logger
}

// Inspect reads scan results and fetches content for found indicators.
// scanResultsPath may be a CSV file or a Parquet file/directory.
func (insp *Inspector) Inspect(scanResultsPath string) ([]InspectResult, error) {
	var entries []foundEntry
	var err error
	if strings.HasSuffix(scanResultsPath, ".parquet") || isParquetDir(scanResultsPath) {
		entries, err = readFoundIndicatorsParquet(scanResultsPath)
	} else {
		entries, err = readFoundIndicators(scanResultsPath)
	}
	if err != nil {
		return nil, fmt.Errorf("reading scan results: %w", err)
	}

	insp.Logger.Printf("Found %d indicators to inspect", len(entries))

	now := time.Now().UTC().Format(time.RFC3339)
	var results []InspectResult

	for i, entry := range entries {
		insp.Logger.Printf("[%d/%d] Inspecting %s/%s: %s", i+1, len(entries), entry.repo, entry.filePath, entry.indicator)

		// Skip entries with multiple paths (from search results) — inspect each individually
		paths := strings.Split(entry.filePath, "; ")
		for _, path := range paths {
			path = strings.TrimSpace(path)
			if path == "" {
				continue
			}

			content, err := insp.Client.GetFileContent(insp.Org, entry.repo, path)
			if err != nil {
				insp.Logger.Printf("  Warning: could not fetch %s/%s/%s: %v", insp.Org, entry.repo, path, err)
				continue
			}

			summary := summarizeContent(entry.category, entry.indicator, string(content))

			results = append(results, InspectResult{
				ScanTimestamp:  now,
				Org:            insp.Org,
				Repo:           entry.repo,
				Category:       entry.category,
				Indicator:      entry.indicator,
				FilePath:       path,
				ContentSize:    len(content),
				ContentSummary: summary,
				RawContent:     string(content),
			})
		}
	}

	return results, nil
}

type foundEntry struct {
	repo      string
	category  string
	indicator string
	filePath  string
}

func readFoundIndicators(path string) ([]foundEntry, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer f.Close()

	reader := csv.NewReader(f)
	records, err := reader.ReadAll()
	if err != nil {
		return nil, err
	}

	if len(records) < 2 {
		return nil, nil
	}

	// Find column indices from header
	header := records[0]
	colIdx := make(map[string]int)
	for i, col := range header {
		colIdx[col] = i
	}

	required := []string{"repo", "category", "indicator", "found", "file_path"}
	for _, col := range required {
		if _, ok := colIdx[col]; !ok {
			return nil, fmt.Errorf("missing required column: %s", col)
		}
	}

	var entries []foundEntry
	for _, row := range records[1:] {
		if row[colIdx["found"]] != "true" {
			continue
		}
		filePath := row[colIdx["file_path"]]
		if filePath == "" {
			continue
		}
		entries = append(entries, foundEntry{
			repo:      row[colIdx["repo"]],
			category:  row[colIdx["category"]],
			indicator: row[colIdx["indicator"]],
			filePath:  filePath,
		})
	}

	return entries, nil
}

// isParquetDir returns true if path is a directory containing .parquet files.
func isParquetDir(path string) bool {
	info, err := os.Stat(path)
	return err == nil && info.IsDir()
}

// readFoundIndicatorsParquet reads found indicators from a Parquet scan output.
// path may be a single .parquet file or a partitioned directory.
func readFoundIndicatorsParquet(scanResultsPath string) ([]foundEntry, error) {
	store := &LocalStore{}
	files, err := store.List(context.Background(), scanResultsPath)
	if err != nil {
		// Try as a single file.
		rows, err2 := ReadScanRows(store, scanResultsPath)
		if err2 != nil {
			return nil, fmt.Errorf("reading parquet: %w", err)
		}
		return entriesFromScanRows(rows), nil
	}
	if len(files) == 0 {
		// Single file path with .parquet extension but List returned nothing.
		rows, err := ReadScanRows(store, scanResultsPath)
		if err != nil {
			return nil, err
		}
		return entriesFromScanRows(rows), nil
	}
	var all []ScanRow
	for _, f := range files {
		rows, err := ReadScanRows(store, f)
		if err != nil {
			return nil, fmt.Errorf("reading %s: %w", f, err)
		}
		all = append(all, rows...)
	}
	return entriesFromScanRows(all), nil
}

func entriesFromScanRows(rows []ScanRow) []foundEntry {
	var entries []foundEntry
	for _, r := range rows {
		if !r.Found || r.FilePath == "" {
			continue
		}
		entries = append(entries, foundEntry{
			repo:      r.Repo,
			category:  r.Category,
			indicator: r.Indicator,
			filePath:  r.FilePath,
		})
	}
	return entries
}

// summarizeContent extracts key details from file content based on indicator type.
func summarizeContent(category, indicator, content string) string {
	switch category {
	case "mcp":
		return summarizeMCP(content)
	case "evals":
		return summarizeEvals(indicator, content)
	case "claude-code":
		if indicator == "CLAUDE.md" || indicator == "AGENTS.md" {
			return summarizeMarkdown(content)
		}
		return fmt.Sprintf("%d bytes", len(content))
	default:
		return fmt.Sprintf("%d bytes", len(content))
	}
}

func summarizeMCP(content string) string {
	// Look for server names in MCP config
	var servers []string
	lines := strings.Split(content, "\n")
	for _, line := range lines {
		trimmed := strings.TrimSpace(line)
		// Look for keys that look like server names in JSON
		if strings.Contains(trimmed, ":") && !strings.Contains(trimmed, "mcpServers") {
			parts := strings.SplitN(trimmed, ":", 2)
			name := strings.Trim(strings.TrimSpace(parts[0]), `"`)
			if name != "" && !strings.HasPrefix(name, "//") && !strings.HasPrefix(name, "{") {
				servers = append(servers, name)
			}
		}
	}
	if len(servers) > 0 {
		return fmt.Sprintf("servers: %s", strings.Join(servers, ", "))
	}
	return fmt.Sprintf("%d bytes", len(content))
}

func summarizeEvals(indicator, content string) string {
	lines := strings.Split(content, "\n")
	lineCount := len(lines)
	return fmt.Sprintf("%d lines", lineCount)
}

func summarizeMarkdown(content string) string {
	lines := strings.Split(content, "\n")
	// Extract headings as summary
	var headings []string
	for _, line := range lines {
		trimmed := strings.TrimSpace(line)
		if strings.HasPrefix(trimmed, "#") {
			headings = append(headings, trimmed)
		}
	}
	if len(headings) > 0 {
		if len(headings) > 5 {
			headings = headings[:5]
		}
		return fmt.Sprintf("headings: %s", strings.Join(headings, "; "))
	}
	return fmt.Sprintf("%d lines", len(lines))
}

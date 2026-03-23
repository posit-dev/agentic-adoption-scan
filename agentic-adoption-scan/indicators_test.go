package main

import (
	"bytes"
	"testing"
)

func TestDefaultIndicatorsNotEmpty(t *testing.T) {
	indicators := DefaultIndicators()
	if len(indicators) == 0 {
		t.Fatal("DefaultIndicators() returned empty slice")
	}
}

func TestDefaultIndicatorsHaveRequiredFields(t *testing.T) {
	for _, ind := range DefaultIndicators() {
		if ind.Category == "" {
			t.Errorf("indicator %q has empty category", ind.Name)
		}
		if ind.Name == "" {
			t.Errorf("indicator in category %q has empty name", ind.Category)
		}
		if ind.Target == "" {
			t.Errorf("indicator %s/%s has empty target", ind.Category, ind.Name)
		}
		if ind.Description == "" {
			t.Errorf("indicator %s/%s has empty description", ind.Category, ind.Name)
		}
	}
}

func TestDefaultIndicatorsCategories(t *testing.T) {
	categories := make(map[string]bool)
	for _, ind := range DefaultIndicators() {
		categories[ind.Category] = true
	}

	expected := []string{
		"claude-code",
		"github-copilot",
		"cursor",
		"agents-config",
		"mcp",
		"evals",
		"workflows-ai",
	}

	for _, cat := range expected {
		if !categories[cat] {
			t.Errorf("missing expected category: %s", cat)
		}
	}
}

func TestWriteScanCSV(t *testing.T) {
	results := []ScanResult{
		{
			ScanTimestamp:  "2026-03-23T00:00:00Z",
			Org:            "test-org",
			Repo:           "test-repo",
			RepoVisibility: "public",
			RepoLanguage:   "Go",
			RepoPushedAt:   "2026-03-22T00:00:00Z",
			Category:       "claude-code",
			Indicator:      "CLAUDE.md",
			Found:          true,
			FilePath:       "CLAUDE.md",
			Details:        "",
		},
	}

	var buf bytes.Buffer
	err := WriteScanCSV(&buf, results)
	if err != nil {
		t.Fatalf("WriteScanCSV error: %v", err)
	}

	output := buf.String()
	if !bytes.Contains([]byte(output), []byte("scan_timestamp")) {
		t.Error("CSV missing header")
	}
	if !bytes.Contains([]byte(output), []byte("test-repo")) {
		t.Error("CSV missing repo data")
	}
	if !bytes.Contains([]byte(output), []byte("true")) {
		t.Error("CSV missing found=true")
	}
}

func TestCacheRoundTrip(t *testing.T) {
	dir := t.TempDir()
	cache := NewCache(dir)

	cache.SetRepoResults("org", "repo1", "2026-01-01T00:00:00Z", []CachedIndicator{
		{Category: "claude-code", Indicator: "CLAUDE.md", Found: true, FilePath: "CLAUDE.md", ScannedAt: "2026-03-23T00:00:00Z"},
	})

	if err := cache.Save(); err != nil {
		t.Fatalf("Save error: %v", err)
	}

	loaded, err := LoadCache(dir)
	if err != nil {
		t.Fatalf("LoadCache error: %v", err)
	}

	if !loaded.IsRepoFresh("org", "repo1", "2026-01-01T00:00:00Z") {
		t.Error("expected repo to be fresh")
	}

	if loaded.IsRepoFresh("org", "repo1", "2026-02-01T00:00:00Z") {
		t.Error("expected repo to be stale with different pushed_at")
	}

	results := loaded.GetRepoResults("org", "repo1")
	if len(results) != 1 {
		t.Fatalf("expected 1 cached result, got %d", len(results))
	}
	if !results[0].Found {
		t.Error("expected cached result to be found")
	}
}

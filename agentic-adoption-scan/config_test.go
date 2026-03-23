package main

import (
	"os"
	"path/filepath"
	"testing"
)

func TestLoadConfigExtendMode(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "config.yaml")
	os.WriteFile(path, []byte(`
mode: extend
indicators:
  - category: custom
    name: my-tool
    search_type: file_exists
    target: .my-tool.json
    description: Custom tool config
`), 0644)

	cfg, err := LoadConfig(path)
	if err != nil {
		t.Fatalf("LoadConfig error: %v", err)
	}
	if cfg.Mode != "extend" {
		t.Errorf("expected mode extend, got %s", cfg.Mode)
	}
	if len(cfg.Indicators) != 1 {
		t.Fatalf("expected 1 indicator, got %d", len(cfg.Indicators))
	}
}

func TestLoadConfigDefaultsToExtend(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "config.yaml")
	os.WriteFile(path, []byte(`
indicators:
  - category: custom
    name: test
    search_type: file_exists
    target: test.txt
    description: Test
`), 0644)

	cfg, err := LoadConfig(path)
	if err != nil {
		t.Fatalf("LoadConfig error: %v", err)
	}
	if cfg.Mode != "extend" {
		t.Errorf("expected default mode extend, got %s", cfg.Mode)
	}
}

func TestLoadConfigInvalidMode(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "config.yaml")
	os.WriteFile(path, []byte(`mode: invalid`), 0644)

	_, err := LoadConfig(path)
	if err == nil {
		t.Fatal("expected error for invalid mode")
	}
}

func TestResolveIndicatorsNilConfig(t *testing.T) {
	indicators, err := ResolveIndicators(nil)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(indicators) != len(DefaultIndicators()) {
		t.Errorf("expected %d defaults, got %d", len(DefaultIndicators()), len(indicators))
	}
}

func TestResolveIndicatorsExtendAdds(t *testing.T) {
	cfg := &Config{
		Mode: "extend",
		Indicators: []IndicatorConfig{
			{Category: "custom", Name: "new-thing", SearchType: "file_exists", Target: "new.json", Description: "New"},
		},
	}

	indicators, err := ResolveIndicators(cfg)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(indicators) != len(DefaultIndicators())+1 {
		t.Errorf("expected %d indicators, got %d", len(DefaultIndicators())+1, len(indicators))
	}

	// Check the custom one is present
	found := false
	for _, ind := range indicators {
		if ind.Name == "new-thing" {
			found = true
			break
		}
	}
	if !found {
		t.Error("custom indicator not found in resolved list")
	}
}

func TestResolveIndicatorsExtendOverridesByName(t *testing.T) {
	cfg := &Config{
		Mode: "extend",
		Indicators: []IndicatorConfig{
			{Category: "claude-code", Name: "CLAUDE.md", SearchType: "file_exists", Target: "CLAUDE.md", Description: "Overridden description"},
		},
	}

	indicators, err := ResolveIndicators(cfg)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	// Should not add a duplicate — count should match defaults
	if len(indicators) != len(DefaultIndicators()) {
		t.Errorf("expected %d indicators (no duplicates), got %d", len(DefaultIndicators()), len(indicators))
	}
	for _, ind := range indicators {
		if ind.Category == "claude-code" && ind.Name == "CLAUDE.md" {
			if ind.Description != "Overridden description" {
				t.Errorf("expected overridden description, got %q", ind.Description)
			}
			break
		}
	}
}

func TestResolveIndicatorsDisable(t *testing.T) {
	cfg := &Config{
		Mode:    "extend",
		Disable: []string{"CLAUDE.md", ".cursorrules"},
	}

	indicators, err := ResolveIndicators(cfg)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	for _, ind := range indicators {
		if ind.Name == "CLAUDE.md" || ind.Name == ".cursorrules" {
			t.Errorf("disabled indicator %q should not be present", ind.Name)
		}
	}
	if len(indicators) != len(DefaultIndicators())-2 {
		t.Errorf("expected %d indicators after disabling 2, got %d", len(DefaultIndicators())-2, len(indicators))
	}
}

func TestResolveIndicatorsOverrideMode(t *testing.T) {
	cfg := &Config{
		Mode: "override",
		Indicators: []IndicatorConfig{
			{Category: "custom", Name: "only-this", SearchType: "file_exists", Target: "only.txt", Description: "Only indicator"},
		},
	}

	indicators, err := ResolveIndicators(cfg)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(indicators) != 1 {
		t.Errorf("expected 1 indicator in override mode, got %d", len(indicators))
	}
	if indicators[0].Name != "only-this" {
		t.Errorf("expected only-this, got %s", indicators[0].Name)
	}
}

func TestResolveIndicatorsOverrideEmpty(t *testing.T) {
	cfg := &Config{
		Mode: "override",
	}

	_, err := ResolveIndicators(cfg)
	if err == nil {
		t.Fatal("expected error for override mode with no indicators")
	}
}

func TestParseSearchTypes(t *testing.T) {
	tests := []struct {
		input    string
		expected SearchType
	}{
		{"file_exists", FileExists},
		{"file-exists", FileExists},
		{"directory_exists", DirectoryExists},
		{"content_search", ContentSearch},
		{"content-search", ContentSearch},
		{"workflow_search", WorkflowSearch},
		{"workflow-search", WorkflowSearch},
	}

	for _, tt := range tests {
		st, err := parseSearchType(tt.input)
		if err != nil {
			t.Errorf("parseSearchType(%q): unexpected error: %v", tt.input, err)
		}
		if st != tt.expected {
			t.Errorf("parseSearchType(%q) = %v, want %v", tt.input, st, tt.expected)
		}
	}
}

func TestGenerateDefaultConfig(t *testing.T) {
	data, err := GenerateDefaultConfig()
	if err != nil {
		t.Fatalf("GenerateDefaultConfig error: %v", err)
	}
	if len(data) == 0 {
		t.Fatal("generated config is empty")
	}
	// Should be valid YAML that can be loaded back
	dir := t.TempDir()
	path := filepath.Join(dir, "config.yaml")
	os.WriteFile(path, data, 0644)

	cfg, err := LoadConfig(path)
	if err != nil {
		t.Fatalf("generated config is not valid: %v", err)
	}
	if len(cfg.Indicators) != len(DefaultIndicators()) {
		t.Errorf("generated config has %d indicators, expected %d", len(cfg.Indicators), len(DefaultIndicators()))
	}
}

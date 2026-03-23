package main

import (
	"fmt"
	"os"
	"strings"

	"gopkg.in/yaml.v3"
)

// Config represents the YAML configuration file.
type Config struct {
	// Mode controls how config indicators interact with built-in defaults.
	//   "extend"   - config indicators are added to the defaults (default behavior)
	//   "override" - config indicators replace the defaults entirely
	Mode string `yaml:"mode,omitempty"`

	// Disable is a list of built-in indicator names to exclude.
	// Only applies when mode is "extend".
	Disable []string `yaml:"disable,omitempty"`

	// Indicators defines custom indicators to scan for.
	Indicators []IndicatorConfig `yaml:"indicators,omitempty"`
}

// IndicatorConfig is the YAML representation of an Indicator.
type IndicatorConfig struct {
	Category    string `yaml:"category"`
	Name        string `yaml:"name"`
	SearchType  string `yaml:"search_type"` // file_exists, directory_exists, content_search, workflow_search
	Target      string `yaml:"target"`
	Description string `yaml:"description"`
}

// LoadConfig reads and parses a YAML config file.
func LoadConfig(path string) (*Config, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("reading config: %w", err)
	}

	var cfg Config
	if err := yaml.Unmarshal(data, &cfg); err != nil {
		return nil, fmt.Errorf("parsing config: %w", err)
	}

	if cfg.Mode == "" {
		cfg.Mode = "extend"
	}

	if cfg.Mode != "extend" && cfg.Mode != "override" {
		return nil, fmt.Errorf("invalid mode %q: must be \"extend\" or \"override\"", cfg.Mode)
	}

	return &cfg, nil
}

// ResolveIndicators merges config indicators with defaults based on mode.
func ResolveIndicators(cfg *Config) ([]Indicator, error) {
	if cfg == nil {
		return DefaultIndicators(), nil
	}

	configIndicators, err := convertIndicators(cfg.Indicators)
	if err != nil {
		return nil, err
	}

	switch cfg.Mode {
	case "override":
		if len(configIndicators) == 0 {
			return nil, fmt.Errorf("mode is \"override\" but no indicators defined in config")
		}
		return configIndicators, nil

	case "extend":
		defaults := DefaultIndicators()

		// Remove disabled indicators
		if len(cfg.Disable) > 0 {
			disableSet := make(map[string]bool)
			for _, name := range cfg.Disable {
				disableSet[strings.ToLower(name)] = true
			}
			var filtered []Indicator
			for _, ind := range defaults {
				if !disableSet[strings.ToLower(ind.Name)] {
					filtered = append(filtered, ind)
				}
			}
			defaults = filtered
		}

		// Append config indicators, replacing any with the same category+name
		byKey := make(map[string]int) // "category/name" -> index in defaults
		for i, ind := range defaults {
			byKey[ind.Category+"/"+ind.Name] = i
		}
		for _, ind := range configIndicators {
			key := ind.Category + "/" + ind.Name
			if idx, exists := byKey[key]; exists {
				defaults[idx] = ind // replace existing
			} else {
				defaults = append(defaults, ind)
			}
		}

		return defaults, nil

	default:
		return nil, fmt.Errorf("unknown mode: %s", cfg.Mode)
	}
}

func convertIndicators(configs []IndicatorConfig) ([]Indicator, error) {
	var indicators []Indicator
	for _, c := range configs {
		st, err := parseSearchType(c.SearchType)
		if err != nil {
			return nil, fmt.Errorf("indicator %q: %w", c.Name, err)
		}
		if c.Category == "" || c.Name == "" || c.Target == "" {
			return nil, fmt.Errorf("indicator %q: category, name, and target are required", c.Name)
		}
		indicators = append(indicators, Indicator{
			Category:    c.Category,
			Name:        c.Name,
			SearchType:  st,
			Target:      c.Target,
			Description: c.Description,
		})
	}
	return indicators, nil
}

func parseSearchType(s string) (SearchType, error) {
	switch strings.ToLower(s) {
	case "file_exists", "file-exists", "fileexists":
		return FileExists, nil
	case "directory_exists", "directory-exists", "directoryexists":
		return DirectoryExists, nil
	case "content_search", "content-search", "contentsearch":
		return ContentSearch, nil
	case "workflow_search", "workflow-search", "workflowsearch":
		return WorkflowSearch, nil
	default:
		return 0, fmt.Errorf("unknown search_type %q (valid: file_exists, directory_exists, content_search, workflow_search)", s)
	}
}

func searchTypeName(st SearchType) string {
	switch st {
	case FileExists:
		return "file_exists"
	case DirectoryExists:
		return "directory_exists"
	case ContentSearch:
		return "content_search"
	case WorkflowSearch:
		return "workflow_search"
	default:
		return "unknown"
	}
}

// GenerateDefaultConfig produces a YAML config file showing all built-in indicators.
func GenerateDefaultConfig() ([]byte, error) {
	defaults := DefaultIndicators()

	var configs []IndicatorConfig
	for _, ind := range defaults {
		configs = append(configs, IndicatorConfig{
			Category:    ind.Category,
			Name:        ind.Name,
			SearchType:  searchTypeName(ind.SearchType),
			Target:      ind.Target,
			Description: ind.Description,
		})
	}

	cfg := Config{
		Mode:       "extend",
		Disable:    []string{},
		Indicators: configs,
	}

	data, err := yaml.Marshal(&cfg)
	if err != nil {
		return nil, err
	}

	header := `# Agentic Adoption Scan - Indicator Configuration
#
# mode: "extend" (default) adds these indicators to built-in defaults.
#        Use "override" to replace all built-in indicators entirely.
#
# disable: list of built-in indicator names to exclude (only in extend mode).
#
# indicators: custom indicators to add or override.
#   search_type values: file_exists, directory_exists, content_search, workflow_search
#
# The indicators below are the built-in defaults, shown for reference.
# Remove or modify as needed.

`
	return append([]byte(header), data...), nil
}

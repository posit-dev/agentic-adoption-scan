package main

// SearchType defines how an indicator is checked against a repository.
type SearchType int

const (
	FileExists      SearchType = iota // Check if a file exists at a specific path
	DirectoryExists                   // Check if a directory exists at a specific path
	ContentSearch                     // Search for content patterns via Code Search API
	WorkflowSearch                    // Search within .github/workflows/ for patterns
)

// Indicator defines a single agentic coding signal to detect.
type Indicator struct {
	Category    string     // Grouping for analysis (e.g., "claude-code")
	Name        string     // Specific indicator (e.g., "CLAUDE.md")
	SearchType  SearchType // How to check for this indicator
	Target      string     // File path, directory path, or search query
	Description string     // Human-readable description
}

// DefaultIndicators returns the full registry of indicators to scan for.
// To add a new indicator, append an entry to this slice.
func DefaultIndicators() []Indicator {
	return []Indicator{
		// Claude Code
		{
			Category:    "claude-code",
			Name:        "CLAUDE.md",
			SearchType:  FileExists,
			Target:      "CLAUDE.md",
			Description: "Claude Code project instructions file",
		},
		{
			Category:    "claude-code",
			Name:        ".claude directory",
			SearchType:  DirectoryExists,
			Target:      ".claude",
			Description: "Claude Code configuration directory",
		},
		{
			Category:    "claude-code",
			Name:        "claude settings",
			SearchType:  FileExists,
			Target:      ".claude/settings.json",
			Description: "Claude Code settings file",
		},
		{
			Category:    "claude-code",
			Name:        "claude commands",
			SearchType:  DirectoryExists,
			Target:      ".claude/commands",
			Description: "Claude Code custom slash commands",
		},

		// GitHub Copilot
		{
			Category:    "github-copilot",
			Name:        "copilot instructions",
			SearchType:  FileExists,
			Target:      ".github/copilot-instructions.md",
			Description: "GitHub Copilot custom instructions",
		},
		{
			Category:    "github-copilot",
			Name:        ".copilot directory",
			SearchType:  DirectoryExists,
			Target:      ".copilot",
			Description: "GitHub Copilot configuration directory",
		},

		// Cursor
		{
			Category:    "cursor",
			Name:        ".cursorrules",
			SearchType:  FileExists,
			Target:      ".cursorrules",
			Description: "Cursor AI rules file",
		},
		{
			Category:    "cursor",
			Name:        "cursor rules dir",
			SearchType:  DirectoryExists,
			Target:      ".cursor/rules",
			Description: "Cursor AI rules directory",
		},

		// Agents config
		{
			Category:    "agents-config",
			Name:        "AGENTS.md",
			SearchType:  FileExists,
			Target:      "AGENTS.md",
			Description: "Agentic coding agents configuration",
		},
		{
			Category:    "agents-config",
			Name:        ".agents directory",
			SearchType:  DirectoryExists,
			Target:      ".agents",
			Description: "Agents configuration directory",
		},

		// MCP
		{
			Category:    "mcp",
			Name:        "mcp.json",
			SearchType:  FileExists,
			Target:      "mcp.json",
			Description: "MCP server configuration file",
		},
		{
			Category:    "mcp",
			Name:        ".mcp.json",
			SearchType:  FileExists,
			Target:      ".mcp.json",
			Description: "MCP server configuration file (dotfile)",
		},
		{
			Category:    "mcp",
			Name:        "mcp in claude settings",
			SearchType:  ContentSearch,
			Target:      "mcpServers filename:.claude/settings.json",
			Description: "MCP servers configured in Claude settings",
		},
		{
			Category:    "mcp",
			Name:        "mcp in cursor settings",
			SearchType:  ContentSearch,
			Target:      "mcpServers path:.cursor",
			Description: "MCP servers configured in Cursor settings",
		},

		// Evals
		{
			Category:    "evals",
			Name:        "evals directory",
			SearchType:  DirectoryExists,
			Target:      "evals",
			Description: "Evaluations directory",
		},
		{
			Category:    "evals",
			Name:        ".evals directory",
			SearchType:  DirectoryExists,
			Target:      ".evals",
			Description: "Evaluations directory (hidden)",
		},
		{
			Category:    "evals",
			Name:        "promptfoo config",
			SearchType:  ContentSearch,
			Target:      "filename:promptfooconfig",
			Description: "Promptfoo evaluation configuration",
		},
		{
			Category:    "evals",
			Name:        "inspect AI",
			SearchType:  ContentSearch,
			Target:      "inspect_ai filename:requirements.txt OR filename:pyproject.toml",
			Description: "Inspect AI evaluation framework dependency",
		},
		{
			Category:    "evals",
			Name:        "mcp-evals",
			SearchType:  ContentSearch,
			Target:      "mcp-evals",
			Description: "MCP evaluation framework",
		},

		// AI Workflows
		{
			Category:    "workflows-ai",
			Name:        "claude-code-action",
			SearchType:  WorkflowSearch,
			Target:      "claude-code-action",
			Description: "Claude Code GitHub Action in workflows",
		},
		{
			Category:    "workflows-ai",
			Name:        "copilot in workflows",
			SearchType:  WorkflowSearch,
			Target:      "copilot",
			Description: "GitHub Copilot references in workflows",
		},
		{
			Category:    "workflows-ai",
			Name:        "ai review actions",
			SearchType:  WorkflowSearch,
			Target:      "ai-pr-reviewer OR ai-review OR coderabbit",
			Description: "AI-powered code review actions in workflows",
		},
	}
}

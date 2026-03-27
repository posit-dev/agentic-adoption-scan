from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class SearchType(Enum):
    FILE_EXISTS = "file_exists"
    DIRECTORY_EXISTS = "directory_exists"
    CONTENT_SEARCH = "content_search"
    WORKFLOW_SEARCH = "workflow_search"


@dataclass
class Indicator:
    category: str
    name: str
    search_type: SearchType
    target: str
    description: str


def search_type_name(st: SearchType) -> str:
    """Return canonical string name for a SearchType."""
    return st.value


def default_indicators() -> list[Indicator]:
    """Return the full registry of indicators to scan for."""
    return [
        # Claude Code
        Indicator(
            category="claude-code",
            name="CLAUDE.md",
            search_type=SearchType.FILE_EXISTS,
            target="CLAUDE.md",
            description="Claude Code project instructions file",
        ),
        Indicator(
            category="claude-code",
            name=".claude directory",
            search_type=SearchType.DIRECTORY_EXISTS,
            target=".claude",
            description="Claude Code configuration directory",
        ),
        Indicator(
            category="claude-code",
            name="claude settings",
            search_type=SearchType.FILE_EXISTS,
            target=".claude/settings.json",
            description="Claude Code settings file",
        ),
        Indicator(
            category="claude-code",
            name="claude commands",
            search_type=SearchType.DIRECTORY_EXISTS,
            target=".claude/commands",
            description="Claude Code custom slash commands",
        ),
        # GitHub Copilot
        Indicator(
            category="github-copilot",
            name="copilot instructions",
            search_type=SearchType.FILE_EXISTS,
            target=".github/copilot-instructions.md",
            description="GitHub Copilot custom instructions",
        ),
        Indicator(
            category="github-copilot",
            name=".copilot directory",
            search_type=SearchType.DIRECTORY_EXISTS,
            target=".copilot",
            description="GitHub Copilot configuration directory",
        ),
        # Cursor
        Indicator(
            category="cursor",
            name=".cursorrules",
            search_type=SearchType.FILE_EXISTS,
            target=".cursorrules",
            description="Cursor AI rules file",
        ),
        Indicator(
            category="cursor",
            name="cursor rules dir",
            search_type=SearchType.DIRECTORY_EXISTS,
            target=".cursor/rules",
            description="Cursor AI rules directory",
        ),
        # Agents config
        Indicator(
            category="agents-config",
            name="AGENTS.md",
            search_type=SearchType.FILE_EXISTS,
            target="AGENTS.md",
            description="Agentic coding agents configuration",
        ),
        Indicator(
            category="agents-config",
            name=".agents directory",
            search_type=SearchType.DIRECTORY_EXISTS,
            target=".agents",
            description="Agents configuration directory",
        ),
        # MCP
        Indicator(
            category="mcp",
            name="mcp.json",
            search_type=SearchType.FILE_EXISTS,
            target="mcp.json",
            description="MCP server configuration file",
        ),
        Indicator(
            category="mcp",
            name=".mcp.json",
            search_type=SearchType.FILE_EXISTS,
            target=".mcp.json",
            description="MCP server configuration file (dotfile)",
        ),
        Indicator(
            category="mcp",
            name="mcp in claude settings",
            search_type=SearchType.CONTENT_SEARCH,
            target="mcpServers filename:.claude/settings.json",
            description="MCP servers configured in Claude settings",
        ),
        Indicator(
            category="mcp",
            name="mcp in cursor settings",
            search_type=SearchType.CONTENT_SEARCH,
            target="mcpServers path:.cursor",
            description="MCP servers configured in Cursor settings",
        ),
        # Evals
        Indicator(
            category="evals",
            name="evals directory",
            search_type=SearchType.DIRECTORY_EXISTS,
            target="evals",
            description="Evaluations directory",
        ),
        Indicator(
            category="evals",
            name=".evals directory",
            search_type=SearchType.DIRECTORY_EXISTS,
            target=".evals",
            description="Evaluations directory (hidden)",
        ),
        Indicator(
            category="evals",
            name="promptfoo config",
            search_type=SearchType.CONTENT_SEARCH,
            target="filename:promptfooconfig",
            description="Promptfoo evaluation configuration",
        ),
        Indicator(
            category="evals",
            name="inspect AI",
            search_type=SearchType.CONTENT_SEARCH,
            target="inspect_ai filename:requirements.txt OR filename:pyproject.toml",
            description="Inspect AI evaluation framework dependency",
        ),
        Indicator(
            category="evals",
            name="mcp-evals",
            search_type=SearchType.CONTENT_SEARCH,
            target="mcp-evals",
            description="MCP evaluation framework",
        ),
        # AI Workflows
        Indicator(
            category="workflows-ai",
            name="claude-code-action",
            search_type=SearchType.WORKFLOW_SEARCH,
            target="claude-code-action",
            description="Claude Code GitHub Action in workflows",
        ),
        Indicator(
            category="workflows-ai",
            name="copilot in workflows",
            search_type=SearchType.WORKFLOW_SEARCH,
            target="copilot",
            description="GitHub Copilot references in workflows",
        ),
        Indicator(
            category="workflows-ai",
            name="ai review actions",
            search_type=SearchType.WORKFLOW_SEARCH,
            target="ai-pr-reviewer OR ai-review OR coderabbit",
            description="AI-powered code review actions in workflows",
        ),
    ]

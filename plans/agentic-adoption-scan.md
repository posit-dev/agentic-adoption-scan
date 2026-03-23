# Agentic Coding Adoption Analysis Tool

## Overview

A Go CLI tool that scans all repositories in a GitHub organization to detect adoption of agentic coding tools, configurations, and workflows. Produces tidy-format CSV data suitable for visualization and historical tracking.

## Goals

- Detect presence of agentic coding indicators across an entire GitHub org
- Produce structured CSV output in tidy data format for analysis/visualization
- Support incremental scanning to avoid redundant API calls
- Support deep content inspection as a follow-up analysis pass
- Be extensible so new indicators can be added with minimal code changes

## CLI Interface

```
# Scan mode (default): detect indicator presence
agentic-adoption-scan scan --org posit-dev --output results.csv

# Inspect mode: fetch content of detected indicators
agentic-adoption-scan inspect --org posit-dev --scan-results results.csv --output inspect-results.csv

# Common flags
  --org           GitHub organization to scan (required)
  --output        Output CSV file path (default: stdout)
  --days          Only include repos with activity in last N days (default: 90)
  --include-archived  Include archived repos (default: false)
  --force         Bypass cache and rescan everything
  --since         Only scan repos active since this date (YYYY-MM-DD)
  --cache-dir     Directory for scan state cache (default: .agentic-scan-cache/)
  --verbose       Enable verbose logging
```

## Architecture

### Directory Structure

```
agentic-adoption-scan/
├── main.go              # CLI entrypoint, flag parsing, subcommand dispatch
├── scanner.go           # Orchestration: repo listing, indicator checking, caching
├── indicators.go        # Indicator registry (extensible list of what to detect)
├── github.go            # GitHub API client: rate limiting, search, contents endpoints
├── cache.go             # Scan state persistence and invalidation
├── inspect.go           # Deep content inspection mode
├── output.go            # CSV writing in tidy data format
├── go.mod
└── go.sum
```

### Two-Mode Architecture

#### Scan Mode

Detects the presence or absence of agentic coding indicators across repos. Uses GitHub API only (no cloning).

**Flow:**

1. List all repos in the org (filtered by activity, archived status)
2. For each repo, check the cache — skip if `repo.pushed_at` hasn't changed since last scan
3. For each uncached/stale repo, run all registered indicators against GitHub API
4. Write results to tidy CSV
5. Update the cache

#### Inspect Mode

For repos where indicators were found in scan mode, fetches and analyzes the actual file contents.

**Flow:**

1. Read the scan results CSV to identify repos with found indicators
2. For each found indicator, fetch the file content via GitHub Contents API
3. Produce a second CSV with content details (raw content, summaries)

### Incremental Scanning / Cache

A local JSON state file stores scan results keyed by `(org, repo, indicator)`:

```json
{
  "posit-dev/vetiver-python": {
    "pushed_at": "2026-03-20T12:00:00Z",
    "scanned_at": "2026-03-22T08:30:00Z",
    "indicators": {
      "claude-code/CLAUDE.md": { "found": true, "file_path": "CLAUDE.md" },
      "cursor/.cursorrules": { "found": false }
    }
  }
}
```

On re-run, a repo is skipped if its `pushed_at` from the GitHub API matches the cached value. The `--force` flag bypasses this check entirely.

### Extensible Indicator Registry

Indicators are defined as a Go slice of structs. Adding a new indicator requires appending one entry:

```go
type Indicator struct {
    Category    string            // Grouping for analysis (e.g., "claude-code")
    Name        string            // Specific indicator (e.g., "CLAUDE.md")
    SearchType  SearchType        // FileExists, DirectoryExists, ContentSearch, WorkflowSearch
    Target      string            // File path, directory path, or search query
    Description string            // Human-readable description
}
```

Search types:
- **FileExists** — Check if a specific file exists via Contents API (`/repos/{owner}/{repo}/contents/{path}`)
- **DirectoryExists** — Check if a directory exists via Contents API
- **ContentSearch** — Search for content patterns via Code Search API (`/search/code?q=...`)
- **WorkflowSearch** — Search specifically within `.github/workflows/` for patterns

### Indicator List

| Category | Name | Search Type | Target |
|----------|------|-------------|--------|
| **claude-code** | CLAUDE.md | FileExists | `CLAUDE.md` |
| **claude-code** | .claude directory | DirectoryExists | `.claude` |
| **claude-code** | claude settings | FileExists | `.claude/settings.json` |
| **claude-code** | claude commands | DirectoryExists | `.claude/commands` |
| **github-copilot** | copilot instructions | FileExists | `.github/copilot-instructions.md` |
| **github-copilot** | .copilot directory | DirectoryExists | `.copilot` |
| **cursor** | .cursorrules | FileExists | `.cursorrules` |
| **cursor** | cursor rules dir | DirectoryExists | `.cursor/rules` |
| **agents-config** | AGENTS.md | FileExists | `AGENTS.md` |
| **agents-config** | .agents directory | DirectoryExists | `.agents` |
| **mcp** | mcp.json | FileExists | `mcp.json` |
| **mcp** | .mcp.json | FileExists | `.mcp.json` |
| **mcp** | mcp in claude settings | ContentSearch | `mcpServers` in `.claude/settings.json` |
| **mcp** | mcp in cursor settings | ContentSearch | `mcpServers` in `.cursor/` |
| **evals** | evals directory | DirectoryExists | `evals` |
| **evals** | .evals directory | DirectoryExists | `.evals` |
| **evals** | promptfoo config | ContentSearch | `filename:promptfooconfig` |
| **evals** | inspect AI | ContentSearch | `inspect_ai` in `requirements*.txt` or `pyproject.toml` |
| **evals** | mcp-evals | ContentSearch | `mcp-evals` |
| **workflows-ai** | claude-code-action | WorkflowSearch | `claude-code-action` in `.github/workflows/` |
| **workflows-ai** | copilot in workflows | WorkflowSearch | `copilot` in `.github/workflows/` |
| **workflows-ai** | ai review actions | WorkflowSearch | AI PR review action references |

### Output Format

#### Scan CSV (tidy data)

Each row is one observation of (repo, indicator):

| Column | Type | Description |
|--------|------|-------------|
| `scan_timestamp` | ISO 8601 | When the scan was performed |
| `org` | string | GitHub organization |
| `repo` | string | Repository name |
| `repo_visibility` | string | public / private / internal |
| `repo_language` | string | Primary language of the repo |
| `repo_pushed_at` | ISO 8601 | Last push timestamp |
| `category` | string | Indicator category |
| `indicator` | string | Indicator name |
| `found` | boolean | Whether the indicator was detected |
| `file_path` | string | Path where found (empty if not found) |
| `details` | string | Additional context if available |

#### Inspect CSV

| Column | Type | Description |
|--------|------|-------------|
| `scan_timestamp` | ISO 8601 | When the inspection was performed |
| `org` | string | GitHub organization |
| `repo` | string | Repository name |
| `category` | string | Indicator category |
| `indicator` | string | Indicator name |
| `file_path` | string | Path of inspected file |
| `content_size` | int | Size of file in bytes |
| `content_summary` | string | Extracted key details (e.g., MCP server names) |
| `raw_content` | string | Full file content (escaped for CSV) |

### GitHub API Strategy

#### Endpoints Used

- **List org repos:** `GET /orgs/{org}/repos` — paginated, sorted by pushed, filtered by type
- **Check file/dir existence:** `GET /repos/{owner}/{repo}/contents/{path}` — 200 = exists, 404 = doesn't
- **Code search:** `GET /search/code?q={query}+repo:{owner}/{repo}` — for content pattern matching
- **Get file content:** `GET /repos/{owner}/{repo}/contents/{path}` (with accept: raw) — for inspect mode

#### Rate Limiting

- Track `X-RateLimit-Remaining` and `X-RateLimit-Reset` headers on every response
- When remaining < 10, sleep until reset time
- On 403 rate limit response, use exponential backoff (1s, 2s, 4s, 8s) with jitter
- Code Search API has a separate, stricter limit (30 req/min) — enforce a per-second throttle for search calls
- Log rate limit status in verbose mode

#### Authentication

- Use the `gh` CLI's auth token via `gh auth token` for API authentication
- This ensures the tool works with whatever auth the user already has configured

## Implementation Phases

### Phase 1: Core scan mode
- CLI entrypoint with flag parsing
- GitHub API client with rate limiting
- Repo listing with filtering
- Indicator registry with all indicators
- File/directory existence checks
- CSV output

### Phase 2: Content search indicators
- Code Search API integration
- Workflow-specific search
- All content-based indicators

### Phase 3: Cache layer
- JSON state file read/write
- Cache invalidation by `pushed_at`
- `--force` flag support

### Phase 4: Inspect mode
- Read scan results CSV
- Fetch file contents for found indicators
- Content summarization
- Inspect CSV output

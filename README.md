# eng-effectiveness-metrics-tools

Tools for measuring and tracking engineering effectiveness, with a focus on agentic coding tool adoption.

---

## agentic-adoption-scan

A CLI tool that scans all repositories in a GitHub organization to detect adoption of agentic coding tools (Claude Code, GitHub Copilot, Cursor, MCP servers, evals frameworks, and more). Produces tidy-format CSV data suitable for analysis and visualization.

### Install

**macOS** (Intel and Apple Silicon):

```bash
curl -fsSL "https://github.com/posit-dev/eng-effectiveness-metrics-tools/releases/latest/download/agentic-adoption-scan_darwin_$(uname -m | sed 's/x86_64/amd64/').tar.gz" | tar -xz && sudo mv agentic-adoption-scan /usr/local/bin/
```

**Linux** (x86\_64 and arm64):

```bash
curl -fsSL "https://github.com/posit-dev/eng-effectiveness-metrics-tools/releases/latest/download/agentic-adoption-scan_linux_$(uname -m | sed 's/x86_64/amd64/;s/aarch64/arm64/').tar.gz" | tar -xz && sudo mv agentic-adoption-scan /usr/local/bin/
```

**Via pip/pipx** (macOS, Linux, Windows):

```bash
pipx install agentic-adoption-scan
```

### Prerequisites

The tool uses the `gh` CLI for GitHub authentication. Make sure you have it installed and authenticated:

```bash
gh auth login
```

### Usage

**Scan an organization for agentic tool indicators:**

```bash
agentic-adoption-scan scan --org your-org --output results.csv
```

**Fetch and analyze content of detected indicators:**

```bash
agentic-adoption-scan inspect --org your-org --scan-results results.csv --output inspect-results.csv
```

**Generate a customizable indicators config file:**

```bash
agentic-adoption-scan init-config --output indicators.yaml
```

**Run as an MCP server for Claude Code integration:**

```bash
agentic-adoption-scan serve
```

### Scan flags

| Flag | Default | Description |
|------|---------|-------------|
| `--org` | (required) | GitHub organization to scan |
| `--output` | stdout | Output CSV file path |
| `--days` | 90 | Only include repos active in the last N days |
| `--include-archived` | false | Include archived repos |
| `--force` | false | Bypass cache and rescan everything |
| `--cache-dir` | `.agentic-scan-cache` | Directory for scan state cache |
| `--config` | | Path to custom indicators YAML config |
| `--verbose` | false | Enable verbose logging |

### What it detects

The tool checks for 25+ built-in indicators across 7 categories:

| Category | Examples |
|----------|---------|
| `claude-code` | `CLAUDE.md`, `.claude/` directory, `settings.json`, custom commands |
| `github-copilot` | `copilot-instructions.md`, `.copilot/` directory |
| `cursor` | `.cursorrules`, `.cursor/rules/` directory |
| `agents-config` | `AGENTS.md`, `.agents/` directory |
| `mcp` | `mcp.json`, `.mcp.json`, MCP server configs |
| `evals` | evals directories, promptfoo, inspect\_ai, mcp-evals |
| `workflows-ai` | claude-code-action, Copilot references, AI review actions |

You can extend or override these indicators via a YAML config file (`init-config` generates a starter).

### Output format

Scan results are written as tidy CSV — one row per (repo × indicator) observation:

```
scan_timestamp,org,repo,repo_visibility,repo_language,repo_pushed_at,category,indicator,found,file_path,details
```

This format makes it easy to filter, pivot, and visualize in R, Python, or any BI tool.

### MCP server

The tool can run as an MCP server, exposing tools for use directly within Claude Code:

```json
{
  "mcpServers": {
    "agentic-adoption-scan": {
      "command": "agentic-adoption-scan",
      "args": ["serve"]
    }
  }
}
```

Available MCP tools: `scan_org`, `inspect_repo`, `list_indicators`, `get_repo_summary`, `get_adoption_summary`.

---

## Other scripts

**Record a deployment event into GitHub:**

```bash
./record-deployment.sh posit-dev/eng-effectiveness-metrics-tools main testing
```

---

## Releases

Releases are fully automated via [python-semantic-release](https://python-semantic-release.readthedocs.io/) on every merge to `main`. The version bump is determined automatically from [Conventional Commit](https://www.conventionalcommits.org/) PR titles (enforced by the `pr-title` workflow):

| PR title prefix | Version bump |
|---|---|
| `fix:` | patch — `0.1.0` → `0.1.1` |
| `feat:` | minor — `0.1.1` → `0.2.0` |
| `feat!:` / `BREAKING CHANGE:` | major — `0.2.0` → `1.0.0` |
| `chore:`, `docs:`, `refactor:`, etc. | no release |

On every merge to `main`, semantic-release analyzes commits since the last tag. If there are releasable changes, it creates a `CHANGELOG.md` entry, commits it, tags the new version (e.g. `v0.2.0`), and publishes a GitHub release — all in one step. That tag push then triggers the publish workflow, which:

1. Builds native binaries for macOS (amd64/arm64) and Linux (amd64/arm64) via [GoReleaser](https://goreleaser.com/)
2. Publishes Python wheels for all platforms to [PyPI](https://pypi.org/project/agentic-adoption-scan/) via [go-to-wheel](https://github.com/simonw/go-to-wheel)

### One-time setup required

**Deploy key** — semantic-release pushes back to `main` and needs to trigger the publish workflow. The default `GITHUB_TOKEN` cannot do this, so an SSH deploy key is required:

```bash
ssh-keygen -t ed25519 -C "semantic-release" -f deploy_key -N ""
```

1. Add `deploy_key.pub` as a repo **Deploy key** with write access: _Settings → Deploy keys_
2. Add `deploy_key` (private) as an Actions secret named **`DEPLOY_KEY`**: _Settings → Secrets and variables → Actions_

**PyPI Trusted Publisher** — the publish workflow uses [OIDC Trusted Publishing](https://docs.pypi.org/trusted-publishers/) (no API token needed). Configure a Trusted Publisher on PyPI for this repository pointing to the `publish.yml` workflow and the `pypi` environment.

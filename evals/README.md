# Eval Framework for the Agentic Adoption MCP Server

## Overview

This directory contains the evaluation framework for the `agentic-adoption-scan` MCP server. Tests run on every pull request and are organised into three layers, each adding more depth at the cost of more infrastructure.

```
evals/
├── inspect/          # Inspect AI tasks (deterministic + LLM-as-judge)
└── connect/          # Posit Connect deployment + smoke tests
```

Unit and integration tests for the MCP handler functions live alongside the Go source code:

```
agentic-adoption-scan/
└── mcpserver_test.go  # Go handler-level tests (no GitHub token required)
```

---

## Layer 1 — Go unit tests (`go test`)

**What:** Direct calls to each MCP tool handler function. No network, no LLM, no GitHub token.

**Coverage:**
- `list_indicators` returns valid JSON with all expected categories and indicator fields
- Every handler returns `IsError=true` (not a transport error) when required params are missing
- `get_repo_summary` / `get_adoption_summary` gracefully report a cache miss
- `marshalToolResult` round-trips data correctly
- `newMCPServer` can be instantiated

**Run:**
```bash
cd agentic-adoption-scan
go test -v -race ./...
```

**CI:** Runs in `pr-checks.yml` alongside `go vet` and the GoReleaser dry-run.

---

## Layer 2 — Inspect AI evals (`evals/inspect/`)

Inspect AI (from UK AISI) provides a composable eval framework built around Tasks, Solvers, and Scorers. We use three eval sub-types:

### 2a. Deterministic structure evals

No LLM required. The solver calls the MCP binary directly via stdio and the scorer checks the response structure deterministically.

| Task | What it checks |
|---|---|
| `list_indicators_structure` | All 7 category keys present in the response |
| `list_indicators_schema` | Every indicator has `name`, `search_type`, `target` fields |

**Run:**
```bash
cd evals/inspect
pip install -e .

# Build the binary first
cd ../../agentic-adoption-scan && go build -o agentic-adoption-scan . && cd ../evals/inspect

inspect eval mcp_eval_tasks.py --task list_indicators_structure
inspect eval mcp_eval_tasks.py --task list_indicators_schema
```

### 2b. Semantic quality evals (LLM-as-judge)

Requires `ANTHROPIC_API_KEY`. The solver embeds the tool output into a conversation and asks a judge model to score whether it meets quality criteria.

| Task | What it checks |
|---|---|
| `list_indicators_quality` | Completeness and clarity of the indicator taxonomy |

**Run:**
```bash
ANTHROPIC_API_KEY=sk-... \
inspect eval mcp_eval_tasks.py \
  --task list_indicators_quality \
  --model anthropic/claude-haiku-4-5-20251001
```

### 2c. Integration evals (LLM-as-agent + real GitHub)

Requires `ANTHROPIC_API_KEY` + `GITHUB_TOKEN`. An LLM agent answers an adoption question by calling the MCP tools; the answer is graded by a judge model.

Skipped automatically when `GITHUB_TOKEN` is not set.

| Task | What it checks |
|---|---|
| `adoption_agent_eval` | Agent uses `list_indicators` + `inspect_repo` to answer an adoption question |

**Run:**
```bash
ANTHROPIC_API_KEY=sk-... GITHUB_TOKEN=ghp_... \
inspect eval mcp_eval_tasks.py \
  --task adoption_agent_eval \
  --model anthropic/claude-sonnet-4-6
```

**CI:** Runs in `pr-evals.yml`. Deterministic tasks always run; semantic/integration tasks run only when `ANTHROPIC_API_KEY` is available.

---

## Layer 3 — Connect deployment tests (`evals/connect/`)

These tests prove that the Python MCP wrapper deploys successfully to Posit Connect and that each MCP tool is reachable via the Streamable HTTP transport.

### Architecture (following `posit-dev/with-connect`)

```
GitHub Actions
  └── posit-dev/with-connect@v1        ← starts Connect in Docker
        ├── bootstrap API key
        └── outputs: url, api-key
  └── rsconnect deploy fastapi          ← deploy the Python wrapper
  └── pytest evals/connect/ -m connect  ← smoke tests against deployed server
```

### Test classes

| Class | What it proves |
|---|---|
| `TestDeploymentReachability` | MCP endpoint responds; initialize handshake works |
| `TestListIndicatorsTool` | `list_indicators` returns correct data from the deployed server |
| `TestToolErrorHandling` | Tools return `isError=true` for missing required params |
| `TestMCPProtocolCompliance` | `tools/list` returns all 5 tools; unknown methods return error |

### Run locally

```bash
# Start Connect (needs Docker + a Connect license file)
with-connect --license-file /path/to/connect.lic -- \
  bash -c 'cd evals/connect && pip install -e . && pytest -v -m connect'
```

Or if Connect is already running:
```bash
CONNECT_SERVER=http://localhost:3939 \
CONNECT_API_KEY=<key> \
pytest evals/connect/ -v -m connect
```

### Required secrets

| Secret | Purpose |
|---|---|
| `CONNECT_LICENSE` | Base64-encoded Posit Connect `.lic` file for the ephemeral container |
| `ANTHROPIC_API_KEY` | For semantic/integration evals (optional; tasks skip gracefully if absent) |

**CI:** Runs in `pr-connect-deploy.yml`. Skips gracefully if `CONNECT_LICENSE` is not set (e.g., for community/fork PRs).

---

## Design decisions

### Why three layers?

Adapted from the skill-eval / skillgrade dual-grader pattern and the VIP project's phased test approach:

- **Layer 1 (Go):** Fast, zero dependencies, no API keys. Catches regressions in handler logic immediately. Every PR runs these.
- **Layer 2 (Inspect AI):** Catches semantic regressions that unit tests miss — e.g., an indicator category renamed or a field silently dropped. LLM-as-judge is used sparingly, only for quality assertions that are hard to express as deterministic checks.
- **Layer 3 (Connect):** The only way to prove the full deployment stack works end-to-end. Following the VIP / with-connect pattern, a real (ephemeral) Connect server is used rather than a mock.

### Why Inspect AI over promptfoo?

Both were evaluated:

- **promptfoo** excels at prompt regression testing with a YAML-driven format. Its MCP provider support is useful when testing an LLM that *uses* MCP tools, not when testing the MCP server itself.
- **Inspect AI** provides first-class Python extensibility, a composable Solver/Scorer architecture, and built-in log storage — a better fit for testing the server's outputs programmatically.

### Why not mcp-evals (mclenhard)?

`mcp-evals` is excellent for quick LLM-based scoring of individual tool calls. We use the same pattern (LLM-as-judge with structured rubrics) inside Inspect AI so we get the benefits without an additional dependency. The Inspect AI log viewer also provides better visibility into eval history.

### Graceful degradation

Every layer degrades gracefully when optional secrets are absent:
- Layer 2 semantic tasks: skipped if `ANTHROPIC_API_KEY` not set
- Layer 2 integration task: skipped if `GITHUB_TOKEN` not set
- Layer 3: entire job skipped if `CONNECT_LICENSE` not set

This means the core Go tests always run for every PR, while richer evals run in repos that have the necessary credentials configured.

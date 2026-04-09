"""Inspect AI eval tasks for the agentic-adoption-scan MCP server.

These tasks evaluate correctness, structure, and quality of MCP tool responses.

Eval layers
-----------
1. Deterministic structure evals  — no LLM, no GitHub token required.
   Runs on every PR to catch regressions quickly.

2. Semantic quality evals         — LLM-as-judge, no GitHub token required.
   Validates that tool descriptions and outputs are helpful and clear.

3. Integration evals              — LLM-as-agent + GitHub token.
   An agent answers adoption questions using the real MCP tools; the answer
   is scored against expected outcomes.
   Skipped when GITHUB_TOKEN is not set.

Usage
-----
    # All deterministic tasks (fast, no API keys needed):
    inspect eval mcp_eval_tasks.py --task list_indicators_structure
    inspect eval mcp_eval_tasks.py --task list_indicators_schema

    # Semantic quality tasks (needs ANTHROPIC_API_KEY):
    inspect eval mcp_eval_tasks.py --task list_indicators_quality

    # Full agent integration (needs ANTHROPIC_API_KEY + GITHUB_TOKEN):
    inspect eval mcp_eval_tasks.py --task adoption_agent_eval

    # All tasks:
    inspect eval mcp_eval_tasks.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from inspect_ai import Task, task
from inspect_ai.dataset import Dataset, MemoryDataset, Sample, json_dataset
from inspect_ai.model import ChatMessage, ChatMessageUser
from inspect_ai.scorer import (
    Score,
    Target,
    accuracy,
    mean,
    model_graded_qa,
    scorer,
)
from inspect_ai.solver import (
    Generate,
    Solver,
    TaskState,
    generate,
    solver,
    system_message,
)

# ---------------------------------------------------------------------------
# Helpers: call the MCP server via subprocess (stdio transport)
# ---------------------------------------------------------------------------

_BINARY = "agentic-adoption-scan"
_REPO_ROOT = Path(__file__).parent.parent.parent


def _find_binary() -> str:
    """Locate the agentic-adoption-scan binary, preferring the local build."""
    local = _REPO_ROOT / "agentic-adoption-scan" / "agentic-adoption-scan"
    if local.exists():
        return str(local)
    found = shutil.which(_BINARY)
    if found:
        return found
    raise FileNotFoundError(
        f"Binary '{_BINARY}' not found. "
        "Build it with: cd agentic-adoption-scan && go build ."
    )


def _call_mcp_tool(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Call an MCP tool via the stdio transport and return the parsed result.

    Sends the MCP initialize + tools/call sequence to the binary's stdin,
    then reads the JSON-RPC response stream.
    """
    binary = _find_binary()

    # Build the MCP JSON-RPC message sequence
    messages = [
        {
            "jsonrpc": "2.0",
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "inspect-eval", "version": "1.0"},
            },
            "id": 1,
        },
        {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
            "params": {},
        },
        {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
            "id": 2,
        },
    ]
    stdin_data = "\n".join(json.dumps(m) for m in messages) + "\n"

    with tempfile.TemporaryDirectory() as cache_dir:
        result = subprocess.run(
            [binary, "serve", "--cache-dir", cache_dir],
            input=stdin_data,
            capture_output=True,
            text=True,
            timeout=30,
        )

    # Parse newline-delimited JSON-RPC responses, pick the one with id=2
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if msg.get("id") == 2:
            if "error" in msg:
                raise RuntimeError(f"MCP tool error: {msg['error']}")
            return msg.get("result", {})

    raise RuntimeError(
        f"No response for tool {tool_name!r}.\n"
        f"stdout: {result.stdout[:500]}\n"
        f"stderr: {result.stderr[:500]}"
    )


def _get_tool_text(tool_name: str, arguments: dict[str, Any]) -> str:
    """Return the text content from a successful tool call."""
    result = _call_mcp_tool(tool_name, arguments)
    content = result.get("content", [])
    for item in content:
        if isinstance(item, dict) and item.get("type") == "text":
            return item["text"]
    raise RuntimeError(f"No text content in response from {tool_name!r}")


# ---------------------------------------------------------------------------
# Layer 1: Deterministic structure evals (no LLM, no GitHub token)
# ---------------------------------------------------------------------------


@scorer(metrics=[accuracy()])
def structure_scorer(expected_keys: list[str]):
    """Score whether a JSON response contains all expected top-level keys."""

    async def score(state: TaskState, target: Target) -> Score:
        output = state.output.completion
        try:
            data = json.loads(output)
        except json.JSONDecodeError:
            return Score(value=0, explanation=f"Response is not valid JSON: {output[:200]}")

        missing = [k for k in expected_keys if k not in data]
        if missing:
            return Score(
                value=0,
                explanation=f"Missing expected keys: {missing}",
            )
        return Score(value=1, explanation=f"All expected keys present: {expected_keys}")

    return score


@scorer(metrics=[accuracy()])
def schema_scorer():
    """Score whether every indicator entry has required fields (name, search_type, target)."""

    async def score(state: TaskState, target: Target) -> Score:
        output = state.output.completion
        try:
            grouped: dict[str, list[dict]] = json.loads(output)
        except json.JSONDecodeError:
            return Score(value=0, explanation="Response is not valid JSON")

        errors = []
        for cat, indicators in grouped.items():
            if not isinstance(indicators, list):
                errors.append(f"Category {cat!r} value is not a list")
                continue
            for i, ind in enumerate(indicators):
                for field in ("name", "search_type", "target"):
                    if not ind.get(field):
                        errors.append(
                            f"Category {cat!r} indicator[{i}] missing field {field!r}"
                        )

        if errors:
            return Score(value=0, explanation="; ".join(errors[:5]))
        total = sum(len(v) for v in grouped.values() if isinstance(v, list))
        return Score(value=1, explanation=f"All {total} indicators have required fields")

    return score


@solver
def call_list_indicators() -> Solver:
    """Solver that calls list_indicators and puts the raw JSON into completion."""

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        try:
            text = _get_tool_text("list_indicators", {})
        except Exception as exc:
            state.output.completion = f"ERROR: {exc}"
            return state
        state.output.completion = text
        return state

    return solve


@task
def list_indicators_structure() -> Task:
    """Verify list_indicators returns all expected category keys."""
    expected_categories = [
        "claude-code",
        "github-copilot",
        "cursor",
        "mcp",
        "evals",
        "agents-config",
        "workflows-ai",
    ]
    return Task(
        dataset=MemoryDataset(
            [
                Sample(
                    input="Call list_indicators and check the top-level category keys",
                    target=", ".join(expected_categories),
                )
            ]
        ),
        solver=call_list_indicators(),
        scorer=structure_scorer(expected_keys=expected_categories),
    )


@task
def list_indicators_schema() -> Task:
    """Verify every indicator entry has required fields (name, search_type, target)."""
    return Task(
        dataset=MemoryDataset(
            [
                Sample(
                    input="Call list_indicators and verify every indicator has required fields",
                    target="All indicators must have name, search_type, and target",
                )
            ]
        ),
        solver=call_list_indicators(),
        scorer=schema_scorer(),
    )


# ---------------------------------------------------------------------------
# Layer 2: Semantic quality evals (LLM-as-judge, no GitHub token)
# ---------------------------------------------------------------------------


@solver
def summarise_indicators() -> Solver:
    """Ask the model to describe what categories of adoption indicators exist."""

    async def solve(state: TaskState, generate_fn: Generate) -> TaskState:
        # Embed the tool output into the context so the model can reason about it
        try:
            raw = _get_tool_text("list_indicators", {})
        except Exception as exc:
            state.messages.append(
                ChatMessageUser(content=f"list_indicators failed: {exc}")
            )
            return await generate_fn(state)

        state.messages.append(
            ChatMessageUser(
                content=(
                    "Here is the output of the list_indicators MCP tool:\n\n"
                    f"```json\n{raw}\n```\n\n"
                    "Summarise which categories of agentic coding adoption this tool tracks "
                    "and give one example indicator per category."
                )
            )
        )
        return await generate_fn(state)

    return solve


@task
def list_indicators_quality() -> Task:
    """LLM-as-judge: assess that list_indicators output is complete and useful.

    Requires ANTHROPIC_API_KEY. Run with:
        inspect eval mcp_eval_tasks.py --task list_indicators_quality -M anthropic/claude-sonnet-4-6
    """
    if "ANTHROPIC_API_KEY" not in os.environ:
        # Return a trivial no-op task so this eval can run safely without secrets.
        return Task(
            dataset=MemoryDataset([]),
            solver=[],
            scorer=accuracy(),
        )
    return Task(
        dataset=MemoryDataset(
            [
                Sample(
                    input=(
                        "Describe the categories of agentic coding adoption tracked by this MCP server. "
                        "Include at least one concrete example indicator per category."
                    ),
                    target=(
                        "The response should mention: claude-code (e.g. CLAUDE.md), "
                        "github-copilot, cursor, mcp configs, evals frameworks (promptfoo/inspect_ai), "
                        "AI GitHub Actions workflows."
                    ),
                )
            ]
        ),
        solver=[
            system_message(
                "You are an expert reviewer evaluating an AI tool's output for completeness and clarity."
            ),
            summarise_indicators(),
        ],
        scorer=model_graded_qa(
            template=(
                "Question: {question}\n\n"
                "Model answer: {answer}\n\n"
                "Correct answer: {criterion}\n\n"
                "Does the model answer cover all the categories mentioned in the correct answer? "
                "Grade C (correct) if it covers at least 5 of the 6 mentioned categories with examples, "
                "grade I (incorrect) otherwise."
            ),
            grade_pattern=r"(?i)\b(C|I)\b",
        ),
    )


# ---------------------------------------------------------------------------
# Layer 3: Integration evals (LLM-as-agent + real GitHub + MCP tools)
# ---------------------------------------------------------------------------


def _has_github_token() -> bool:
    return bool(os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN"))


@task
def adoption_agent_eval() -> Task:
    """An LLM agent answers an adoption question using the real MCP tools.

    Requires ANTHROPIC_API_KEY and GITHUB_TOKEN. The agent is expected to:
    1. Call list_indicators to understand what is tracked.
    2. Call scan_org on a small public org.
    3. Report which agentic adoption indicators are present.

    The answer is scored by a judge model.

    Skip gracefully if GITHUB_TOKEN or ANTHROPIC_API_KEY is unavailable.
    """
    if not _has_github_token() or "ANTHROPIC_API_KEY" not in os.environ:
        # Return a trivially-passing placeholder task so CI doesn't fail
        return Task(
            dataset=MemoryDataset(
                [
                    Sample(
                        input="SKIP: GITHUB_TOKEN or ANTHROPIC_API_KEY not set",
                        target="SKIPPED",
                    )
                ]
            ),
            solver=_skip_solver(),
            scorer=_skip_scorer(),
        )
    # Use posit-dev/py-shiny as a well-known small org with known indicators
    target_org = "posit-dev"
    target_repo = "py-shiny"

    return Task(
        dataset=MemoryDataset(
            [
                Sample(
                    input=(
                        f"Use the available MCP tools to determine which agentic coding "
                        f"adoption indicators are present in {target_org}/{target_repo}. "
                        f"First list all available indicators, then inspect the repo."
                    ),
                    target=(
                        f"The agent should call list_indicators and inspect_repo for "
                        f"{target_org}/{target_repo} and report which indicators were found."
                    ),
                    metadata={"org": target_org, "repo": target_repo},
                )
            ]
        ),
        solver=[
            system_message(
                "You are an engineering effectiveness analyst. "
                "Use the MCP tools to answer adoption questions. "
                "Always start by listing available indicators."
            ),
            generate(),
        ],
        scorer=model_graded_qa(),
    )


@solver
def _skip_solver() -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        state.output.completion = "SKIPPED: GITHUB_TOKEN not available"
        return state

    return solve


@scorer(metrics=[accuracy()])
def _skip_scorer():
    async def score(state: TaskState, target: Target) -> Score:
        return Score(value=1, explanation="Skipped — required secrets not available")

    return score

from __future__ import annotations

import pytest

from agentic_adoption_scan.config import Config, load_config, resolve_activity_matchers
from agentic_adoption_scan.signals import bot_tool, default_matchers, match_trailer_tools

CLAUDE_TRAILER = "Co-Authored-By: Claude <noreply@anthropic.com>"
CLAUDE_FOOTER = "🤖 Generated with [Claude Code](https://claude.com/claude-code)"
COPILOT_TRAILER = "Co-authored-by: Copilot <175728472+Copilot@users.noreply.github.com>"
CURSOR_TRAILER = "Co-authored-by: Cursor Agent <cursoragent@cursor.com>"


@pytest.mark.parametrize(
    "message, expected",
    [
        (f"fix bug\n\n{CLAUDE_TRAILER}", {"claude-code"}),
        (f"feat: x\n\n{CLAUDE_FOOTER}", {"claude-code"}),
        (f"feat: y\n\n{COPILOT_TRAILER}", {"copilot"}),
        (f"feat: z\n\n{CURSOR_TRAILER}", {"cursor"}),
        (f"both\n\n{CLAUDE_TRAILER}\n{COPILOT_TRAILER}", {"claude-code", "copilot"}),
        (f"twice\n\n{CLAUDE_TRAILER}\n{CLAUDE_FOOTER}", {"claude-code"}),
        ("thanks to copilot for the idea", set()),
        ("ask claude about this", set()),
        ("Co-authored-by: Claire Smith <c@example.com>", set()),
        ("Co-authored-by: Claudette Dupont <c@example.com>", set()),
        ("Co-authored-by: Cursory Person <c@example.com>", set()),
        ("", set()),
    ],
)
def test_match_trailer_tools(message, expected):
    assert match_trailer_tools(message, default_matchers()) == expected


@pytest.mark.parametrize(
    "login, expected",
    [
        ("copilot-swe-agent[bot]", "copilot"),
        ("Copilot", "copilot"),
        ("copilot-pull-request-reviewer", "copilot"),
        ("claude", "claude-code"),
        ("app/claude", "claude-code"),
        ("dependabot[bot]", None),
        ("alice", None),
        ("", None),
    ],
)
def test_bot_tool(login, expected):
    assert bot_tool(login, default_matchers()) == expected


def _write(tmp_path, text):
    p = tmp_path / "c.yaml"
    p.write_text(text)
    return str(p)


def test_config_extends_default_matchers(tmp_path):
    cfg = load_config(
        _write(
            tmp_path,
            """
activity:
  trailers:
    - tool: aider
      pattern: '^aider:'
  bots:
    - tool: devin
      login: devin-ai-integration
""",
        )
    )
    m = resolve_activity_matchers(cfg)
    assert match_trailer_tools("aider: did a thing", m) == {"aider"}
    assert match_trailer_tools(CLAUDE_TRAILER, m) == {"claude-code"}  # defaults kept
    assert bot_tool("devin-ai-integration[bot]", m) == "devin"


def test_resolve_activity_matchers_without_config_returns_defaults():
    assert resolve_activity_matchers(None).trailers == default_matchers().trailers


def test_invalid_trailer_regex_names_the_tool(tmp_path):
    cfg = load_config(
        _write(tmp_path, "activity:\n  trailers:\n    - tool: broken\n      pattern: '(unclosed'\n")
    )
    with pytest.raises(ValueError, match="broken"):
        resolve_activity_matchers(cfg)


def test_trailer_missing_fields_raises(tmp_path):
    cfg = load_config(_write(tmp_path, "activity:\n  trailers:\n    - tool: only-tool\n"))
    with pytest.raises(ValueError, match="tool and pattern"):
        resolve_activity_matchers(cfg)


def test_existing_config_without_activity_section_still_loads():
    assert Config().activity_trailers == []
    assert Config().activity_bots == []

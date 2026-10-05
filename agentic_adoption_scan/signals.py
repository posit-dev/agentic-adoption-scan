"""Matchers that attribute commits, PRs and reviews to AI tools.

Trailer patterns are regexes applied case-insensitively and per line to a
commit message. Bot logins are compared after lowercasing and stripping an
``app/`` prefix and a ``[bot]`` suffix.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# (tool, regex). Anchored patterns match whole trailer lines so prose that
# merely mentions a tool does not count.
DEFAULT_TRAILER_PATTERNS: list[tuple[str, str]] = [
    ("claude-code", r"^\s*co-authored-by:\s*claude\b"),
    ("claude-code", r"generated with \[?claude code"),
    ("claude-code", r"^\s*https?://claude\.ai/code/session_"),
    ("copilot", r"^\s*co-authored-by:\s*copilot\b"),
    ("cursor", r"^\s*co-authored-by:\s*cursor\b"),
]

# (tool, login)
DEFAULT_BOT_LOGINS: list[tuple[str, str]] = [
    ("copilot", "copilot"),
    ("copilot", "copilot-swe-agent"),
    ("copilot", "copilot-pull-request-reviewer"),
    ("claude-code", "claude"),
    ("cursor", "cursor"),
]


@dataclass(frozen=True)
class TrailerPattern:
    tool: str
    regex: re.Pattern[str]


@dataclass(frozen=True)
class BotLogin:
    tool: str
    login: str


@dataclass
class ActivityMatchers:
    trailers: list[TrailerPattern] = field(default_factory=list)
    bots: list[BotLogin] = field(default_factory=list)


def compile_trailer(tool: str, pattern: str) -> TrailerPattern:
    try:
        return TrailerPattern(tool, re.compile(pattern, re.IGNORECASE | re.MULTILINE))
    except re.error as exc:
        raise ValueError(f"invalid trailer pattern for tool {tool!r}: {exc}") from exc


def normalize_login(login: str) -> str:
    value = login.strip().lower()
    if value.startswith("app/"):
        value = value[len("app/"):]
    if value.endswith("[bot]"):
        value = value[: -len("[bot]")]
    return value


def make_bot(tool: str, login: str) -> BotLogin:
    return BotLogin(tool, normalize_login(login))


def default_matchers() -> ActivityMatchers:
    return ActivityMatchers(
        trailers=[compile_trailer(t, p) for t, p in DEFAULT_TRAILER_PATTERNS],
        bots=[make_bot(t, login) for t, login in DEFAULT_BOT_LOGINS],
    )


def match_trailer_tools(message: str, matchers: ActivityMatchers) -> set[str]:
    """Return the tools whose trailer appears in *message* (each tool once)."""
    return {p.tool for p in matchers.trailers if p.regex.search(message)}


def bot_tool(login: str, matchers: ActivityMatchers) -> str | None:
    """Return the tool a bot login belongs to, or None."""
    normalized = normalize_login(login)
    if not normalized:
        return None
    for bot in matchers.bots:
        if bot.login == normalized:
            return bot.tool
    return None

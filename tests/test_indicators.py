from __future__ import annotations

from agentic_adoption_scan.indicators import SearchType, default_indicators


def test_default_indicators_not_empty():
    indicators = default_indicators()
    assert len(indicators) > 0


def test_default_indicators_have_required_fields():
    for ind in default_indicators():
        assert ind.category != "", f"indicator {ind.name!r} has empty category"
        assert ind.name != "", f"indicator in category {ind.category!r} has empty name"
        assert ind.target != "", f"indicator {ind.category}/{ind.name} has empty target"
        assert ind.description != "", f"indicator {ind.category}/{ind.name} has empty description"


def test_default_indicators_categories():
    categories = {ind.category for ind in default_indicators()}

    expected = [
        "claude-code",
        "github-copilot",
        "cursor",
        "agents-config",
        "mcp",
        "evals",
        "workflows-ai",
    ]

    for cat in expected:
        assert cat in categories, f"missing expected category: {cat}"

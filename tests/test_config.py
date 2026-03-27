from __future__ import annotations

import os
import tempfile

import pytest

from agentic_adoption_scan.config import (
    Config,
    IndicatorConfig,
    generate_default_config,
    load_config,
    parse_search_type,
    resolve_indicators,
)
from agentic_adoption_scan.indicators import SearchType, default_indicators


def write_temp_config(content: str) -> str:
    """Write content to a temporary YAML file and return the path."""
    fd, path = tempfile.mkstemp(suffix=".yaml")
    with os.fdopen(fd, "w") as f:
        f.write(content)
    return path


def test_load_config_extend_mode():
    path = write_temp_config("""
mode: extend
indicators:
  - category: custom
    name: my-tool
    search_type: file_exists
    target: .my-tool.json
    description: Custom tool config
""")
    try:
        cfg = load_config(path)
        assert cfg.mode == "extend"
        assert len(cfg.indicators) == 1
    finally:
        os.unlink(path)


def test_load_config_defaults_to_extend():
    path = write_temp_config("""
indicators:
  - category: custom
    name: test
    search_type: file_exists
    target: test.txt
    description: Test
""")
    try:
        cfg = load_config(path)
        assert cfg.mode == "extend"
    finally:
        os.unlink(path)


def test_load_config_invalid_mode():
    path = write_temp_config("mode: invalid")
    try:
        with pytest.raises(ValueError):
            load_config(path)
    finally:
        os.unlink(path)


def test_resolve_indicators_nil_config():
    indicators = resolve_indicators(None)
    assert len(indicators) == len(default_indicators())


def test_resolve_indicators_extend_adds():
    cfg = Config(
        mode="extend",
        indicators=[
            IndicatorConfig(
                category="custom",
                name="new-thing",
                search_type="file_exists",
                target="new.json",
                description="New",
            )
        ],
    )

    indicators = resolve_indicators(cfg)
    assert len(indicators) == len(default_indicators()) + 1

    names = [ind.name for ind in indicators]
    assert "new-thing" in names


def test_resolve_indicators_extend_overrides_by_name():
    cfg = Config(
        mode="extend",
        indicators=[
            IndicatorConfig(
                category="claude-code",
                name="CLAUDE.md",
                search_type="file_exists",
                target="CLAUDE.md",
                description="Overridden description",
            )
        ],
    )

    indicators = resolve_indicators(cfg)
    # Should not add a duplicate — count should match defaults
    assert len(indicators) == len(default_indicators())

    for ind in indicators:
        if ind.category == "claude-code" and ind.name == "CLAUDE.md":
            assert ind.description == "Overridden description"
            break


def test_resolve_indicators_disable():
    cfg = Config(
        mode="extend",
        disable=["CLAUDE.md", ".cursorrules"],
    )

    indicators = resolve_indicators(cfg)

    for ind in indicators:
        assert ind.name not in ("CLAUDE.md", ".cursorrules"), (
            f"disabled indicator {ind.name!r} should not be present"
        )

    assert len(indicators) == len(default_indicators()) - 2


def test_resolve_indicators_override_mode():
    cfg = Config(
        mode="override",
        indicators=[
            IndicatorConfig(
                category="custom",
                name="only-this",
                search_type="file_exists",
                target="only.txt",
                description="Only indicator",
            )
        ],
    )

    indicators = resolve_indicators(cfg)
    assert len(indicators) == 1
    assert indicators[0].name == "only-this"


def test_resolve_indicators_override_empty():
    cfg = Config(mode="override")
    with pytest.raises(ValueError):
        resolve_indicators(cfg)


def test_parse_search_types():
    cases = [
        ("file_exists", SearchType.FILE_EXISTS),
        ("file-exists", SearchType.FILE_EXISTS),
        ("directory_exists", SearchType.DIRECTORY_EXISTS),
        ("content_search", SearchType.CONTENT_SEARCH),
        ("content-search", SearchType.CONTENT_SEARCH),
        ("workflow_search", SearchType.WORKFLOW_SEARCH),
        ("workflow-search", SearchType.WORKFLOW_SEARCH),
    ]

    for input_str, expected in cases:
        result = parse_search_type(input_str)
        assert result == expected, f"parse_search_type({input_str!r}) = {result}, want {expected}"


def test_generate_default_config():
    yaml_str = generate_default_config()
    assert len(yaml_str) > 0

    # Should be valid YAML that can be loaded back
    path = write_temp_config(yaml_str)
    try:
        cfg = load_config(path)
        assert len(cfg.indicators) == len(default_indicators())
    finally:
        os.unlink(path)

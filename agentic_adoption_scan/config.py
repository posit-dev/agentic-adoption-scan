from __future__ import annotations

from dataclasses import dataclass, field

import yaml

from .indicators import Indicator, SearchType, default_indicators, search_type_name


@dataclass
class IndicatorConfig:
    """YAML representation of an Indicator."""
    category: str = ""
    name: str = ""
    search_type: str = ""
    target: str = ""
    description: str = ""


@dataclass
class Config:
    """Represents the YAML configuration file.

    mode: "extend" (default) adds config indicators to the defaults.
          "override" replaces defaults entirely.
    disable: list of built-in indicator names to exclude (extend mode only).
    indicators: custom indicators to add or override.
    """
    mode: str = "extend"
    disable: list[str] = field(default_factory=list)
    indicators: list[IndicatorConfig] = field(default_factory=list)


def load_config(path: str) -> Config:
    """Read and parse a YAML config file."""
    with open(path, "r") as f:
        data = yaml.safe_load(f) or {}

    mode = data.get("mode", "extend")
    if not mode:
        mode = "extend"

    if mode not in ("extend", "override"):
        raise ValueError(f'invalid mode {mode!r}: must be "extend" or "override"')

    disable = data.get("disable") or []
    raw_indicators = data.get("indicators") or []

    indicators = []
    for item in raw_indicators:
        indicators.append(IndicatorConfig(
            category=item.get("category", ""),
            name=item.get("name", ""),
            search_type=item.get("search_type", ""),
            target=item.get("target", ""),
            description=item.get("description", ""),
        ))

    return Config(mode=mode, disable=disable, indicators=indicators)


def parse_search_type(s: str) -> SearchType:
    """Parse a search type string, accepting multiple formats."""
    normalized = s.lower()
    if normalized in ("file_exists", "file-exists", "fileexists"):
        return SearchType.FILE_EXISTS
    if normalized in ("directory_exists", "directory-exists", "directoryexists"):
        return SearchType.DIRECTORY_EXISTS
    if normalized in ("content_search", "content-search", "contentsearch"):
        return SearchType.CONTENT_SEARCH
    if normalized in ("workflow_search", "workflow-search", "workflowsearch"):
        return SearchType.WORKFLOW_SEARCH
    raise ValueError(
        f'unknown search_type {s!r} '
        f'(valid: file_exists, directory_exists, content_search, workflow_search)'
    )


def _convert_indicators(configs: list[IndicatorConfig]) -> list[Indicator]:
    """Convert IndicatorConfig list to Indicator list, validating fields."""
    indicators = []
    for c in configs:
        st = parse_search_type(c.search_type)
        if not c.category or not c.name or not c.target:
            raise ValueError(
                f'indicator {c.name!r}: category, name, and target are required'
            )
        indicators.append(Indicator(
            category=c.category,
            name=c.name,
            search_type=st,
            target=c.target,
            description=c.description,
        ))
    return indicators


def resolve_indicators(config: Config | None = None) -> list[Indicator]:
    """Merge config indicators with defaults based on mode.

    If config is None, returns default_indicators() unchanged.
    """
    if config is None:
        return default_indicators()

    config_indicators = _convert_indicators(config.indicators)

    if config.mode == "override":
        if not config_indicators:
            raise ValueError('mode is "override" but no indicators defined in config')
        return config_indicators

    if config.mode == "extend":
        defaults = default_indicators()

        # Remove disabled indicators
        if config.disable:
            disable_set = {name.lower() for name in config.disable}
            defaults = [ind for ind in defaults if ind.name.lower() not in disable_set]

        # Append config indicators, replacing any with same category+name
        by_key: dict[str, int] = {}
        for i, ind in enumerate(defaults):
            by_key[ind.category + "/" + ind.name] = i

        for ind in config_indicators:
            key = ind.category + "/" + ind.name
            if key in by_key:
                defaults[by_key[key]] = ind  # replace existing
            else:
                defaults.append(ind)

        return defaults

    raise ValueError(f"unknown mode: {config.mode}")


def generate_default_config() -> str:
    """Produce a YAML config string showing all built-in indicators."""
    defaults = default_indicators()

    configs = []
    for ind in defaults:
        configs.append({
            "category": ind.category,
            "name": ind.name,
            "search_type": search_type_name(ind.search_type),
            "target": ind.target,
            "description": ind.description,
        })

    cfg_dict = {
        "mode": "extend",
        "disable": [],
        "indicators": configs,
    }

    header = """\
# Agentic Adoption Scan - Indicator Configuration
#
# mode: "extend" (default) adds these indicators to built-in defaults.
#        Use "override" to replace all built-in indicators entirely.
#
# disable: list of built-in indicator names to exclude (only in extend mode).
#
# indicators: custom indicators to add or override.
#   search_type values: file_exists, directory_exists, content_search, workflow_search
#
# The indicators below are the built-in defaults, shown for reference.
# Remove or modify as needed.

"""
    return header + yaml.dump(cfg_dict, default_flow_style=False, allow_unicode=True)

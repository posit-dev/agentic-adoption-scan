"""Resolve the GitHub orgs to scan from CLI flags."""
from __future__ import annotations

from typing import Sequence


def parse_org_list(raw: str) -> list[str]:
    """Split a comma-separated string of org slugs, dropping blanks."""
    return [o.strip() for o in raw.split(",") if o.strip()]


def load_orgs_file(path: str) -> list[str]:
    """Read one org per line; blank lines and ``#`` comments are ignored."""
    orgs: list[str] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.split("#", 1)[0].strip()
            if line:
                orgs.append(line)
    return orgs


def resolve_orgs(cli_orgs: Sequence[str], orgs_file: str = "") -> list[str]:
    """Combine ``--org`` values and ``--orgs-file`` entries.

    Orgs are deduplicated case-insensitively (GitHub slugs are
    case-insensitive), keeping the first spelling and the given order.
    Raises ValueError if no org was given.
    """
    candidates: list[str] = []
    for value in cli_orgs:
        candidates.extend(parse_org_list(value))
    if orgs_file:
        candidates.extend(load_orgs_file(orgs_file))

    seen: set[str] = set()
    orgs: list[str] = []
    for org in candidates:
        if org.lower() in seen:
            continue
        seen.add(org.lower())
        orgs.append(org)

    if not orgs:
        raise ValueError("no orgs given: pass --org (repeatable) or --orgs-file")
    return orgs

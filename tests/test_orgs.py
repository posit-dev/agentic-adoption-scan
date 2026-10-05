from __future__ import annotations

import pytest

from agentic_adoption_scan.orgs import load_orgs_file, parse_org_list, resolve_orgs


def test_parse_org_list_splits_commas_and_drops_blanks():
    assert parse_org_list("posit-dev, rstudio,,  ") == ["posit-dev", "rstudio"]


def test_load_orgs_file_ignores_comments_and_blank_lines(tmp_path):
    f = tmp_path / "orgs.txt"
    f.write_text("# company orgs\nposit-dev\n\nrstudio  # legacy\n")
    assert load_orgs_file(str(f)) == ["posit-dev", "rstudio"]


def test_resolve_orgs_combines_flags_and_file_and_dedupes_case_insensitively(tmp_path):
    f = tmp_path / "orgs.txt"
    f.write_text("RStudio\ntidyverse\n")
    assert resolve_orgs(("posit-dev", "rstudio"), str(f)) == [
        "posit-dev",
        "rstudio",
        "tidyverse",
    ]


def test_resolve_orgs_empty_raises():
    with pytest.raises(ValueError, match="--org"):
        resolve_orgs((), "")

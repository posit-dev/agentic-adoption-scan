from __future__ import annotations

import io
import os

import pyarrow as pa

from agentic_adoption_scan.models import ActivityResult
from agentic_adoption_scan.output import write_activity_csv
from agentic_adoption_scan.parquet_io import (
    ACTIVITY_SCHEMA,
    read_activity_rows,
    read_activity_state,
    write_activity_parquet,
    write_activity_rows,
    write_activity_state,
)
from agentic_adoption_scan.storage import LocalStore


def _row(**kw) -> ActivityResult:
    base = dict(
        scan_timestamp="2026-10-05T12:00:00Z",
        org="orga",
        repo="r1",
        repo_visibility="public",
        week_start="2026-09-28",
        tool="claude-code",
        signal="commit_trailer",
        count=3,
        total_commits=10,
    )
    base.update(kw)
    return ActivityResult(**base)


def test_activity_schema_columns_and_types_are_pinned():
    assert ACTIVITY_SCHEMA.names == [
        "scan_timestamp",
        "org",
        "repo",
        "repo_visibility",
        "week_start",
        "tool",
        "signal",
        "count",
        "total_commits",
    ]
    assert [f.type for f in ACTIVITY_SCHEMA] == [
        pa.string(),
        pa.string(),
        pa.string(),
        pa.string(),
        pa.string(),
        pa.string(),
        pa.string(),
        pa.int64(),
        pa.int64(),
    ]


def test_activity_rows_round_trip(tmp_path):
    store = LocalStore()
    path = str(tmp_path / "activity-cache.parquet")
    rows = [_row(), _row(tool="", signal="none", count=0, week_start="2026-10-05")]
    write_activity_rows(store, path, rows)
    assert read_activity_rows(store, path) == rows


def test_activity_state_round_trip(tmp_path):
    store = LocalStore()
    path = str(tmp_path / "activity-state.parquet")
    state = {("orga", "r1"): "2026-10-05T12:00:00Z", ("orgb", "r1"): "2026-10-06T00:00:00Z"}
    write_activity_state(store, path, state)
    assert read_activity_state(store, path) == state


def test_write_activity_parquet_is_partitioned_by_org_and_scan_date(tmp_path):
    store = LocalStore()
    write_activity_parquet(store, str(tmp_path), [_row(), _row(org="orgb")])
    assert os.path.exists(tmp_path / "org=orga" / "date=2026-10-05" / "part-0.parquet")
    assert os.path.exists(tmp_path / "org=orgb" / "date=2026-10-05" / "part-0.parquet")


def test_write_activity_csv_header_and_values():
    buf = io.StringIO()
    write_activity_csv(buf, [_row()])
    lines = buf.getvalue().splitlines()
    assert lines[0] == (
        "scan_timestamp,org,repo,repo_visibility,week_start,tool,signal,count,total_commits"
    )
    assert lines[1] == "2026-10-05T12:00:00Z,orga,r1,public,2026-09-28,claude-code,commit_trailer,3,10"

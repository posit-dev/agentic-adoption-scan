"""Parquet read/write helpers for ScanRow and InspectRow.

Hive partition layout:
    <base_path>/org=<org>/date=<YYYY-MM-DD>/part-0.parquet
"""
from __future__ import annotations

import io
from dataclasses import dataclass
from datetime import timezone
from typing import TYPE_CHECKING

import pyarrow as pa
import pyarrow.parquet as pq

from agentic_adoption_scan.models import InspectResult, ScanResult
from agentic_adoption_scan.storage import ObjectStore

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# Row dataclasses (flat Parquet schema)
# ---------------------------------------------------------------------------


@dataclass
class ScanRow:
    scan_timestamp: str
    org: str
    repo: str
    repo_visibility: str
    repo_language: str
    repo_pushed_at: str
    category: str
    indicator: str
    found: bool
    file_path: str
    details: str


@dataclass
class InspectRow:
    scan_timestamp: str
    org: str
    repo: str
    category: str
    indicator: str
    file_path: str
    content_size: int
    content_summary: str
    raw_content: str


# ---------------------------------------------------------------------------
# pyarrow schemas
# ---------------------------------------------------------------------------

SCAN_SCHEMA = pa.schema([
    ("scan_timestamp", pa.string()),
    ("org", pa.string()),
    ("repo", pa.string()),
    ("repo_visibility", pa.string()),
    ("repo_language", pa.string()),
    ("repo_pushed_at", pa.string()),
    ("category", pa.string()),
    ("indicator", pa.string()),
    ("found", pa.bool_()),
    ("file_path", pa.string()),
    ("details", pa.string()),
])

INSPECT_SCHEMA = pa.schema([
    ("scan_timestamp", pa.string()),
    ("org", pa.string()),
    ("repo", pa.string()),
    ("category", pa.string()),
    ("indicator", pa.string()),
    ("file_path", pa.string()),
    ("content_size", pa.int64()),
    ("content_summary", pa.string()),
    ("raw_content", pa.string()),
])


# ---------------------------------------------------------------------------
# Conversion helpers
# ---------------------------------------------------------------------------


def scan_result_to_row(r: ScanResult) -> ScanRow:
    return ScanRow(
        scan_timestamp=r.scan_timestamp,
        org=r.org,
        repo=r.repo,
        repo_visibility=r.repo_visibility,
        repo_language=r.repo_language,
        repo_pushed_at=r.repo_pushed_at,
        category=r.category,
        indicator=r.indicator,
        found=r.found,
        file_path=r.file_path,
        details=r.details,
    )


def scan_row_to_result(r: ScanRow) -> ScanResult:
    return ScanResult(
        scan_timestamp=r.scan_timestamp,
        org=r.org,
        repo=r.repo,
        repo_visibility=r.repo_visibility,
        repo_language=r.repo_language,
        repo_pushed_at=r.repo_pushed_at,
        category=r.category,
        indicator=r.indicator,
        found=r.found,
        file_path=r.file_path,
        details=r.details,
    )


def inspect_result_to_row(r: InspectResult) -> InspectRow:
    return InspectRow(
        scan_timestamp=r.scan_timestamp,
        org=r.org,
        repo=r.repo,
        category=r.category,
        indicator=r.indicator,
        file_path=r.file_path,
        content_size=r.content_size,
        content_summary=r.content_summary,
        raw_content=r.raw_content,
    )


# ---------------------------------------------------------------------------
# Low-level serialisation
# ---------------------------------------------------------------------------


def _rows_to_table(rows: list[ScanRow], schema: pa.Schema) -> pa.Table:
    if not rows:
        return pa.table({f.name: pa.array([], type=f.type) for f in schema}, schema=schema)
    col: dict[str, list] = {f.name: [] for f in schema}
    for r in rows:
        for f in schema:
            col[f.name].append(getattr(r, f.name))
    return pa.table(col, schema=schema)


def _inspect_rows_to_table(rows: list[InspectRow]) -> pa.Table:
    schema = INSPECT_SCHEMA
    if not rows:
        return pa.table({f.name: pa.array([], type=f.type) for f in schema}, schema=schema)
    col: dict[str, list] = {f.name: [] for f in schema}
    for r in rows:
        for f in schema:
            col[f.name].append(getattr(r, f.name))
    return pa.table(col, schema=schema)


def _serialize_table(table: pa.Table) -> bytes:
    buf = io.BytesIO()
    pq.write_table(table, buf)
    return buf.getvalue()


def _deserialize_scan_rows(data: bytes) -> list[ScanRow]:
    table = pq.read_table(io.BytesIO(data))
    rows: list[ScanRow] = []
    d = table.to_pydict()
    n = len(d["scan_timestamp"])
    for i in range(n):
        rows.append(ScanRow(
            scan_timestamp=d["scan_timestamp"][i] or "",
            org=d["org"][i] or "",
            repo=d["repo"][i] or "",
            repo_visibility=d["repo_visibility"][i] or "",
            repo_language=d["repo_language"][i] or "",
            repo_pushed_at=d["repo_pushed_at"][i] or "",
            category=d["category"][i] or "",
            indicator=d["indicator"][i] or "",
            found=bool(d["found"][i]),
            file_path=d["file_path"][i] or "",
            details=d["details"][i] or "",
        ))
    return rows


def _deserialize_inspect_rows(data: bytes) -> list[InspectRow]:
    table = pq.read_table(io.BytesIO(data))
    rows: list[InspectRow] = []
    d = table.to_pydict()
    n = len(d["scan_timestamp"])
    for i in range(n):
        rows.append(InspectRow(
            scan_timestamp=d["scan_timestamp"][i] or "",
            org=d["org"][i] or "",
            repo=d["repo"][i] or "",
            category=d["category"][i] or "",
            indicator=d["indicator"][i] or "",
            file_path=d["file_path"][i] or "",
            content_size=int(d["content_size"][i]) if d["content_size"][i] is not None else 0,
            content_summary=d["content_summary"][i] or "",
            raw_content=d["raw_content"][i] or "",
        ))
    return rows


# ---------------------------------------------------------------------------
# Partition key helper
# ---------------------------------------------------------------------------


def _scan_partition_key(org: str, scan_timestamp: str) -> tuple[str, str]:
    from datetime import datetime
    try:
        t = datetime.fromisoformat(scan_timestamp.replace("Z", "+00:00"))
        date_str = t.astimezone(timezone.utc).strftime("%Y-%m-%d")
    except (ValueError, AttributeError):
        date_str = "unknown"
    return org, date_str


# ---------------------------------------------------------------------------
# Public API: partitioned write
# ---------------------------------------------------------------------------


def write_scan_parquet(store: ObjectStore, base_path: str, results: list[ScanResult]) -> None:
    """Write scan results as Hive-partitioned Parquet files."""
    import posixpath

    groups: dict[tuple[str, str], list[ScanRow]] = {}
    for r in results:
        org, date = _scan_partition_key(r.org, r.scan_timestamp)
        key = (org, date)
        groups.setdefault(key, []).append(scan_result_to_row(r))

    for (org, date), rows in groups.items():
        part_path = posixpath.join(
            base_path, f"org={org}", f"date={date}", "part-0.parquet"
        )
        table = _rows_to_table(rows, SCAN_SCHEMA)
        store.write(part_path, _serialize_table(table))


def write_inspect_parquet(store: ObjectStore, base_path: str, results: list[InspectResult]) -> None:
    """Write inspect results as Hive-partitioned Parquet files."""
    import posixpath

    groups: dict[tuple[str, str], list[InspectRow]] = {}
    for r in results:
        org, date = _scan_partition_key(r.org, r.scan_timestamp)
        key = (org, date)
        groups.setdefault(key, []).append(inspect_result_to_row(r))

    for (org, date), rows in groups.items():
        part_path = posixpath.join(
            base_path, f"org={org}", f"date={date}", "part-0.parquet"
        )
        table = _inspect_rows_to_table(rows)
        store.write(part_path, _serialize_table(table))


# ---------------------------------------------------------------------------
# Public API: read
# ---------------------------------------------------------------------------


def write_scan_rows(store: ObjectStore, file_path: str, rows: list[ScanRow]) -> None:
    """Serialize and write a flat list of ScanRows."""
    table = _rows_to_table(rows, SCAN_SCHEMA)
    store.write(file_path, _serialize_table(table))


def read_scan_rows(store: ObjectStore, path: str) -> list[ScanRow]:
    """Read ScanRows from a single Parquet file."""
    data = store.read(path)
    return _deserialize_scan_rows(data)


def read_inspect_rows(store: ObjectStore, path: str) -> list[InspectRow]:
    """Read InspectRows from a single Parquet file."""
    data = store.read(path)
    return _deserialize_inspect_rows(data)

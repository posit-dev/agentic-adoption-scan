# Parquet Caching Design

## Overview

Replace the current CSV output and JSON scan cache with Parquet files for improved storage efficiency, query performance, and DuckDB compatibility. Support writing to local filesystem or S3 using a unified `s3://` path syntax.

## Goals

- Store scan results and inspect results in Parquet format instead of CSV
- Replace the JSON scan cache (`scan-cache.json`) with a Parquet-based cache
- Support writing to local disk or S3 via `s3://bucket/prefix` paths
- Make output files trivially queryable from DuckDB without custom tooling
- Maintain backward-compatible CLI flags (existing `--output` and `--cache-dir` flags accept new path forms)

---

## Storage Layout

### Output Files

The `--output` flag accepts either a local path or an `s3://` URI:

```
# Local
--output ./results/scan.parquet

# S3
--output s3://my-bucket/metrics/scan.parquet
```

### Cache Files

The `--cache-dir` flag accepts either a local directory or an `s3://` prefix:

```
# Local (existing behavior, new format)
--cache-dir .agentic-scan-cache/

# S3
--cache-dir s3://my-bucket/agentic-cache/
```

Under the cache directory, two Parquet files are maintained:

```
<cache-dir>/
├── scan-cache.parquet      # Replaces scan-cache.json
└── inspect-cache.parquet   # New: caches inspect results
```

---

## Parquet Schema

### Scan Results / Scan Cache

Both the output file and the cache share a common schema. The cache is simply the
full history of scans; freshness checks use `pushed_at` the same as today.

| Column | Type | Description |
|---|---|---|
| `scan_timestamp` | `TIMESTAMP` | When the scan ran (UTC) |
| `org` | `VARCHAR` | GitHub organization |
| `repo` | `VARCHAR` | Repository name |
| `repo_visibility` | `VARCHAR` | `public`, `private`, or `internal` |
| `repo_language` | `VARCHAR` | Primary language reported by GitHub |
| `repo_pushed_at` | `TIMESTAMP` | Last push time (used for cache invalidation) |
| `category` | `VARCHAR` | Indicator category (e.g. `claude-code`) |
| `indicator` | `VARCHAR` | Indicator name (e.g. `CLAUDE.md`) |
| `found` | `BOOLEAN` | Whether the indicator was detected |
| `file_path` | `VARCHAR` | Path where found, empty string if not found |
| `details` | `VARCHAR` | Additional context (e.g. match count) |

**Partitioning**: Partition by `org` and `date(scan_timestamp)` using Hive-style
directory layout for efficient time-range and org queries:

```
scan.parquet/
└── org=posit-dev/
    └── date=2026-03-23/
        └── part-0.parquet
```

### Inspect Results / Inspect Cache

| Column | Type | Description |
|---|---|---|
| `scan_timestamp` | `TIMESTAMP` | When the inspect ran (UTC) |
| `org` | `VARCHAR` | GitHub organization |
| `repo` | `VARCHAR` | Repository name |
| `repo_visibility` | `VARCHAR` | Visibility |
| `repo_language` | `VARCHAR` | Primary language |
| `repo_pushed_at` | `TIMESTAMP` | Last push time |
| `category` | `VARCHAR` | Indicator category |
| `indicator` | `VARCHAR` | Indicator name |
| `file_path` | `VARCHAR` | File path inspected |
| `content_size` | `INT64` | File size in bytes |
| `content_summary` | `VARCHAR` | Extracted key details |
| `raw_content` | `VARCHAR` | Full file content |

**Partitioning**: Same Hive layout (`org=`, `date=`).

---

## Cache Invalidation

The scan cache Parquet file replaces `scan-cache.json`. Invalidation logic is unchanged:

1. For each repo, find the most recent row in `scan-cache.parquet` where `org/repo` matches.
2. Compare the stored `repo_pushed_at` to the value returned by the GitHub API.
3. If equal → cache hit, reuse all indicator rows for that repo from the cache.
4. If different (or no row exists) → cache miss, re-scan and append new rows.

The `--force` flag continues to bypass the cache entirely.

**Compaction**: Rows accumulate over time. A `compact` subcommand (see below) merges
historical partitions and deduplicates, keeping only the latest scan per `org/repo`.

---

## New CLI Flags and Commands

### Modified flags (backward-compatible)

```
--output <path>     Output file. Accepts local path or s3:// URI.
                    .parquet extension triggers Parquet output;
                    .csv extension preserves existing CSV behavior.
                    (default: stdout → CSV for compatibility)

--cache-dir <path>  Cache directory. Accepts local path or s3:// URI.
                    Automatically uses Parquet when path ends in /
                    and contains .parquet files.
```

### New `compact` subcommand

Merges partitioned cache files and deduplicates to the latest scan per repo:

```
agentic-adoption-scan compact --cache-dir s3://my-bucket/cache/
agentic-adoption-scan compact --cache-dir .agentic-scan-cache/
```

Options:
- `--dry-run`: Print what would be compacted without writing
- `--keep-history`: Keep all historical rows (default: deduplicate to latest per org/repo)

---

## S3 Integration

### Authentication

Use the AWS SDK default credential chain (environment variables, `~/.aws/credentials`,
EC2 instance role, ECS task role). No new flags needed; standard AWS env vars apply:

```
AWS_PROFILE=my-profile agentic-adoption-scan scan --org posit-dev \
  --output s3://my-bucket/results/scan.parquet \
  --cache-dir s3://my-bucket/cache/
```

### S3 Path Resolution

A `storage` package provides a unified `ObjectStore` interface:

```go
type ObjectStore interface {
    // Read returns a reader for the object at path.
    Read(ctx context.Context, path string) (io.ReadCloser, error)

    // Write returns a writer that flushes to path on Close.
    Write(ctx context.Context, path string) (io.WriteCloser, error)

    // List returns object keys under prefix.
    List(ctx context.Context, prefix string) ([]string, error)

    // Delete removes an object.
    Delete(ctx context.Context, path string) error
}
```

Two implementations:

| Implementation | Trigger |
|---|---|
| `LocalStore` | Path does not start with `s3://` |
| `S3Store` | Path starts with `s3://` |

`ParsePath(raw string) (store ObjectStore, key string)` inspects the prefix and
returns the right implementation plus the bucket-relative key.

### S3 Write Strategy

Parquet files are written locally to a temp file first, then uploaded atomically
via `PutObject`. This avoids partial writes and works with S3's object model.
For partitioned outputs a single `PutObject` call is made per partition file.

---

## Go Dependencies

Add to `go.mod`:

```
github.com/parquet-go/parquet-go        # Parquet read/write
github.com/aws/aws-sdk-go-v2/config     # AWS credential chain
github.com/aws/aws-sdk-go-v2/service/s3 # S3 client
```

`parquet-go` is a pure-Go implementation; no CGO required, preserving the current
single-binary release model.

---

## New Source Files

```
agentic-adoption-scan/
├── storage.go        # ObjectStore interface + LocalStore + S3Store
├── parquet.go        # Parquet schema definitions, read/write helpers
├── compact.go        # compact subcommand implementation
```

### Changes to Existing Files

| File | Change |
|---|---|
| `cache.go` | Replace JSON read/write with Parquet via `parquet.go`; preserve `IsRepoFresh` / `GetRepoResults` / `SetRepoResults` API |
| `output.go` | Add `WriteScanParquet` / `WriteInspectParquet` alongside existing CSV writers |
| `main.go` | Register `compact` subcommand; detect `.parquet` extension in `--output` |
| `go.mod` | Add three new dependencies |

---

## DuckDB Usage

Because the output uses standard Hive-partitioned Parquet, DuckDB can query it
directly with no additional setup.

### Local files

```sql
-- Single file
SELECT org, repo, indicator, found
FROM read_parquet('results/scan.parquet');

-- Partitioned directory (all orgs, all dates)
SELECT *
FROM read_parquet('scan.parquet/**/*.parquet', hive_partitioning = true);

-- Filter pushed down to partition pruning
SELECT org, repo, COUNT(*) AS indicators_found
FROM read_parquet('scan.parquet/**/*.parquet', hive_partitioning = true)
WHERE org = 'posit-dev'
  AND found = true
GROUP BY org, repo
ORDER BY indicators_found DESC;
```

### S3 files

```sql
-- Install and load httpfs for S3 access
INSTALL httpfs;
LOAD httpfs;

SET s3_region = 'us-east-1';
-- Credentials picked up from environment or ~/.aws/credentials automatically

-- Query partitioned data on S3
SELECT *
FROM read_parquet('s3://my-bucket/metrics/scan.parquet/**/*.parquet',
                  hive_partitioning = true)
WHERE date >= '2026-01-01'
  AND org = 'posit-dev';

-- Time series: adoption trend by week
SELECT
    date_trunc('week', scan_timestamp) AS week,
    indicator,
    COUNT(DISTINCT repo) AS repos_with_indicator
FROM read_parquet('s3://my-bucket/metrics/scan.parquet/**/*.parquet',
                  hive_partitioning = true)
WHERE found = true
GROUP BY week, indicator
ORDER BY week, indicator;
```

### Persistent DuckDB views (optional)

Users can register the Parquet files as persistent views in a local DuckDB database
for repeated use:

```sql
CREATE OR REPLACE VIEW scan_results AS
  SELECT * FROM read_parquet(
    's3://my-bucket/metrics/scan.parquet/**/*.parquet',
    hive_partitioning = true
  );

-- Then query like a regular table
SELECT * FROM scan_results WHERE org = 'posit-dev' AND found = true;
```

---

## Migration

Existing users can convert their CSV outputs to Parquet using DuckDB directly:

```sql
COPY (SELECT * FROM read_csv_auto('results.csv'))
TO 'results.parquet' (FORMAT parquet);
```

The JSON cache (`scan-cache.json`) is auto-detected and transparently migrated to
`scan-cache.parquet` on the first run after upgrading. The old JSON file is left in
place and can be deleted manually once the Parquet cache is confirmed working.

---

## Open Questions

1. **Compression codec**: `SNAPPY` (fast, splittable) vs `ZSTD` (better ratio). Default to `SNAPPY`; expose `--parquet-compression` flag if needed.
2. **Row group size**: 128 MB default. Tune based on typical org scan sizes.
3. **Streaming vs buffered writes**: For very large orgs (10k+ repos), streaming row groups avoids holding all results in memory. `parquet-go` supports this via `RowWriter`.
4. **Inspect cache invalidation**: The inspect cache should be invalidated when `repo_pushed_at` changes (same signal as scan cache). Confirm this is sufficient or if content hash is needed.
5. **Backward compatibility period**: Keep CSV output as the default for one release cycle; switch default to Parquet in the next major version.

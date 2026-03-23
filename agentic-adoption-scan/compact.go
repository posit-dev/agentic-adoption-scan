package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"os"
	"path"
)

func runCompact(args []string) {
	fs := flag.NewFlagSet("compact", flag.ExitOnError)
	cacheDir := fs.String("cache-dir", ".agentic-scan-cache", "Cache directory (local path or s3:// URI)")
	dryRun := fs.Bool("dry-run", false, "Print what would be compacted without writing")
	keepHistory := fs.Bool("keep-history", false, "Keep all historical rows instead of deduplicating to latest per org/repo")

	fs.Parse(args)

	store, basePath, err := ParseStorePath(*cacheDir)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		os.Exit(1)
	}

	parquetPath := path.Join(basePath, "scan-cache.parquet")
	rows, err := ReadScanRows(store, parquetPath)
	if err != nil {
		if errors.Is(err, os.ErrNotExist) {
			fmt.Fprintln(os.Stderr, "No cache file found; nothing to compact.")
			return
		}
		fmt.Fprintf(os.Stderr, "Error reading cache: %v\n", err)
		os.Exit(1)
	}

	fmt.Fprintf(os.Stderr, "Read %d rows from %s\n", len(rows), parquetPath)

	var compacted []ScanRow
	if *keepHistory {
		compacted = rows
		fmt.Fprintf(os.Stderr, "Keeping all %d historical rows\n", len(compacted))
	} else {
		compacted = deduplicateScanRows(rows)
		fmt.Fprintf(os.Stderr, "Deduplicated to %d rows (latest scan per org/repo)\n", len(compacted))
	}

	if *dryRun {
		fmt.Fprintln(os.Stderr, "Dry run: not writing changes.")
		return
	}

	if err := writeScanRows(store, parquetPath, compacted); err != nil {
		fmt.Fprintf(os.Stderr, "Error writing compacted cache: %v\n", err)
		os.Exit(1)
	}
	fmt.Fprintln(os.Stderr, "Compaction complete.")
}

// deduplicateScanRows keeps only the rows from the most recent scan for each
// (org, repo) pair, removing stale historical entries.
func deduplicateScanRows(rows []ScanRow) []ScanRow {
	// Find the latest scan_timestamp per (org, repo).
	latest := make(map[string]string)
	for _, r := range rows {
		key := r.Org + "/" + r.Repo
		if r.ScanTimestamp > latest[key] {
			latest[key] = r.ScanTimestamp
		}
	}
	out := make([]ScanRow, 0, len(rows))
	for _, r := range rows {
		if r.ScanTimestamp == latest[r.Org+"/"+r.Repo] {
			out = append(out, r)
		}
	}
	return out
}

// readAllCacheScanRows reads all scan rows from a cache directory,
// combining rows from the flat cache file and any partitioned output files.
func readAllCacheScanRows(store ObjectStore, basePath string) ([]ScanRow, error) {
	files, err := store.List(context.Background(), basePath)
	if err != nil {
		return nil, fmt.Errorf("listing parquet files: %w", err)
	}

	var all []ScanRow
	for _, f := range files {
		rows, err := ReadScanRows(store, f)
		if err != nil {
			return nil, fmt.Errorf("reading %s: %w", f, err)
		}
		all = append(all, rows...)
	}
	return all, nil
}

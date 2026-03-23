package main

import (
	"bytes"
	"context"
	"fmt"
	"io"
	"path"
	"time"

	parquet "github.com/parquet-go/parquet-go"
)

// ---------------------------------------------------------------------------
// Row types – Parquet-serialisable structs
// ---------------------------------------------------------------------------

// ScanRow is the Parquet-serialisable form of a ScanResult.
// It is used for both partitioned output files and the flat cache file.
type ScanRow struct {
	ScanTimestamp  string `parquet:"scan_timestamp"`
	Org            string `parquet:"org"`
	Repo           string `parquet:"repo"`
	RepoVisibility string `parquet:"repo_visibility"`
	RepoLanguage   string `parquet:"repo_language"`
	RepoPushedAt   string `parquet:"repo_pushed_at"`
	Category       string `parquet:"category"`
	Indicator      string `parquet:"indicator"`
	Found          bool   `parquet:"found"`
	FilePath       string `parquet:"file_path"`
	Details        string `parquet:"details"`
}

// InspectRow is the Parquet-serialisable form of an InspectResult.
type InspectRow struct {
	ScanTimestamp  string `parquet:"scan_timestamp"`
	Org            string `parquet:"org"`
	Repo           string `parquet:"repo"`
	Category       string `parquet:"category"`
	Indicator      string `parquet:"indicator"`
	FilePath       string `parquet:"file_path"`
	ContentSize    int64  `parquet:"content_size"`
	ContentSummary string `parquet:"content_summary"`
	RawContent     string `parquet:"raw_content"`
}

// ---------------------------------------------------------------------------
// Conversion helpers
// ---------------------------------------------------------------------------

func scanResultToRow(r ScanResult) ScanRow {
	return ScanRow{
		ScanTimestamp:  r.ScanTimestamp,
		Org:            r.Org,
		Repo:           r.Repo,
		RepoVisibility: r.RepoVisibility,
		RepoLanguage:   r.RepoLanguage,
		RepoPushedAt:   r.RepoPushedAt,
		Category:       r.Category,
		Indicator:      r.Indicator,
		Found:          r.Found,
		FilePath:       r.FilePath,
		Details:        r.Details,
	}
}

func scanRowToResult(r ScanRow) ScanResult {
	return ScanResult{
		ScanTimestamp:  r.ScanTimestamp,
		Org:            r.Org,
		Repo:           r.Repo,
		RepoVisibility: r.RepoVisibility,
		RepoLanguage:   r.RepoLanguage,
		RepoPushedAt:   r.RepoPushedAt,
		Category:       r.Category,
		Indicator:      r.Indicator,
		Found:          r.Found,
		FilePath:       r.FilePath,
		Details:        r.Details,
	}
}

func inspectResultToRow(r InspectResult) InspectRow {
	return InspectRow{
		ScanTimestamp:  r.ScanTimestamp,
		Org:            r.Org,
		Repo:           r.Repo,
		Category:       r.Category,
		Indicator:      r.Indicator,
		FilePath:       r.FilePath,
		ContentSize:    int64(r.ContentSize),
		ContentSummary: r.ContentSummary,
		RawContent:     r.RawContent,
	}
}

// ---------------------------------------------------------------------------
// Partitioned write helpers (output files)
// ---------------------------------------------------------------------------

// WriteScanParquet writes scan results as Hive-partitioned Parquet under basePath.
//
// Partition layout:  basePath/org=<org>/date=<YYYY-MM-DD>/part-0.parquet
//
// basePath may be a local directory path or an s3:// URI.
func WriteScanParquet(basePath string, results []ScanResult) error {
	store, base, err := ParseStorePath(basePath)
	if err != nil {
		return err
	}

	type partKey struct{ org, date string }
	groups := make(map[partKey][]ScanRow)
	for _, r := range results {
		org, date := scanPartitionKey(r.Org, r.ScanTimestamp)
		k := partKey{org, date}
		groups[k] = append(groups[k], scanResultToRow(r))
	}

	for k, rows := range groups {
		partPath := path.Join(base,
			fmt.Sprintf("org=%s", k.org),
			fmt.Sprintf("date=%s", k.date),
			"part-0.parquet",
		)
		if err := writeScanRows(store, partPath, rows); err != nil {
			return fmt.Errorf("writing partition org=%s date=%s: %w", k.org, k.date, err)
		}
	}
	return nil
}

// WriteInspectParquet writes inspect results as Hive-partitioned Parquet under basePath.
func WriteInspectParquet(basePath string, results []InspectResult) error {
	store, base, err := ParseStorePath(basePath)
	if err != nil {
		return err
	}

	type partKey struct{ org, date string }
	groups := make(map[partKey][]InspectRow)
	for _, r := range results {
		org, date := scanPartitionKey(r.Org, r.ScanTimestamp)
		k := partKey{org, date}
		groups[k] = append(groups[k], inspectResultToRow(r))
	}

	for k, rows := range groups {
		partPath := path.Join(base,
			fmt.Sprintf("org=%s", k.org),
			fmt.Sprintf("date=%s", k.date),
			"part-0.parquet",
		)
		if err := writeInspectRows(store, partPath, rows); err != nil {
			return fmt.Errorf("writing partition org=%s date=%s: %w", k.org, k.date, err)
		}
	}
	return nil
}

// scanPartitionKey returns the (org, date) Hive partition values for a row.
func scanPartitionKey(org, scanTimestamp string) (string, string) {
	t, err := time.Parse(time.RFC3339, scanTimestamp)
	if err != nil {
		return org, "unknown"
	}
	return org, t.UTC().Format("2006-01-02")
}

// ---------------------------------------------------------------------------
// Low-level read/write
// ---------------------------------------------------------------------------

// writeScanRows serialises rows to Parquet and uploads via store.
func writeScanRows(store ObjectStore, filePath string, rows []ScanRow) error {
	var buf bytes.Buffer
	w := parquet.NewGenericWriter[ScanRow](&buf)
	if _, err := w.Write(rows); err != nil {
		return fmt.Errorf("writing parquet rows: %w", err)
	}
	if err := w.Close(); err != nil {
		return fmt.Errorf("closing parquet writer: %w", err)
	}
	return store.Write(context.Background(), filePath, &buf)
}

// writeInspectRows serialises inspect rows to Parquet and uploads via store.
func writeInspectRows(store ObjectStore, filePath string, rows []InspectRow) error {
	var buf bytes.Buffer
	w := parquet.NewGenericWriter[InspectRow](&buf)
	if _, err := w.Write(rows); err != nil {
		return fmt.Errorf("writing parquet rows: %w", err)
	}
	if err := w.Close(); err != nil {
		return fmt.Errorf("closing parquet writer: %w", err)
	}
	return store.Write(context.Background(), filePath, &buf)
}

// ReadScanRows downloads and deserialises a single Parquet file of ScanRows.
func ReadScanRows(store ObjectStore, filePath string) ([]ScanRow, error) {
	rc, err := store.Read(context.Background(), filePath)
	if err != nil {
		return nil, err
	}
	defer rc.Close()

	data, err := io.ReadAll(rc)
	if err != nil {
		return nil, fmt.Errorf("reading parquet file %s: %w", filePath, err)
	}

	return parseScanRows(data)
}

func parseScanRows(data []byte) ([]ScanRow, error) {
	br := bytes.NewReader(data)
	f, err := parquet.OpenFile(br, int64(len(data)))
	if err != nil {
		return nil, fmt.Errorf("opening parquet file: %w", err)
	}

	r := parquet.NewGenericReader[ScanRow](f)
	defer r.Close()

	var rows []ScanRow
	buf := make([]ScanRow, 1024)
	for {
		n, err := r.Read(buf)
		rows = append(rows, buf[:n]...)
		if err == io.EOF {
			break
		}
		if err != nil {
			return nil, fmt.Errorf("reading parquet rows: %w", err)
		}
	}
	return rows, nil
}

// ReadInspectRows downloads and deserialises a single Parquet file of InspectRows.
func ReadInspectRows(store ObjectStore, filePath string) ([]InspectRow, error) {
	rc, err := store.Read(context.Background(), filePath)
	if err != nil {
		return nil, err
	}
	defer rc.Close()

	data, err := io.ReadAll(rc)
	if err != nil {
		return nil, fmt.Errorf("reading parquet file %s: %w", filePath, err)
	}

	br := bytes.NewReader(data)
	f, err := parquet.OpenFile(br, int64(len(data)))
	if err != nil {
		return nil, fmt.Errorf("opening parquet file: %w", err)
	}

	r := parquet.NewGenericReader[InspectRow](f)
	defer r.Close()

	var rows []InspectRow
	buf := make([]InspectRow, 1024)
	for {
		n, err := r.Read(buf)
		rows = append(rows, buf[:n]...)
		if err == io.EOF {
			break
		}
		if err != nil {
			return nil, fmt.Errorf("reading parquet rows: %w", err)
		}
	}
	return rows, nil
}

package main

import (
	"encoding/csv"
	"fmt"
	"io"
)

// WriteScanCSV writes scan results in tidy data format.
func WriteScanCSV(w io.Writer, results []ScanResult) error {
	writer := csv.NewWriter(w)
	defer writer.Flush()

	header := []string{
		"scan_timestamp",
		"org",
		"repo",
		"repo_visibility",
		"repo_language",
		"repo_pushed_at",
		"category",
		"indicator",
		"found",
		"file_path",
		"details",
	}

	if err := writer.Write(header); err != nil {
		return fmt.Errorf("writing CSV header: %w", err)
	}

	for _, r := range results {
		found := "false"
		if r.Found {
			found = "true"
		}

		row := []string{
			r.ScanTimestamp,
			r.Org,
			r.Repo,
			r.RepoVisibility,
			r.RepoLanguage,
			r.RepoPushedAt,
			r.Category,
			r.Indicator,
			found,
			r.FilePath,
			r.Details,
		}

		if err := writer.Write(row); err != nil {
			return fmt.Errorf("writing CSV row: %w", err)
		}
	}

	return nil
}

// WriteInspectCSV writes inspection results as CSV.
func WriteInspectCSV(w io.Writer, results []InspectResult) error {
	writer := csv.NewWriter(w)
	defer writer.Flush()

	header := []string{
		"scan_timestamp",
		"org",
		"repo",
		"category",
		"indicator",
		"file_path",
		"content_size",
		"content_summary",
		"raw_content",
	}

	if err := writer.Write(header); err != nil {
		return fmt.Errorf("writing CSV header: %w", err)
	}

	for _, r := range results {
		row := []string{
			r.ScanTimestamp,
			r.Org,
			r.Repo,
			r.Category,
			r.Indicator,
			r.FilePath,
			fmt.Sprintf("%d", r.ContentSize),
			r.ContentSummary,
			r.RawContent,
		}

		if err := writer.Write(row); err != nil {
			return fmt.Errorf("writing CSV row: %w", err)
		}
	}

	return nil
}

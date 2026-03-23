package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path"
	"path/filepath"
	"strings"
)

// CachedIndicator stores a single indicator result in the cache.
type CachedIndicator struct {
	Category  string `json:"category"`
	Indicator string `json:"indicator"`
	Found     bool   `json:"found"`
	FilePath  string `json:"file_path,omitempty"`
	Details   string `json:"details,omitempty"`
	ScannedAt string `json:"scanned_at"`
}

// CachedRepo stores cached scan state for a single repo.
type CachedRepo struct {
	PushedAt   string            `json:"pushed_at"`
	ScannedAt  string            `json:"scanned_at"`
	Indicators []CachedIndicator `json:"indicators"`
}

// CacheData is the top-level in-memory cache structure.
// Key format: "org/repo"
type CacheData map[string]*CachedRepo

// Cache manages the scan state persistence.
type Cache struct {
	dir  string
	data CacheData
}

func NewCache(dir string) *Cache {
	return &Cache{
		dir:  dir,
		data: make(CacheData),
	}
}

// LoadCache loads the cache from dir.
//
// It first looks for a Parquet cache file (scan-cache.parquet).  If that is
// absent it falls back to the legacy JSON file (scan-cache.json) so existing
// caches are automatically migrated on the next Save call.
func LoadCache(dir string) (*Cache, error) {
	c := NewCache(dir)

	store, basePath, err := ParseStorePath(dir)
	if err != nil {
		return nil, fmt.Errorf("parsing cache path %q: %w", dir, err)
	}

	parquetPath := path.Join(basePath, "scan-cache.parquet")
	rows, err := ReadScanRows(store, parquetPath)
	if err == nil {
		c.data = cacheDataFromRows(rows)
		return c, nil
	}

	// Treat "not found" as an empty cache; propagate other errors.
	if !errors.Is(err, os.ErrNotExist) {
		return nil, fmt.Errorf("loading parquet cache: %w", err)
	}

	// Fall back to legacy JSON for local caches only.
	if _, ok := store.(*LocalStore); ok {
		jsonPath := filepath.Join(dir, "scan-cache.json")
		if jsonData, jerr := os.ReadFile(jsonPath); jerr == nil {
			var legacyData CacheData
			if jerr := json.Unmarshal(jsonData, &legacyData); jerr == nil {
				c.data = legacyData
				return c, nil
			}
		}
	}

	return c, nil
}

// Save persists the cache to a flat Parquet file at <dir>/scan-cache.parquet.
// The legacy JSON file (if any) is left untouched; users may delete it once
// they confirm the Parquet cache is working.
func (c *Cache) Save() error {
	store, basePath, err := ParseStorePath(c.dir)
	if err != nil {
		return fmt.Errorf("parsing cache path: %w", err)
	}

	// If using LocalStore ensure the directory exists.
	if _, ok := store.(*LocalStore); ok {
		if err := os.MkdirAll(c.dir, 0755); err != nil {
			return fmt.Errorf("creating cache dir: %w", err)
		}
	}

	rows := cacheDataToRows(c.data)
	parquetPath := path.Join(basePath, "scan-cache.parquet")
	return writeScanRows(store, parquetPath, rows)
}

// IsRepoFresh returns true if the repo's pushed_at matches the cached value,
// meaning it hasn't changed since we last scanned it.
func (c *Cache) IsRepoFresh(org, repo, pushedAt string) bool {
	key := org + "/" + repo
	cached, ok := c.data[key]
	if !ok {
		return false
	}
	return cached.PushedAt == pushedAt
}

// GetRepoResults returns cached indicator results for a repo.
func (c *Cache) GetRepoResults(org, repo string) []CachedIndicator {
	key := org + "/" + repo
	cached, ok := c.data[key]
	if !ok {
		return nil
	}
	return cached.Indicators
}

// SetRepoResults updates the cache for a repo.
func (c *Cache) SetRepoResults(org, repo, pushedAt string, indicators []CachedIndicator) {
	key := org + "/" + repo
	c.data[key] = &CachedRepo{
		PushedAt:   pushedAt,
		Indicators: indicators,
	}
}

// ---------------------------------------------------------------------------
// Conversion between CacheData and []ScanRow
// ---------------------------------------------------------------------------

// cacheDataFromRows builds the in-memory cache from a flat list of ScanRows.
// For each (org, repo) only the rows from the most recent scan_timestamp are
// kept, which matches the existing invalidation semantics.
func cacheDataFromRows(rows []ScanRow) CacheData {
	// Find the latest scan timestamp per repo.
	latest := make(map[string]string) // org/repo -> max scan_timestamp
	for _, r := range rows {
		key := r.Org + "/" + r.Repo
		if r.ScanTimestamp > latest[key] {
			latest[key] = r.ScanTimestamp
		}
	}

	data := make(CacheData)
	for _, r := range rows {
		key := r.Org + "/" + r.Repo
		if r.ScanTimestamp != latest[key] {
			continue
		}
		cached, ok := data[key]
		if !ok {
			cached = &CachedRepo{
				PushedAt:  r.RepoPushedAt,
				ScannedAt: r.ScanTimestamp,
			}
			data[key] = cached
		}
		cached.Indicators = append(cached.Indicators, CachedIndicator{
			Category:  r.Category,
			Indicator: r.Indicator,
			Found:     r.Found,
			FilePath:  r.FilePath,
			Details:   r.Details,
			ScannedAt: r.ScanTimestamp,
		})
	}
	return data
}

// cacheDataToRows converts the in-memory cache to a flat list of ScanRows.
func cacheDataToRows(data CacheData) []ScanRow {
	var rows []ScanRow
	for key, cached := range data {
		parts := strings.SplitN(key, "/", 2)
		if len(parts) != 2 {
			continue
		}
		org, repo := parts[0], parts[1]
		for _, ind := range cached.Indicators {
			rows = append(rows, ScanRow{
				ScanTimestamp: ind.ScannedAt,
				Org:           org,
				Repo:          repo,
				RepoPushedAt:  cached.PushedAt,
				Category:      ind.Category,
				Indicator:     ind.Indicator,
				Found:         ind.Found,
				FilePath:      ind.FilePath,
				Details:       ind.Details,
			})
		}
	}
	return rows
}

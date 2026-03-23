package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
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

// CacheData is the top-level structure of the cache file.
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

func LoadCache(dir string) (*Cache, error) {
	c := NewCache(dir)
	path := c.filePath()

	data, err := os.ReadFile(path)
	if err != nil {
		if os.IsNotExist(err) {
			return c, nil
		}
		return nil, fmt.Errorf("reading cache file: %w", err)
	}

	if err := json.Unmarshal(data, &c.data); err != nil {
		return nil, fmt.Errorf("parsing cache file: %w", err)
	}

	return c, nil
}

func (c *Cache) filePath() string {
	return filepath.Join(c.dir, "scan-cache.json")
}

func (c *Cache) Save() error {
	if err := os.MkdirAll(c.dir, 0755); err != nil {
		return fmt.Errorf("creating cache dir: %w", err)
	}

	data, err := json.MarshalIndent(c.data, "", "  ")
	if err != nil {
		return fmt.Errorf("marshaling cache: %w", err)
	}

	return os.WriteFile(c.filePath(), data, 0644)
}

func (c *Cache) repoKey(org, repo string) string {
	return org + "/" + repo
}

// IsRepoFresh returns true if the repo's pushed_at matches the cached value,
// meaning it hasn't changed since we last scanned it.
func (c *Cache) IsRepoFresh(org, repo, pushedAt string) bool {
	key := c.repoKey(org, repo)
	cached, ok := c.data[key]
	if !ok {
		return false
	}
	return cached.PushedAt == pushedAt
}

// GetRepoResults returns cached indicator results for a repo.
func (c *Cache) GetRepoResults(org, repo string) []CachedIndicator {
	key := c.repoKey(org, repo)
	cached, ok := c.data[key]
	if !ok {
		return nil
	}
	return cached.Indicators
}

// SetRepoResults updates the cache for a repo.
func (c *Cache) SetRepoResults(org, repo, pushedAt string, indicators []CachedIndicator) {
	key := c.repoKey(org, repo)
	c.data[key] = &CachedRepo{
		PushedAt:   pushedAt,
		Indicators: indicators,
	}
}

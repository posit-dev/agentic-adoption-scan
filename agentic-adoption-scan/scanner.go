package main

import (
	"fmt"
	"log"
	"strings"
	"time"
)

// ScanResult represents one observation in the tidy data output.
type ScanResult struct {
	ScanTimestamp  string // ISO 8601
	Org            string
	Repo           string
	RepoVisibility string
	RepoLanguage   string
	RepoPushedAt   string
	Category       string
	Indicator      string
	Found          bool
	FilePath       string
	Details        string
}

// Scanner orchestrates the scanning process.
type Scanner struct {
	Client          *GitHubClient
	Cache           *Cache
	Org             string
	Indicators      []Indicator
	ActiveSince     time.Time
	IncludeArchived bool
	Force           bool
	Logger          *log.Logger
}

// Scan runs the full scan and returns results.
func (s *Scanner) Scan() ([]ScanResult, error) {
	repos, err := s.Client.ListOrgRepos(s.Org)
	if err != nil {
		return nil, fmt.Errorf("listing repos: %w", err)
	}

	filtered := s.filterRepos(repos)
	s.Logger.Printf("Scanning %d repos (filtered from %d total)", len(filtered), len(repos))

	now := time.Now().UTC().Format(time.RFC3339)
	var results []ScanResult

	for i, repo := range filtered {
		s.Logger.Printf("[%d/%d] Scanning %s", i+1, len(filtered), repo.FullName)

		// Check cache
		if !s.Force && s.Cache.IsRepoFresh(s.Org, repo.Name, repo.PushedAt) {
			s.Logger.Printf("  Cache hit for %s (pushed_at unchanged)", repo.Name)
			cached := s.Cache.GetRepoResults(s.Org, repo.Name)
			for _, cr := range cached {
				results = append(results, ScanResult{
					ScanTimestamp:  cr.ScannedAt,
					Org:            s.Org,
					Repo:           repo.Name,
					RepoVisibility: repo.Visibility,
					RepoLanguage:   repo.Language,
					RepoPushedAt:   repo.PushedAt,
					Category:       cr.Category,
					Indicator:      cr.Indicator,
					Found:          cr.Found,
					FilePath:       cr.FilePath,
					Details:        cr.Details,
				})
			}
			continue
		}

		repoResults := s.scanRepo(repo, now)
		results = append(results, repoResults...)

		// Update cache
		var cacheResults []CachedIndicator
		for _, r := range repoResults {
			cacheResults = append(cacheResults, CachedIndicator{
				Category:  r.Category,
				Indicator: r.Indicator,
				Found:     r.Found,
				FilePath:  r.FilePath,
				Details:   r.Details,
				ScannedAt: r.ScanTimestamp,
			})
		}
		s.Cache.SetRepoResults(s.Org, repo.Name, repo.PushedAt, cacheResults)
	}

	return results, nil
}

func (s *Scanner) filterRepos(repos []Repo) []Repo {
	var filtered []Repo
	for _, r := range repos {
		if r.Archived && !s.IncludeArchived {
			continue
		}
		if r.PushedAt != "" {
			pushed, err := time.Parse(time.RFC3339, r.PushedAt)
			if err == nil && pushed.Before(s.ActiveSince) {
				continue
			}
		}
		filtered = append(filtered, r)
	}
	return filtered
}

func (s *Scanner) scanRepo(repo Repo, timestamp string) []ScanResult {
	owner := s.Org
	var results []ScanResult

	for _, ind := range s.Indicators {
		result := ScanResult{
			ScanTimestamp:  timestamp,
			Org:            s.Org,
			Repo:           repo.Name,
			RepoVisibility: repo.Visibility,
			RepoLanguage:   repo.Language,
			RepoPushedAt:   repo.PushedAt,
			Category:       ind.Category,
			Indicator:      ind.Name,
		}

		switch ind.SearchType {
		case FileExists:
			exists, _, err := s.Client.CheckPathExists(owner, repo.Name, ind.Target)
			if err != nil {
				s.Logger.Printf("  Warning: error checking %s in %s: %v", ind.Target, repo.Name, err)
			}
			result.Found = exists
			if exists {
				result.FilePath = ind.Target
			}

		case DirectoryExists:
			exists, isDir, err := s.Client.CheckPathExists(owner, repo.Name, ind.Target)
			if err != nil {
				s.Logger.Printf("  Warning: error checking %s in %s: %v", ind.Target, repo.Name, err)
			}
			result.Found = exists && isDir
			if result.Found {
				result.FilePath = ind.Target
			}

		case ContentSearch:
			sr, err := s.Client.SearchCode(owner, repo.Name, ind.Target)
			if err != nil {
				s.Logger.Printf("  Warning: error searching %s in %s: %v", ind.Target, repo.Name, err)
			} else if sr.TotalCount > 0 {
				result.Found = true
				var paths []string
				for _, item := range sr.Items {
					paths = append(paths, item.Path)
				}
				result.FilePath = strings.Join(paths, "; ")
				result.Details = fmt.Sprintf("%d matches", sr.TotalCount)
			}

		case WorkflowSearch:
			sr, err := s.Client.SearchCodeInWorkflows(owner, repo.Name, ind.Target)
			if err != nil {
				s.Logger.Printf("  Warning: error searching workflows in %s: %v", repo.Name, err)
			} else if sr.TotalCount > 0 {
				result.Found = true
				var paths []string
				for _, item := range sr.Items {
					paths = append(paths, item.Path)
				}
				result.FilePath = strings.Join(paths, "; ")
				result.Details = fmt.Sprintf("%d workflow files", sr.TotalCount)
			}
		}

		if result.Found {
			s.Logger.Printf("  Found: %s/%s", ind.Category, ind.Name)
		}
		results = append(results, result)
	}

	return results
}

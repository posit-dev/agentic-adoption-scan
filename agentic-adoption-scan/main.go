package main

import (
	"flag"
	"fmt"
	"log"
	"os"
	"time"
)

const usage = `Usage: agentic-adoption-scan <command> [flags]

Commands:
  scan      Detect agentic coding indicators across an org's repos
  inspect   Fetch and analyze content of detected indicators

Run 'agentic-adoption-scan <command> -help' for command-specific flags.
`

func main() {
	if len(os.Args) < 2 {
		fmt.Fprint(os.Stderr, usage)
		os.Exit(1)
	}

	switch os.Args[1] {
	case "scan":
		runScan(os.Args[2:])
	case "inspect":
		runInspect(os.Args[2:])
	default:
		fmt.Fprintf(os.Stderr, "Unknown command: %s\n\n%s", os.Args[1], usage)
		os.Exit(1)
	}
}

func runScan(args []string) {
	fs := flag.NewFlagSet("scan", flag.ExitOnError)
	org := fs.String("org", "", "GitHub organization to scan (required)")
	output := fs.String("output", "", "Output CSV file path (default: stdout)")
	days := fs.Int("days", 90, "Only include repos with activity in last N days")
	includeArchived := fs.Bool("include-archived", false, "Include archived repos")
	force := fs.Bool("force", false, "Bypass cache and rescan everything")
	cacheDir := fs.String("cache-dir", ".agentic-scan-cache", "Directory for scan state cache")
	verbose := fs.Bool("verbose", false, "Enable verbose logging")

	fs.Parse(args)

	if *org == "" {
		fmt.Fprintln(os.Stderr, "Error: --org is required")
		fs.Usage()
		os.Exit(1)
	}

	logger := log.New(os.Stderr, "", log.LstdFlags)
	if !*verbose {
		logger = log.New(nopWriter{}, "", 0)
	}

	ghClient := NewGitHubClient(logger)

	cache, err := LoadCache(*cacheDir)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Warning: could not load cache: %v (starting fresh)\n", err)
		cache = NewCache(*cacheDir)
	}

	cutoff := time.Now().AddDate(0, 0, -*days)

	scanner := &Scanner{
		Client:          ghClient,
		Cache:           cache,
		Org:             *org,
		Indicators:      DefaultIndicators(),
		ActiveSince:     cutoff,
		IncludeArchived: *includeArchived,
		Force:           *force,
		Logger:          logger,
	}

	results, err := scanner.Scan()
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		os.Exit(1)
	}

	var w *os.File
	if *output != "" {
		w, err = os.Create(*output)
		if err != nil {
			fmt.Fprintf(os.Stderr, "Error creating output file: %v\n", err)
			os.Exit(1)
		}
		defer w.Close()
	} else {
		w = os.Stdout
	}

	if err := WriteScanCSV(w, results); err != nil {
		fmt.Fprintf(os.Stderr, "Error writing CSV: %v\n", err)
		os.Exit(1)
	}

	if err := cache.Save(); err != nil {
		fmt.Fprintf(os.Stderr, "Warning: could not save cache: %v\n", err)
	}

	fmt.Fprintf(os.Stderr, "Scan complete: %d results across %d repos\n", len(results), countUniqueRepos(results))
}

func runInspect(args []string) {
	fs := flag.NewFlagSet("inspect", flag.ExitOnError)
	org := fs.String("org", "", "GitHub organization (required)")
	scanResults := fs.String("scan-results", "", "Path to scan results CSV (required)")
	output := fs.String("output", "", "Output CSV file path (default: stdout)")
	verbose := fs.Bool("verbose", false, "Enable verbose logging")

	fs.Parse(args)

	if *org == "" || *scanResults == "" {
		fmt.Fprintln(os.Stderr, "Error: --org and --scan-results are required")
		fs.Usage()
		os.Exit(1)
	}

	logger := log.New(os.Stderr, "", log.LstdFlags)
	if !*verbose {
		logger = log.New(nopWriter{}, "", 0)
	}

	ghClient := NewGitHubClient(logger)

	inspector := &Inspector{
		Client: ghClient,
		Org:    *org,
		Logger: logger,
	}

	results, err := inspector.Inspect(*scanResults)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		os.Exit(1)
	}

	var w *os.File
	if *output != "" {
		w, err = os.Create(*output)
		if err != nil {
			fmt.Fprintf(os.Stderr, "Error creating output file: %v\n", err)
			os.Exit(1)
		}
		defer w.Close()
	} else {
		w = os.Stdout
	}

	if err := WriteInspectCSV(w, results); err != nil {
		fmt.Fprintf(os.Stderr, "Error writing CSV: %v\n", err)
		os.Exit(1)
	}

	fmt.Fprintf(os.Stderr, "Inspection complete: %d files inspected\n", len(results))
}

func countUniqueRepos(results []ScanResult) int {
	seen := make(map[string]bool)
	for _, r := range results {
		seen[r.Repo] = true
	}
	return len(seen)
}

type nopWriter struct{}

func (nopWriter) Write(p []byte) (int, error) { return len(p), nil }

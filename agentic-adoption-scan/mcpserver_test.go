package main

import (
	"context"
	"encoding/json"
	"io"
	"log"
	"testing"

	"github.com/mark3labs/mcp-go/mcp"
)

// testMCPCfg creates a minimal MCPServerConfig for unit tests.
// No GitHub token required; the cache dir is a fresh temp directory.
func testMCPCfg(t *testing.T) MCPServerConfig {
	t.Helper()
	return MCPServerConfig{
		Logger:     log.New(io.Discard, "", 0),
		CacheDir:   t.TempDir(),
		ConfigPath: "",
	}
}

// callToolRequest builds a CallToolRequest with the given arguments.
func callToolRequest(args map[string]any) mcp.CallToolRequest {
	req := mcp.CallToolRequest{}
	req.Params.Arguments = args
	return req
}

// requireToolText extracts the text body from a successful tool result,
// failing the test if the result is nil or IsError is true.
func requireToolText(t *testing.T, result *mcp.CallToolResult) string {
	t.Helper()
	if result == nil {
		t.Fatal("tool result is nil")
	}
	if result.IsError {
		for _, c := range result.Content {
			if tc, ok := c.(mcp.TextContent); ok {
				t.Fatalf("tool returned error: %s", tc.Text)
			}
		}
		t.Fatal("tool returned IsError=true (no text content)")
	}
	for _, c := range result.Content {
		if tc, ok := c.(mcp.TextContent); ok {
			return tc.Text
		}
	}
	t.Fatal("tool result has no text content")
	return ""
}

// requireToolError asserts that the result has IsError=true.
func requireToolError(t *testing.T, result *mcp.CallToolResult, err error) {
	t.Helper()
	if err != nil {
		t.Fatalf("unexpected transport error: %v", err)
	}
	if result == nil {
		t.Fatal("result is nil")
	}
	if !result.IsError {
		t.Error("expected IsError=true but got successful result")
	}
}

// --- list_indicators tests (no GitHub token required) ---

func TestListIndicatorsReturnsValidJSON(t *testing.T) {
	cfg := testMCPCfg(t)
	handler := makeListIndicatorsHandler(cfg)
	result, err := handler(context.Background(), callToolRequest(nil))
	if err != nil {
		t.Fatalf("handler error: %v", err)
	}
	text := requireToolText(t, result)

	var data map[string]any
	if err := json.Unmarshal([]byte(text), &data); err != nil {
		t.Fatalf("response is not valid JSON: %v\nraw: %s", err, text)
	}
}

func TestListIndicatorsHasExpectedCategories(t *testing.T) {
	cfg := testMCPCfg(t)
	handler := makeListIndicatorsHandler(cfg)
	result, err := handler(context.Background(), callToolRequest(nil))
	if err != nil {
		t.Fatalf("handler error: %v", err)
	}
	text := requireToolText(t, result)

	var grouped map[string]any
	if err := json.Unmarshal([]byte(text), &grouped); err != nil {
		t.Fatalf("unmarshal error: %v", err)
	}

	required := []string{"claude-code", "github-copilot", "cursor", "mcp", "evals"}
	for _, cat := range required {
		if _, ok := grouped[cat]; !ok {
			t.Errorf("expected category %q missing from list_indicators response", cat)
		}
	}
}

func TestListIndicatorsEvalsCategory(t *testing.T) {
	cfg := testMCPCfg(t)
	handler := makeListIndicatorsHandler(cfg)
	result, err := handler(context.Background(), callToolRequest(nil))
	if err != nil {
		t.Fatalf("handler error: %v", err)
	}
	text := requireToolText(t, result)

	type indicatorInfo struct {
		Name string `json:"name"`
	}
	var grouped map[string][]indicatorInfo
	if err := json.Unmarshal([]byte(text), &grouped); err != nil {
		t.Fatalf("unmarshal error: %v", err)
	}

	evalsInds := grouped["evals"]
	if len(evalsInds) == 0 {
		t.Fatal("evals category has no indicators")
	}

	// Verify known evals indicators are present
	known := map[string]bool{
		"promptfoo config": false,
		"inspect AI":       false,
		"mcp-evals":        false,
	}
	for _, ind := range evalsInds {
		known[ind.Name] = true
	}
	for name, found := range known {
		if !found {
			t.Errorf("expected evals indicator %q not found", name)
		}
	}
}

func TestListIndicatorsIndicatorFields(t *testing.T) {
	cfg := testMCPCfg(t)
	handler := makeListIndicatorsHandler(cfg)
	result, err := handler(context.Background(), callToolRequest(nil))
	if err != nil {
		t.Fatalf("handler error: %v", err)
	}
	text := requireToolText(t, result)

	var grouped map[string][]map[string]any
	if err := json.Unmarshal([]byte(text), &grouped); err != nil {
		t.Fatalf("unmarshal error: %v", err)
	}

	for cat, indicators := range grouped {
		for i, ind := range indicators {
			for _, field := range []string{"name", "search_type", "target"} {
				v, ok := ind[field]
				if !ok || v == nil || v == "" {
					t.Errorf("category %q indicator[%d] missing or empty field %q", cat, i, field)
				}
			}
		}
	}
}

// --- Parameter validation tests (no GitHub required) ---

func TestScanOrgMissingOrg(t *testing.T) {
	cfg := testMCPCfg(t)
	handler := makeScanHandler(cfg)
	result, err := handler(context.Background(), callToolRequest(nil))
	requireToolError(t, result, err)
}

func TestInspectRepoMissingOrg(t *testing.T) {
	cfg := testMCPCfg(t)
	handler := makeInspectHandler(cfg)
	result, err := handler(context.Background(), callToolRequest(nil))
	requireToolError(t, result, err)
}

func TestInspectRepoMissingRepo(t *testing.T) {
	cfg := testMCPCfg(t)
	handler := makeInspectHandler(cfg)
	result, err := handler(context.Background(), callToolRequest(map[string]any{"org": "test-org"}))
	requireToolError(t, result, err)
}

func TestRepoSummaryMissingOrg(t *testing.T) {
	cfg := testMCPCfg(t)
	handler := makeRepoSummaryHandler(cfg)
	result, err := handler(context.Background(), callToolRequest(nil))
	requireToolError(t, result, err)
}

func TestAdoptionSummaryMissingOrg(t *testing.T) {
	cfg := testMCPCfg(t)
	handler := makeAdoptionSummaryHandler(cfg)
	result, err := handler(context.Background(), callToolRequest(nil))
	requireToolError(t, result, err)
}

// --- Cache behaviour tests (no GitHub required) ---

func TestRepoSummaryEmptyCache(t *testing.T) {
	cfg := testMCPCfg(t) // fresh temp dir = no cache
	handler := makeRepoSummaryHandler(cfg)
	result, err := handler(context.Background(), callToolRequest(map[string]any{
		"org":  "test-org",
		"repo": "test-repo",
	}))
	requireToolError(t, result, err)
}

func TestAdoptionSummaryEmptyCache(t *testing.T) {
	cfg := testMCPCfg(t)
	handler := makeAdoptionSummaryHandler(cfg)
	result, err := handler(context.Background(), callToolRequest(map[string]any{
		"org": "test-org",
	}))
	requireToolError(t, result, err)
}

// --- Server construction smoke tests ---

func TestNewMCPServerNotNil(t *testing.T) {
	cfg := testMCPCfg(t)
	s := newMCPServer(cfg)
	if s == nil {
		t.Fatal("newMCPServer returned nil")
	}
}

func TestMarshalToolResultRoundTrip(t *testing.T) {
	type sample struct {
		Name  string `json:"name"`
		Count int    `json:"count"`
	}
	result, err := marshalToolResult(sample{Name: "test", Count: 42})
	if err != nil {
		t.Fatalf("marshalToolResult error: %v", err)
	}
	if result == nil {
		t.Fatal("result is nil")
	}
	if result.IsError {
		t.Fatal("unexpected IsError=true")
	}

	text := requireToolText(t, result)
	var back sample
	if err := json.Unmarshal([]byte(text), &back); err != nil {
		t.Fatalf("round-trip unmarshal failed: %v", err)
	}
	if back.Name != "test" || back.Count != 42 {
		t.Errorf("round-trip mismatch: got %+v", back)
	}
}

// TestMarshalToolResultIndented verifies pretty-printing is applied.
func TestMarshalToolResultIndented(t *testing.T) {
	result, err := marshalToolResult(map[string]int{"a": 1})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	text := requireToolText(t, result)
	if len(text) == 0 {
		t.Fatal("empty result text")
	}
	// Indented JSON contains newlines
	found := false
	for _, ch := range text {
		if ch == '\n' {
			found = true
			break
		}
	}
	if !found {
		t.Error("expected indented JSON (with newlines), got: " + text)
	}
}

module github.com/posit-dev/eng-effectiveness-metrics-tools/agentic-adoption-scan

go 1.24.9

require (
	github.com/mark3labs/mcp-go v0.45.0
	gopkg.in/yaml.v3 v3.0.1
)

require (
	github.com/andybalholm/brotli v1.1.1
	github.com/bahlo/generic-list-go v0.2.0 // indirect
	github.com/buger/jsonparser v1.1.1 // indirect
	github.com/google/uuid v1.6.0 // indirect
	github.com/invopop/jsonschema v0.13.0 // indirect
	github.com/klauspost/compress v1.17.9
	github.com/mailru/easyjson v0.7.7 // indirect
	github.com/parquet-go/bitpack v1.0.0
	github.com/parquet-go/jsonlite v1.0.0
	github.com/parquet-go/parquet-go v0.29.0
	github.com/pierrec/lz4/v4 v4.1.21
	github.com/spf13/cast v1.7.1 // indirect
	github.com/twpayne/go-geom v1.6.1
	github.com/wk8/go-ordered-map/v2 v2.1.8 // indirect
	github.com/yosida95/uritemplate/v3 v3.0.2 // indirect
	golang.org/x/sys v0.38.0
	google.golang.org/protobuf v1.34.2
)

replace github.com/klauspost/compress => ./_local_deps/klauspost-compress

replace github.com/pierrec/lz4/v4 => ./_local_deps/pierrec-lz4v4

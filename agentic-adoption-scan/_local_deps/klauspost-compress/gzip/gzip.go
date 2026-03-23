// Package gzip wraps stdlib compress/gzip to satisfy parquet-go's dependency.
package gzip

import (
	stdgzip "compress/gzip"
	"io"
)

// Re-export stdlib types via aliases so parquet-go can embed *Reader directly.
type Writer = stdgzip.Writer
type Reader = stdgzip.Reader

const (
	NoCompression      = stdgzip.NoCompression
	BestSpeed          = stdgzip.BestSpeed
	BestCompression    = stdgzip.BestCompression
	DefaultCompression = stdgzip.DefaultCompression
	HuffmanOnly        = stdgzip.HuffmanOnly
)

func NewWriterLevel(w io.Writer, level int) (*Writer, error) {
	return stdgzip.NewWriterLevel(w, level)
}

func NewReader(r io.Reader) (*Reader, error) {
	return stdgzip.NewReader(r)
}

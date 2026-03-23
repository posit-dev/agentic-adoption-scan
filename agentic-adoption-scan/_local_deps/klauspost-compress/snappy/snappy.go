// Package snappy is a stub that satisfies parquet-go's compile-time dependency.
// Actual snappy encode/decode is never invoked when writing uncompressed parquet.
package snappy

import "fmt"

// Encode is a stub; raw snappy encoding is not used with uncompressed parquet.
func Encode(dst, src []byte) []byte {
	if cap(dst) < len(src) {
		dst = make([]byte, len(src))
	}
	return dst[:copy(dst, src)]
}

// Decode is a stub; snappy-compressed files are not read by this tool.
func Decode(dst, src []byte) ([]byte, error) {
	return nil, fmt.Errorf("snappy: decode not implemented (stub)")
}

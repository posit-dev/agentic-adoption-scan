// Package lz4 is a stub that satisfies parquet-go's compile-time dependency.
// LZ4 encode/decode is never invoked when writing uncompressed parquet.
package lz4

import "fmt"

// CompressionLevel is the LZ4 compression level type.
type CompressionLevel int

const (
	Fast    CompressionLevel = 0
	Level1  CompressionLevel = 1
	Level2  CompressionLevel = 2
	Level3  CompressionLevel = 3
	Level4  CompressionLevel = 4
	Level5  CompressionLevel = 5
	Level6  CompressionLevel = 6
	Level7  CompressionLevel = 7
	Level8  CompressionLevel = 8
	Level9  CompressionLevel = 9
)

// Compressor is a stub LZ4 block compressor.
type Compressor struct{}

// CompressBlock is a stub; LZ4 compression is not used with uncompressed parquet.
func (c *Compressor) CompressBlock(src, dst []byte) (int, error) {
	return 0, fmt.Errorf("lz4: CompressBlock not implemented (stub)")
}

// CompressorHC is a stub high-compression LZ4 compressor.
type CompressorHC struct {
	Level CompressionLevel
}

// CompressBlock is a stub; LZ4 compression is not used with uncompressed parquet.
func (c *CompressorHC) CompressBlock(src, dst []byte) (int, error) {
	return 0, fmt.Errorf("lz4: CompressBlockHC not implemented (stub)")
}

// CompressBlockBound returns the maximum compressed block size for a given input size.
func CompressBlockBound(n int) int {
	return n + n/255 + 16
}

// UncompressBlock is a stub; LZ4 decompression is not used by this tool.
func UncompressBlock(src, dst []byte) (int, error) {
	return 0, fmt.Errorf("lz4: UncompressBlock not implemented (stub)")
}

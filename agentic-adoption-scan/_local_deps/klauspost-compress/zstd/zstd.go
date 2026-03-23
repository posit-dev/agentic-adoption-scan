// Package zstd is a stub that satisfies parquet-go's compile-time dependency.
// Zstd encode/decode is never invoked when writing uncompressed parquet.
package zstd

import (
	"fmt"
	"io"
)

// EncoderLevel represents the zstd compression level.
type EncoderLevel int

const (
	SpeedFastest           EncoderLevel = 1
	SpeedDefault           EncoderLevel = 3
	SpeedBetterCompression EncoderLevel = 6
	SpeedBestCompression   EncoderLevel = 11
)

// EncoderOption configures a zstd Encoder.
type EncoderOption func(*encoderConfig)

type encoderConfig struct{}

// DecoderOption configures a zstd Decoder.
type DecoderOption func(*decoderConfig)

type decoderConfig struct{}

// WithEncoderConcurrency sets the encoder concurrency.
func WithEncoderConcurrency(n int) EncoderOption { return func(*encoderConfig) {} }

// WithEncoderLevel sets the encoder compression level.
func WithEncoderLevel(l EncoderLevel) EncoderOption { return func(*encoderConfig) {} }

// WithZeroFrames controls zero-frame output.
func WithZeroFrames(b bool) EncoderOption { return func(*encoderConfig) {} }

// WithEncoderCRC controls CRC generation.
func WithEncoderCRC(b bool) EncoderOption { return func(*encoderConfig) {} }

// WithDecoderConcurrency sets the decoder concurrency.
func WithDecoderConcurrency(n int) DecoderOption { return func(*decoderConfig) {} }

// Encoder is a stub zstd encoder.
type Encoder struct{}

// NewWriter creates a stub zstd encoder.
func NewWriter(_ io.Writer, _ ...EncoderOption) (*Encoder, error) {
	return &Encoder{}, nil
}

// EncodeAll is a stub; zstd encoding is not used with uncompressed parquet.
func (e *Encoder) EncodeAll(src, dst []byte) []byte {
	panic("zstd: EncodeAll not implemented (stub)")
}

// Close is a no-op for the stub encoder.
func (e *Encoder) Close() error { return nil }

// Decoder is a stub zstd decoder.
type Decoder struct{}

// NewReader creates a stub zstd decoder.
func NewReader(_ io.Reader, _ ...DecoderOption) (*Decoder, error) {
	return &Decoder{}, nil
}

// DecodeAll is a stub; zstd decoding is not used with uncompressed parquet.
func (d *Decoder) DecodeAll(src, dst []byte) ([]byte, error) {
	return nil, fmt.Errorf("zstd: DecodeAll not implemented (stub)")
}

// Close is a no-op for the stub decoder.
func (d *Decoder) Close() {}

package main

import (
	"bufio"
	"bytes"
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"
)

// ObjectStore is a unified interface for reading and writing files to either
// the local filesystem or Amazon S3.
type ObjectStore interface {
	// Read returns a reader for the object at path/key.
	Read(ctx context.Context, path string) (io.ReadCloser, error)

	// Write uploads r to path/key.
	Write(ctx context.Context, path string, r io.Reader) error

	// List returns all object keys with the given prefix that end in .parquet.
	List(ctx context.Context, prefix string) ([]string, error)

	// Delete removes the object at path/key.
	Delete(ctx context.Context, path string) error
}

// ParseStorePath returns the appropriate ObjectStore for raw and the
// normalised path/key within that store.
//
// Paths beginning with "s3://" use S3; everything else uses the local
// filesystem.
func ParseStorePath(raw string) (ObjectStore, string, error) {
	if strings.HasPrefix(raw, "s3://") {
		rest := strings.TrimPrefix(raw, "s3://")
		parts := strings.SplitN(rest, "/", 2)
		bucket := parts[0]
		key := ""
		if len(parts) > 1 {
			key = parts[1]
		}
		store, err := newS3Store(bucket)
		if err != nil {
			return nil, "", err
		}
		return store, key, nil
	}
	return &LocalStore{}, raw, nil
}

// ---------------------------------------------------------------------------
// LocalStore – local filesystem implementation
// ---------------------------------------------------------------------------

// LocalStore implements ObjectStore for the local filesystem.
type LocalStore struct{}

func (s *LocalStore) Read(_ context.Context, path string) (io.ReadCloser, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, err // os.IsNotExist checks work on this error
	}
	return f, nil
}

func (s *LocalStore) Write(_ context.Context, path string, r io.Reader) error {
	if err := os.MkdirAll(filepath.Dir(path), 0755); err != nil {
		return fmt.Errorf("creating directories for %s: %w", path, err)
	}
	f, err := os.Create(path)
	if err != nil {
		return err
	}
	defer f.Close()
	_, err = io.Copy(f, r)
	return err
}

func (s *LocalStore) List(_ context.Context, prefix string) ([]string, error) {
	var paths []string
	err := filepath.WalkDir(prefix, func(p string, d os.DirEntry, err error) error {
		if err != nil {
			if os.IsNotExist(err) {
				return nil
			}
			return err
		}
		if !d.IsDir() && strings.HasSuffix(p, ".parquet") {
			paths = append(paths, p)
		}
		return nil
	})
	return paths, err
}

func (s *LocalStore) Delete(_ context.Context, path string) error {
	return os.Remove(path)
}

// ---------------------------------------------------------------------------
// S3Store – Amazon S3 implementation using stdlib net/http + AWS Sig v4
// ---------------------------------------------------------------------------

// S3Store implements ObjectStore for Amazon S3.
type S3Store struct {
	bucket string
	region string
	creds  awsCreds
}

type awsCreds struct {
	accessKeyID     string
	secretAccessKey string
	sessionToken    string
}

func newS3Store(bucket string) (*S3Store, error) {
	creds, err := resolveAWSCreds()
	if err != nil {
		return nil, err
	}
	region := resolveAWSRegion()
	return &S3Store{bucket: bucket, region: region, creds: creds}, nil
}

func resolveAWSRegion() string {
	for _, env := range []string{"AWS_REGION", "AWS_DEFAULT_REGION"} {
		if r := os.Getenv(env); r != "" {
			return r
		}
	}
	return "us-east-1"
}

func resolveAWSCreds() (awsCreds, error) {
	// 1. Environment variables
	if key := os.Getenv("AWS_ACCESS_KEY_ID"); key != "" {
		return awsCreds{
			accessKeyID:     key,
			secretAccessKey: os.Getenv("AWS_SECRET_ACCESS_KEY"),
			sessionToken:    os.Getenv("AWS_SESSION_TOKEN"),
		}, nil
	}
	// 2. Shared credentials file
	if creds, err := loadSharedCreds(); err == nil {
		return creds, nil
	}
	return awsCreds{}, errors.New("no AWS credentials found; set AWS_ACCESS_KEY_ID or configure ~/.aws/credentials")
}

func loadSharedCreds() (awsCreds, error) {
	profile := os.Getenv("AWS_PROFILE")
	if profile == "" {
		profile = "default"
	}
	home, err := os.UserHomeDir()
	if err != nil {
		return awsCreds{}, err
	}
	f, err := os.Open(filepath.Join(home, ".aws", "credentials"))
	if err != nil {
		return awsCreds{}, err
	}
	defer f.Close()

	var (
		inProfile bool
		creds     awsCreds
	)
	scanner := bufio.NewScanner(f)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if strings.HasPrefix(line, "[") {
			inProfile = strings.TrimSuffix(strings.TrimPrefix(line, "["), "]") == profile
			continue
		}
		if !inProfile || strings.HasPrefix(line, "#") {
			continue
		}
		parts := strings.SplitN(line, "=", 2)
		if len(parts) != 2 {
			continue
		}
		key := strings.TrimSpace(parts[0])
		val := strings.TrimSpace(parts[1])
		switch key {
		case "aws_access_key_id":
			creds.accessKeyID = val
		case "aws_secret_access_key":
			creds.secretAccessKey = val
		case "aws_session_token":
			creds.sessionToken = val
		}
	}
	if creds.accessKeyID == "" {
		return awsCreds{}, fmt.Errorf("profile %q not found in ~/.aws/credentials", profile)
	}
	return creds, nil
}

func (s *S3Store) endpoint(key string) string {
	return fmt.Sprintf("https://%s.s3.%s.amazonaws.com/%s", s.bucket, s.region, key)
}

func (s *S3Store) Read(ctx context.Context, key string) (io.ReadCloser, error) {
	req, err := http.NewRequestWithContext(ctx, "GET", s.endpoint(key), nil)
	if err != nil {
		return nil, err
	}
	s.signRequest(req, nil)
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("s3 get s3://%s/%s: %w", s.bucket, key, err)
	}
	if resp.StatusCode == 404 {
		resp.Body.Close()
		return nil, fmt.Errorf("s3://%s/%s: %w", s.bucket, key, os.ErrNotExist)
	}
	if resp.StatusCode != 200 {
		body, _ := io.ReadAll(resp.Body)
		resp.Body.Close()
		return nil, fmt.Errorf("s3 get s3://%s/%s: HTTP %d: %s", s.bucket, key, resp.StatusCode, body)
	}
	return resp.Body, nil
}

func (s *S3Store) Write(ctx context.Context, key string, r io.Reader) error {
	body, err := io.ReadAll(r)
	if err != nil {
		return fmt.Errorf("reading data for s3 put: %w", err)
	}
	req, err := http.NewRequestWithContext(ctx, "PUT", s.endpoint(key), bytes.NewReader(body))
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/octet-stream")
	s.signRequest(req, body)
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return fmt.Errorf("s3 put s3://%s/%s: %w", s.bucket, key, err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		body, _ := io.ReadAll(resp.Body)
		return fmt.Errorf("s3 put s3://%s/%s: HTTP %d: %s", s.bucket, key, resp.StatusCode, body)
	}
	return nil
}

func (s *S3Store) List(ctx context.Context, prefix string) ([]string, error) {
	var keys []string
	continuationToken := ""
	for {
		q := url.Values{
			"list-type": {"2"},
			"prefix":    {prefix},
		}
		if continuationToken != "" {
			q.Set("continuation-token", continuationToken)
		}
		rawURL := fmt.Sprintf("https://%s.s3.%s.amazonaws.com/?%s", s.bucket, s.region, q.Encode())
		req, err := http.NewRequestWithContext(ctx, "GET", rawURL, nil)
		if err != nil {
			return nil, err
		}
		s.signRequest(req, nil)
		resp, err := http.DefaultClient.Do(req)
		if err != nil {
			return nil, fmt.Errorf("s3 list s3://%s/%s: %w", s.bucket, prefix, err)
		}
		body, err := io.ReadAll(resp.Body)
		resp.Body.Close()
		if err != nil {
			return nil, err
		}
		if resp.StatusCode != 200 {
			return nil, fmt.Errorf("s3 list s3://%s/%s: HTTP %d: %s", s.bucket, prefix, resp.StatusCode, body)
		}
		// Simple XML parsing – avoids importing encoding/xml for just two fields.
		pageKeys := extractXMLValues(string(body), "Key")
		for _, k := range pageKeys {
			if strings.HasSuffix(k, ".parquet") {
				keys = append(keys, k)
			}
		}
		tokens := extractXMLValues(string(body), "NextContinuationToken")
		if len(tokens) == 0 {
			break
		}
		continuationToken = tokens[0]
	}
	return keys, nil
}

func (s *S3Store) Delete(ctx context.Context, key string) error {
	req, err := http.NewRequestWithContext(ctx, "DELETE", s.endpoint(key), nil)
	if err != nil {
		return err
	}
	s.signRequest(req, nil)
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return fmt.Errorf("s3 delete s3://%s/%s: %w", s.bucket, key, err)
	}
	resp.Body.Close()
	if resp.StatusCode != 204 && resp.StatusCode != 200 {
		return fmt.Errorf("s3 delete s3://%s/%s: HTTP %d", s.bucket, key, resp.StatusCode)
	}
	return nil
}

// signRequest adds AWS Signature Version 4 headers to req.
// body is the raw request body bytes (nil for requests without a body).
func (s *S3Store) signRequest(req *http.Request, body []byte) {
	now := time.Now().UTC()
	dateStamp := now.Format("20060102")
	amzDate := now.Format("20060102T150405Z")

	if body == nil {
		body = []byte{}
	}
	bodyHash := sha256Hex(body)

	req.Header.Set("x-amz-date", amzDate)
	req.Header.Set("x-amz-content-sha256", bodyHash)
	if s.creds.sessionToken != "" {
		req.Header.Set("x-amz-security-token", s.creds.sessionToken)
	}

	// Canonical headers (sorted, lowercase)
	var signedHeaderNames []string
	headerMap := map[string]string{}
	for name, vals := range req.Header {
		lower := strings.ToLower(name)
		headerMap[lower] = strings.Join(vals, ",")
		signedHeaderNames = append(signedHeaderNames, lower)
	}
	// Host is not in req.Header, add it explicitly
	host := req.URL.Host
	headerMap["host"] = host
	signedHeaderNames = append(signedHeaderNames, "host")
	sort.Strings(signedHeaderNames)

	var canonicalHeaders strings.Builder
	for _, h := range signedHeaderNames {
		canonicalHeaders.WriteString(h)
		canonicalHeaders.WriteByte(':')
		canonicalHeaders.WriteString(strings.TrimSpace(headerMap[h]))
		canonicalHeaders.WriteByte('\n')
	}
	signedHeaders := strings.Join(signedHeaderNames, ";")

	canonicalURI := req.URL.EscapedPath()
	if canonicalURI == "" {
		canonicalURI = "/"
	}
	canonicalQueryString := req.URL.Query().Encode()

	canonicalRequest := strings.Join([]string{
		req.Method,
		canonicalURI,
		canonicalQueryString,
		canonicalHeaders.String(),
		signedHeaders,
		bodyHash,
	}, "\n")

	credentialScope := strings.Join([]string{dateStamp, s.region, "s3", "aws4_request"}, "/")
	stringToSign := strings.Join([]string{
		"AWS4-HMAC-SHA256",
		amzDate,
		credentialScope,
		sha256Hex([]byte(canonicalRequest)),
	}, "\n")

	signingKey := s.deriveSigningKey(dateStamp)
	signature := hex.EncodeToString(hmacSHA256(signingKey, []byte(stringToSign)))

	req.Header.Set("Authorization", fmt.Sprintf(
		"AWS4-HMAC-SHA256 Credential=%s/%s, SignedHeaders=%s, Signature=%s",
		s.creds.accessKeyID, credentialScope, signedHeaders, signature,
	))
}

func (s *S3Store) deriveSigningKey(dateStamp string) []byte {
	kDate := hmacSHA256([]byte("AWS4"+s.creds.secretAccessKey), []byte(dateStamp))
	kRegion := hmacSHA256(kDate, []byte(s.region))
	kService := hmacSHA256(kRegion, []byte("s3"))
	return hmacSHA256(kService, []byte("aws4_request"))
}

func hmacSHA256(key, data []byte) []byte {
	h := hmac.New(sha256.New, key)
	h.Write(data)
	return h.Sum(nil)
}

func sha256Hex(data []byte) string {
	h := sha256.Sum256(data)
	return hex.EncodeToString(h[:])
}

// extractXMLValues extracts text content of all elements with the given tag
// name from a simple (non-nested-with-same-name) XML string.
func extractXMLValues(xml, tag string) []string {
	open := "<" + tag + ">"
	close := "</" + tag + ">"
	var vals []string
	for {
		start := strings.Index(xml, open)
		if start < 0 {
			break
		}
		start += len(open)
		end := strings.Index(xml[start:], close)
		if end < 0 {
			break
		}
		vals = append(vals, xml[start:start+end])
		xml = xml[start+end+len(close):]
	}
	return vals
}

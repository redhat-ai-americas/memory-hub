package handler_test

import (
	"bytes"
	"fmt"
	"io"
	"mime/multipart"
	"net/http"
	"net/http/httptest"
	"net/textproto"
	"strings"
	"testing"
	"time"

	"github.com/fips-agents/gateway-template/internal/config"
	"github.com/fips-agents/gateway-template/internal/handler"
)

// buildMultipart builds a multipart/form-data body containing one file
// part with the given filename, declared Content-Type, and payload, plus
// any extra form fields. Returns the body, the boundary, and the byte
// length so callers can set Content-Length.
func buildMultipart(t *testing.T, filename, contentType string, payload []byte, fields map[string]string) (*bytes.Buffer, string, int) {
	t.Helper()
	buf := &bytes.Buffer{}
	mw := multipart.NewWriter(buf)
	for k, v := range fields {
		if err := mw.WriteField(k, v); err != nil {
			t.Fatalf("WriteField: %v", err)
		}
	}
	hdr := textproto.MIMEHeader{}
	hdr.Set("Content-Disposition", fmt.Sprintf(`form-data; name=%q; filename=%q`, "file", filename))
	hdr.Set("Content-Type", contentType)
	part, err := mw.CreatePart(hdr)
	if err != nil {
		t.Fatalf("CreatePart: %v", err)
	}
	if _, err := part.Write(payload); err != nil {
		t.Fatalf("part.Write: %v", err)
	}
	if err := mw.Close(); err != nil {
		t.Fatalf("mw.Close: %v", err)
	}
	return buf, mw.Boundary(), buf.Len()
}

// newFilesHandler wires a FilesUploadHandler against a backend test
// server with the given gateway config overrides.
func newFilesHandler(backendURL string, cfg *config.Config) *handler.FilesUploadHandler {
	return &handler.FilesUploadHandler{
		BackendURL: backendURL,
		MaxBytes:   cfg.FilesMaxBytes,
		Cfg:        cfg,
		Timeout:    cfg.FilesUploadTimeout,
		Client:     &http.Client{},
	}
}

func TestFilesUpload_HappyPath(t *testing.T) {
	var receivedBody []byte
	var receivedCT string
	var receivedSubject, receivedAuthorization string
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/v1/files" {
			t.Errorf("backend path = %q, want /v1/files", r.URL.Path)
		}
		receivedCT = r.Header.Get("Content-Type")
		receivedSubject = r.Header.Get("X-Auth-Subject")
		receivedAuthorization = r.Header.Get("Authorization")
		receivedBody, _ = io.ReadAll(r.Body)
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusCreated)
		_, _ = w.Write([]byte(`{"file_id":"file_abc"}`))
	}))
	defer backend.Close()

	cfg := &config.Config{
		FilesMaxBytes:      1 << 20,
		FilesUploadTimeout: 10 * time.Second,
	}
	h := newFilesHandler(backend.URL, cfg)

	body, boundary, length := buildMultipart(t, "doc.pdf", "application/pdf", []byte("%PDF-1.4 hello"), map[string]string{"session_id": "s_42"})
	req := httptest.NewRequest(http.MethodPost, "/v1/files", body)
	req.Header.Set("Content-Type", "multipart/form-data; boundary="+boundary)
	req.ContentLength = int64(length)
	req.Header.Set("X-Auth-Subject", "alice")
	req.Header.Set("Authorization", "Bearer swapped")

	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)

	if rec.Code != http.StatusCreated {
		t.Fatalf("status = %d, want 201; body=%s", rec.Code, rec.Body.String())
	}
	if !strings.HasPrefix(receivedCT, "multipart/form-data;") {
		t.Errorf("backend Content-Type = %q, want multipart/form-data;...", receivedCT)
	}
	if receivedSubject != "alice" {
		t.Errorf("X-Auth-Subject forwarded = %q, want alice", receivedSubject)
	}
	if receivedAuthorization != "Bearer swapped" {
		t.Errorf("Authorization forwarded = %q, want swapped token", receivedAuthorization)
	}
	if !bytes.Contains(receivedBody, []byte("%PDF-1.4 hello")) {
		t.Errorf("file payload not forwarded; body=%q", receivedBody)
	}
	if !bytes.Contains(receivedBody, []byte("s_42")) {
		t.Errorf("session_id form field not forwarded; body=%q", receivedBody)
	}
}

func TestFilesUpload_RejectsContentLengthOverCap(t *testing.T) {
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		t.Error("backend must not be reached when Content-Length exceeds cap")
	}))
	defer backend.Close()

	cfg := &config.Config{FilesMaxBytes: 1024}
	h := newFilesHandler(backend.URL, cfg)

	body, boundary, _ := buildMultipart(t, "big.bin", "application/octet-stream", make([]byte, 4096), nil)
	req := httptest.NewRequest(http.MethodPost, "/v1/files", body)
	req.Header.Set("Content-Type", "multipart/form-data; boundary="+boundary)
	// Lie about Content-Length to force the early rejection path even
	// though the body itself happens to also overflow.
	req.ContentLength = 999_999

	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)

	if rec.Code != http.StatusRequestEntityTooLarge {
		t.Fatalf("status = %d, want 413", rec.Code)
	}
	if !strings.Contains(rec.Body.String(), "max_bytes") {
		t.Errorf("body should include max_bytes hint: %s", rec.Body.String())
	}
}

func TestFilesUpload_RejectsStreamingOverflow(t *testing.T) {
	backendCalls := 0
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		backendCalls++
		// Drain so the pipe doesn't block; reply success even though the
		// gateway should ultimately surface a 413 because MaxBytesReader
		// will return an error mid-copy.
		_, _ = io.Copy(io.Discard, r.Body)
		w.WriteHeader(http.StatusCreated)
	}))
	defer backend.Close()

	cfg := &config.Config{FilesMaxBytes: 256}
	h := newFilesHandler(backend.URL, cfg)

	body, boundary, length := buildMultipart(t, "big.bin", "application/octet-stream", bytes.Repeat([]byte("A"), 4096), nil)
	req := httptest.NewRequest(http.MethodPost, "/v1/files", body)
	req.Header.Set("Content-Type", "multipart/form-data; boundary="+boundary)
	// Match the inbound length so the early Content-Length check
	// passes — must trip MaxBytesReader instead.
	req.ContentLength = int64(length)
	// Force chunked-style behavior: zero out Content-Length on the
	// header, MaxBytesReader still enforces the cap.
	req.Header.Del("Content-Length")
	req.ContentLength = -1

	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)

	if rec.Code != http.StatusRequestEntityTooLarge {
		t.Fatalf("status = %d, want 413 (body=%s, backend_calls=%d)", rec.Code, rec.Body.String(), backendCalls)
	}
}

func TestFilesUpload_RejectsDisallowedMIME(t *testing.T) {
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		t.Error("backend must not be reached when MIME is disallowed")
	}))
	defer backend.Close()

	cfg := &config.Config{
		FilesMaxBytes:    1 << 20,
		FilesAllowedMIME: []string{"application/pdf", "image/*"},
	}
	h := newFilesHandler(backend.URL, cfg)

	body, boundary, length := buildMultipart(t, "evil.exe", "application/x-msdownload", []byte("MZ"), nil)
	req := httptest.NewRequest(http.MethodPost, "/v1/files", body)
	req.Header.Set("Content-Type", "multipart/form-data; boundary="+boundary)
	req.ContentLength = int64(length)

	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)

	if rec.Code != http.StatusUnsupportedMediaType {
		t.Fatalf("status = %d, want 415; body=%s", rec.Code, rec.Body.String())
	}
	if !strings.Contains(rec.Body.String(), "x-msdownload") {
		t.Errorf("body should mention rejected content_type, got %s", rec.Body.String())
	}
}

func TestFilesUpload_AllowsWildcardMIME(t *testing.T) {
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = io.Copy(io.Discard, r.Body)
		w.WriteHeader(http.StatusCreated)
	}))
	defer backend.Close()

	cfg := &config.Config{
		FilesMaxBytes:    1 << 20,
		FilesAllowedMIME: []string{"application/pdf", "image/*"},
	}
	h := newFilesHandler(backend.URL, cfg)

	body, boundary, length := buildMultipart(t, "pic.png", "image/png", []byte("\x89PNG"), nil)
	req := httptest.NewRequest(http.MethodPost, "/v1/files", body)
	req.Header.Set("Content-Type", "multipart/form-data; boundary="+boundary)
	req.ContentLength = int64(length)

	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)

	if rec.Code != http.StatusCreated {
		t.Fatalf("wildcard match should pass: status=%d body=%s", rec.Code, rec.Body.String())
	}
}

func TestFilesUpload_RejectsNonMultipart(t *testing.T) {
	cfg := &config.Config{FilesMaxBytes: 1 << 20}
	h := newFilesHandler("http://unreached", cfg)

	req := httptest.NewRequest(http.MethodPost, "/v1/files", strings.NewReader(`{"oops":true}`))
	req.Header.Set("Content-Type", "application/json")

	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)

	if rec.Code != http.StatusUnsupportedMediaType {
		t.Fatalf("status = %d, want 415", rec.Code)
	}
}

func TestFilesUpload_MethodNotAllowed(t *testing.T) {
	cfg := &config.Config{FilesMaxBytes: 1 << 20}
	h := newFilesHandler("http://unreached", cfg)

	req := httptest.NewRequest(http.MethodGet, "/v1/files", nil)
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)

	if rec.Code != http.StatusMethodNotAllowed {
		t.Fatalf("status = %d, want 405", rec.Code)
	}
}

func TestFilesUpload_BackendErrorBecomes502(t *testing.T) {
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// Hijack and abort to simulate an unreachable upstream. Avoids
		// the test-client being lenient about clean shutdowns.
		hj, ok := w.(http.Hijacker)
		if !ok {
			t.Fatal("expected hijacker")
		}
		conn, _, _ := hj.Hijack()
		_ = conn.Close()
	}))
	defer backend.Close()

	cfg := &config.Config{FilesMaxBytes: 1 << 20, FilesUploadTimeout: 5 * time.Second}
	h := newFilesHandler(backend.URL, cfg)

	body, boundary, length := buildMultipart(t, "doc.pdf", "application/pdf", []byte("hi"), nil)
	req := httptest.NewRequest(http.MethodPost, "/v1/files", body)
	req.Header.Set("Content-Type", "multipart/form-data; boundary="+boundary)
	req.ContentLength = int64(length)

	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)

	if rec.Code != http.StatusBadGateway {
		t.Fatalf("status = %d, want 502", rec.Code)
	}
}

func TestFilesUpload_TimeoutSurfaces504(t *testing.T) {
	// Backend hangs forever — gateway timeout should fire and surface 504.
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		select {
		case <-r.Context().Done():
		case <-time.After(5 * time.Second):
		}
	}))
	defer backend.Close()

	cfg := &config.Config{FilesMaxBytes: 1 << 20, FilesUploadTimeout: 100 * time.Millisecond}
	h := newFilesHandler(backend.URL, cfg)

	body, boundary, length := buildMultipart(t, "doc.pdf", "application/pdf", []byte("hi"), nil)
	req := httptest.NewRequest(http.MethodPost, "/v1/files", body)
	req.Header.Set("Content-Type", "multipart/form-data; boundary="+boundary)
	req.ContentLength = int64(length)

	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)

	if rec.Code != http.StatusGatewayTimeout {
		t.Fatalf("status = %d, want 504; body=%s", rec.Code, rec.Body.String())
	}
}

func TestFilesUpload_NoCapWhenMaxBytesZero(t *testing.T) {
	// MaxBytes == 0 means "no cap" — both the early Content-Length check
	// and the wrapping reader are skipped.
	backendHit := false
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		backendHit = true
		_, _ = io.Copy(io.Discard, r.Body)
		w.WriteHeader(http.StatusCreated)
	}))
	defer backend.Close()

	cfg := &config.Config{FilesMaxBytes: 0}
	h := newFilesHandler(backend.URL, cfg)

	body, boundary, length := buildMultipart(t, "huge.bin", "application/octet-stream", make([]byte, 4096), nil)
	req := httptest.NewRequest(http.MethodPost, "/v1/files", body)
	req.Header.Set("Content-Type", "multipart/form-data; boundary="+boundary)
	req.ContentLength = int64(length)

	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)

	if rec.Code != http.StatusCreated {
		t.Fatalf("status = %d, want 201", rec.Code)
	}
	if !backendHit {
		t.Error("backend should have been reached")
	}
}


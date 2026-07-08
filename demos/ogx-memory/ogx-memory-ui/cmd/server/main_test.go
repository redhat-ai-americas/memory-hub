package main

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"net/http/httputil"
	"net/url"
	"strings"
	"testing"

	"github.com/fips-agents/ui-template/static"
)

// buildMux creates the same ServeMux as main(), wired to the given backend URL
// and apiURL config string.
func buildMux(backendURL *url.URL, apiURL string) *http.ServeMux {
	return buildMuxWithFiles(backendURL, apiURL, defaultMaxFileBytes, "")
}

// buildMuxWithFiles is the variant used by tests that exercise the
// /api/config file-upload knobs.
func buildMuxWithFiles(backendURL *url.URL, apiURL string, maxFileBytes int64, allowedMime string) *http.ServeMux {
	proxy := &httputil.ReverseProxy{
		Director: func(r *http.Request) {
			r.URL.Scheme = backendURL.Scheme
			r.URL.Host = backendURL.Host
			r.Host = backendURL.Host
		},
		FlushInterval: -1,
	}

	configPayload := map[string]any{
		"apiUrl":       apiURL,
		"maxFileBytes": maxFileBytes,
	}
	if allowedMime != "" {
		var list []string
		for _, raw := range strings.Split(allowedMime, ",") {
			if v := strings.TrimSpace(strings.ToLower(raw)); v != "" {
				list = append(list, v)
			}
		}
		if len(list) > 0 {
			configPayload["allowedMime"] = list
		}
	}

	mux := http.NewServeMux()

	mux.Handle("/v1/", proxy)

	mux.HandleFunc("GET /api/config", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(configPayload)
	})

	mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(`{"status":"ok"}`))
	})

	mux.Handle("/", http.FileServer(http.FS(static.Files())))

	return mux
}

// newTestServer creates a UI server backed by the given mock backend.
func newTestServer(t *testing.T, backend *httptest.Server) *httptest.Server {
	t.Helper()
	backendURL, err := url.Parse(backend.URL)
	if err != nil {
		t.Fatalf("parse backend URL: %v", err)
	}
	mux := buildMux(backendURL, backend.URL)
	return httptest.NewServer(mux)
}

// newTestServerNoBackend creates a UI server with a dummy backend URL (for
// tests that don't exercise the proxy).
func newTestServerNoBackend(t *testing.T, apiURL string) *httptest.Server {
	t.Helper()
	backendURL, _ := url.Parse(apiURL)
	mux := buildMux(backendURL, apiURL)
	return httptest.NewServer(mux)
}

func TestGetIndex(t *testing.T) {
	srv := newTestServerNoBackend(t, "http://localhost:8080")
	defer srv.Close()

	resp, err := http.Get(srv.URL + "/")
	if err != nil {
		t.Fatalf("GET /: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		t.Errorf("GET / status = %d, want %d", resp.StatusCode, http.StatusOK)
	}

	body, _ := io.ReadAll(resp.Body)
	if !strings.Contains(string(body), "<html") {
		t.Errorf("GET / body does not contain <html; got %d bytes", len(body))
	}
}

func TestGetStyleCSS(t *testing.T) {
	srv := newTestServerNoBackend(t, "http://localhost:8080")
	defer srv.Close()

	resp, err := http.Get(srv.URL + "/style.css")
	if err != nil {
		t.Fatalf("GET /style.css: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		t.Errorf("GET /style.css status = %d, want %d", resp.StatusCode, http.StatusOK)
	}

	body, _ := io.ReadAll(resp.Body)
	if !strings.Contains(string(body), ":root") {
		t.Errorf("GET /style.css does not look like CSS; first 100 bytes: %q", string(body[:min(100, len(body))]))
	}
}

func TestGetAppJS(t *testing.T) {
	srv := newTestServerNoBackend(t, "http://localhost:8080")
	defer srv.Close()

	resp, err := http.Get(srv.URL + "/app.js")
	if err != nil {
		t.Fatalf("GET /app.js: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		t.Errorf("GET /app.js status = %d, want %d", resp.StatusCode, http.StatusOK)
	}

	body, _ := io.ReadAll(resp.Body)
	if !strings.Contains(string(body), "use strict") {
		t.Errorf("GET /app.js does not look like JavaScript; first 100 bytes: %q", string(body[:min(100, len(body))]))
	}
}

func TestHealthz(t *testing.T) {
	srv := newTestServerNoBackend(t, "http://localhost:8080")
	defer srv.Close()

	resp, err := http.Get(srv.URL + "/healthz")
	if err != nil {
		t.Fatalf("GET /healthz: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		t.Errorf("GET /healthz status = %d, want %d", resp.StatusCode, http.StatusOK)
	}

	var result map[string]string
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		t.Fatalf("GET /healthz decode JSON: %v", err)
	}
	if result["status"] != "ok" {
		t.Errorf("GET /healthz status = %q, want %q", result["status"], "ok")
	}
}

func TestAPIConfig(t *testing.T) {
	const wantURL = "http://my-backend:9090"
	srv := newTestServerNoBackend(t, wantURL)
	defer srv.Close()

	resp, err := http.Get(srv.URL + "/api/config")
	if err != nil {
		t.Fatalf("GET /api/config: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		t.Errorf("GET /api/config status = %d, want %d", resp.StatusCode, http.StatusOK)
	}

	var result map[string]any
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		t.Fatalf("GET /api/config decode JSON: %v", err)
	}
	if result["apiUrl"] != wantURL {
		t.Errorf("GET /api/config apiUrl = %q, want %q", result["apiUrl"], wantURL)
	}
	// JSON numbers decode as float64. The default cap is 25 MiB.
	if got, want := result["maxFileBytes"].(float64), float64(defaultMaxFileBytes); got != want {
		t.Errorf("maxFileBytes = %v, want %v", got, want)
	}
	if _, ok := result["allowedMime"]; ok {
		t.Errorf("allowedMime should be omitted by default, got %v", result["allowedMime"])
	}
}

func TestAPIConfig_FileUploadOverrides(t *testing.T) {
	backendURL, _ := url.Parse("http://unused:9090")
	mux := buildMuxWithFiles(backendURL, "http://unused:9090", 5*1024*1024, "application/pdf, image/*")
	srv := httptest.NewServer(mux)
	defer srv.Close()

	resp, err := http.Get(srv.URL + "/api/config")
	if err != nil {
		t.Fatalf("GET /api/config: %v", err)
	}
	defer resp.Body.Close()

	var result map[string]any
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if got := result["maxFileBytes"].(float64); got != 5*1024*1024 {
		t.Errorf("maxFileBytes = %v, want 5 MiB", got)
	}
	mime, ok := result["allowedMime"].([]any)
	if !ok {
		t.Fatalf("allowedMime missing or wrong type: %v", result["allowedMime"])
	}
	if len(mime) != 2 || mime[0] != "application/pdf" || mime[1] != "image/*" {
		t.Errorf("allowedMime = %v, want [application/pdf image/*]", mime)
	}
}

func TestParseBytes(t *testing.T) {
	cases := []struct {
		in     string
		want   int64
		errOK  bool
		errSub string
	}{
		{"", defaultMaxFileBytes, false, ""},
		{"1024", 1024, false, ""},
		{"5k", 5 * 1024, false, ""},
		{"5KiB", 5 * 1024, false, ""},
		{"25m", 25 * 1024 * 1024, false, ""},
		{"  2 GiB  ", 2 * 1024 * 1024 * 1024, false, ""},
		{"0", 0, true, "positive"},
		{"-5", 0, true, "positive"},
		{"abc", 0, true, "invalid byte count"},
	}
	for _, tc := range cases {
		t.Run(tc.in, func(t *testing.T) {
			got, err := parseBytes(tc.in, defaultMaxFileBytes)
			if tc.errOK {
				if err == nil {
					t.Fatalf("parseBytes(%q): want error, got %d", tc.in, got)
				}
				if tc.errSub != "" && !strings.Contains(err.Error(), tc.errSub) {
					t.Errorf("parseBytes(%q): error %q, want substring %q", tc.in, err, tc.errSub)
				}
				return
			}
			if err != nil {
				t.Fatalf("parseBytes(%q): unexpected error: %v", tc.in, err)
			}
			if got != tc.want {
				t.Errorf("parseBytes(%q) = %d, want %d", tc.in, got, tc.want)
			}
		})
	}
}

func TestProxyChatCompletions(t *testing.T) {
	// Mock backend echoes back the request body with a fixed response.
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/v1/chat/completions" {
			t.Errorf("backend got path %q, want /v1/chat/completions", r.URL.Path)
		}
		if r.Method != http.MethodPost {
			t.Errorf("backend got method %q, want POST", r.Method)
		}

		body, _ := io.ReadAll(r.Body)
		if !strings.Contains(string(body), `"messages"`) {
			t.Errorf("backend body missing 'messages' field: %s", body)
		}

		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(`{"choices":[{"message":{"content":"hello"}}]}`))
	}))
	defer backend.Close()

	srv := newTestServer(t, backend)
	defer srv.Close()

	reqBody := `{"messages":[{"role":"user","content":"hi"}],"stream":false}`
	resp, err := http.Post(srv.URL+"/v1/chat/completions", "application/json", strings.NewReader(reqBody))
	if err != nil {
		t.Fatalf("POST /v1/chat/completions: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		t.Errorf("POST /v1/chat/completions status = %d, want %d", resp.StatusCode, http.StatusOK)
	}

	var result map[string]interface{}
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		t.Fatalf("decode proxy response: %v", err)
	}
	choices, ok := result["choices"].([]interface{})
	if !ok || len(choices) == 0 {
		t.Fatalf("proxy response missing choices: %v", result)
	}
}

func TestProxyStreaming(t *testing.T) {
	// Mock backend sends SSE events, then [DONE].
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		flusher, ok := w.(http.Flusher)
		if !ok {
			t.Fatal("backend ResponseWriter does not implement Flusher")
		}

		w.Header().Set("Content-Type", "text/event-stream")
		w.Header().Set("Cache-Control", "no-cache")
		w.Header().Set("Connection", "keep-alive")

		tokens := []string{"Hello", " world", "!"}
		for i, tok := range tokens {
			chunk := fmt.Sprintf(
				`{"choices":[{"delta":{"content":"%s"},"index":0,"finish_reason":null}]}`,
				tok,
			)
			fmt.Fprintf(w, "data: %s\n\n", chunk)
			flusher.Flush()
			_ = i
		}
		fmt.Fprintf(w, "data: [DONE]\n\n")
		flusher.Flush()
	}))
	defer backend.Close()

	srv := newTestServer(t, backend)
	defer srv.Close()

	reqBody := `{"messages":[{"role":"user","content":"hi"}],"stream":true}`
	resp, err := http.Post(srv.URL+"/v1/chat/completions", "application/json", strings.NewReader(reqBody))
	if err != nil {
		t.Fatalf("POST streaming: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		t.Errorf("POST streaming status = %d, want %d", resp.StatusCode, http.StatusOK)
	}

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		t.Fatalf("read streaming response: %v", err)
	}

	full := string(body)

	// Verify all SSE data lines came through.
	if !strings.Contains(full, "data:") {
		t.Errorf("streaming response missing SSE data lines; got %d bytes: %s", len(full), full)
	}

	// Verify each token arrived.
	for _, tok := range []string{"Hello", " world", "!"} {
		if !strings.Contains(full, tok) {
			t.Errorf("streaming response missing token %q", tok)
		}
	}

	// Verify the [DONE] sentinel came through.
	if !strings.Contains(full, "[DONE]") {
		t.Errorf("streaming response missing [DONE] sentinel")
	}
}

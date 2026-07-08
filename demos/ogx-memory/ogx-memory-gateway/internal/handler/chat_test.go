package handler_test

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/fips-agents/gateway-template/internal/handler"
)

// sampleCompletion is a minimal OpenAI-compatible chat completion response.
var sampleCompletion = map[string]any{
	"id":      "chatcmpl-abc123",
	"object":  "chat.completion",
	"created": 1700000000,
	"model":   "test-model",
	"choices": []map[string]any{
		{
			"index": 0,
			"message": map[string]string{
				"role":    "assistant",
				"content": "Hello!",
			},
			"finish_reason": "stop",
		},
	},
}

func TestChatHandler_SyncProxy(t *testing.T) {
	expected, _ := json.Marshal(sampleCompletion)

	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			t.Errorf("backend: want POST, got %s", r.Method)
		}
		if r.URL.Path != "/v1/chat/completions" {
			t.Errorf("backend: want path /v1/chat/completions, got %s", r.URL.Path)
		}

		// Verify the body was forwarded.
		body, _ := io.ReadAll(r.Body)
		var envelope struct {
			Stream bool `json:"stream"`
		}
		if err := json.Unmarshal(body, &envelope); err != nil {
			t.Errorf("backend: cannot parse forwarded body: %v", err)
		}
		if envelope.Stream {
			t.Errorf("backend: expected stream=false in forwarded body")
		}

		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		w.Write(expected)
	}))
	defer backend.Close()

	h := &handler.ChatHandler{
		BackendURL: backend.URL,
		Client:     backend.Client(),
	}

	reqBody := `{"model":"test-model","messages":[{"role":"user","content":"hi"}],"stream":false}`
	req := httptest.NewRequest(http.MethodPost, "/v1/chat/completions", strings.NewReader(reqBody))
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()

	h.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("sync proxy: want status %d, got %d (body: %s)", http.StatusOK, rec.Code, rec.Body.String())
	}

	ct := rec.Header().Get("Content-Type")
	if ct != "application/json" {
		t.Errorf("sync proxy: want Content-Type application/json, got %q", ct)
	}

	var got map[string]any
	if err := json.Unmarshal(rec.Body.Bytes(), &got); err != nil {
		t.Fatalf("sync proxy: response is not valid JSON: %v", err)
	}
	if got["id"] != "chatcmpl-abc123" {
		t.Errorf("sync proxy: want id=chatcmpl-abc123, got %v", got["id"])
	}
}

func TestChatHandler_StreamingProxy(t *testing.T) {
	// Build SSE chunks that the mock backend will emit.
	chunks := []string{
		`data: {"id":"chatcmpl-1","object":"chat.completion.chunk","choices":[{"delta":{"content":"Hel"},"index":0}]}`,
		`data: {"id":"chatcmpl-1","object":"chat.completion.chunk","choices":[{"delta":{"content":"lo!"},"index":0}]}`,
		`data: [DONE]`,
	}

	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/event-stream")
		w.WriteHeader(http.StatusOK)

		flusher, ok := w.(http.Flusher)
		if !ok {
			t.Fatal("backend: ResponseWriter does not implement Flusher")
		}

		for _, chunk := range chunks {
			fmt.Fprintf(w, "%s\n\n", chunk)
			flusher.Flush()
			time.Sleep(5 * time.Millisecond)
		}
	}))
	defer backend.Close()

	h := &handler.ChatHandler{
		BackendURL: backend.URL,
		Client:     backend.Client(),
	}

	reqBody := `{"model":"test-model","messages":[{"role":"user","content":"hi"}],"stream":true}`
	req := httptest.NewRequest(http.MethodPost, "/v1/chat/completions", strings.NewReader(reqBody))
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()

	h.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("streaming proxy: want status %d, got %d (body: %s)", http.StatusOK, rec.Code, rec.Body.String())
	}

	ct := rec.Header().Get("Content-Type")
	if ct != "text/event-stream" {
		t.Errorf("streaming proxy: want Content-Type text/event-stream, got %q", ct)
	}

	body := rec.Body.String()
	for _, chunk := range chunks {
		if !strings.Contains(body, chunk) {
			t.Errorf("streaming proxy: response missing expected chunk %q", chunk)
		}
	}
}

func TestChatHandler_BackendError(t *testing.T) {
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusInternalServerError)
		w.Write([]byte(`{"error":"internal backend error"}`))
	}))
	defer backend.Close()

	h := &handler.ChatHandler{
		BackendURL: backend.URL,
		Client:     backend.Client(),
	}

	reqBody := `{"model":"test-model","messages":[{"role":"user","content":"hi"}],"stream":false}`
	req := httptest.NewRequest(http.MethodPost, "/v1/chat/completions", strings.NewReader(reqBody))
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()

	h.ServeHTTP(rec, req)

	// The gateway should forward the backend's 500 status.
	if rec.Code != http.StatusInternalServerError {
		t.Fatalf("backend error: want status %d, got %d", http.StatusInternalServerError, rec.Code)
	}

	body := rec.Body.String()
	if !strings.Contains(body, "internal backend error") {
		t.Errorf("backend error: expected backend error message in response, got %q", body)
	}
}

func TestChatHandler_BackendUnreachable(t *testing.T) {
	// Closed server -- nothing listening.
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {}))
	closedURL := backend.URL
	backend.Close()

	h := &handler.ChatHandler{
		BackendURL: closedURL,
		Client:     &http.Client{},
	}

	reqBody := `{"model":"test-model","messages":[{"role":"user","content":"hi"}],"stream":false}`
	req := httptest.NewRequest(http.MethodPost, "/v1/chat/completions", strings.NewReader(reqBody))
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()

	h.ServeHTTP(rec, req)

	if rec.Code != http.StatusBadGateway {
		t.Fatalf("backend unreachable: want status %d, got %d", http.StatusBadGateway, rec.Code)
	}
}

func TestChatHandler_MethodNotAllowed(t *testing.T) {
	h := &handler.ChatHandler{
		BackendURL: "http://localhost:0",
		Client:     &http.Client{},
	}

	req := httptest.NewRequest(http.MethodGet, "/v1/chat/completions", nil)
	rec := httptest.NewRecorder()

	h.ServeHTTP(rec, req)

	if rec.Code != http.StatusMethodNotAllowed {
		t.Fatalf("method not allowed: want status %d, got %d", http.StatusMethodNotAllowed, rec.Code)
	}
}

func TestChatHandler_InvalidJSON(t *testing.T) {
	h := &handler.ChatHandler{
		BackendURL: "http://localhost:0",
		Client:     &http.Client{},
	}

	req := httptest.NewRequest(http.MethodPost, "/v1/chat/completions", strings.NewReader("not json"))
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()

	h.ServeHTTP(rec, req)

	if rec.Code != http.StatusBadRequest {
		t.Fatalf("invalid JSON: want status %d, got %d", http.StatusBadRequest, rec.Code)
	}
}

func TestChatHandler_PropagatesXTraceIdHeader(t *testing.T) {
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("X-Trace-Id", "trace_abcdef0123456789")
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		w.Write([]byte(`{"id":"chatcmpl-x"}`))
	}))
	defer backend.Close()

	h := &handler.ChatHandler{
		BackendURL: backend.URL,
		Client:     backend.Client(),
	}

	reqBody := `{"model":"m","messages":[{"role":"user","content":"hi"}],"stream":false}`
	req := httptest.NewRequest(http.MethodPost, "/v1/chat/completions", strings.NewReader(reqBody))
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()

	h.ServeHTTP(rec, req)

	if got := rec.Header().Get("X-Trace-Id"); got != "trace_abcdef0123456789" {
		t.Errorf("X-Trace-Id not propagated; got %q", got)
	}
}

func TestChatHandler_ForwardsCanonicalAuthHeaders(t *testing.T) {
	var captured http.Header

	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		captured = r.Header.Clone()
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		w.Write([]byte(`{"id":"chatcmpl-x"}`))
	}))
	defer backend.Close()

	h := &handler.ChatHandler{
		BackendURL: backend.URL,
		Client:     backend.Client(),
	}

	// The auth middleware would normally set these. Tests bypass the
	// middleware so we set them directly to assert forwarding.
	reqBody := `{"model":"m","messages":[{"role":"user","content":"hi"}],"stream":false}`
	req := httptest.NewRequest(http.MethodPost, "/v1/chat/completions", strings.NewReader(reqBody))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-Auth-Subject", "alice")
	req.Header.Set("X-Auth-User", "alice")
	req.Header.Set("X-Auth-Email", "alice@example.com")
	req.Header.Set("X-Auth-Mode", "proxy")
	rec := httptest.NewRecorder()

	h.ServeHTTP(rec, req)

	if got := captured.Get("X-Auth-Subject"); got != "alice" {
		t.Errorf("X-Auth-Subject not forwarded: got %q", got)
	}
	if got := captured.Get("X-Auth-User"); got != "alice" {
		t.Errorf("X-Auth-User not forwarded: got %q", got)
	}
	if got := captured.Get("X-Auth-Email"); got != "alice@example.com" {
		t.Errorf("X-Auth-Email not forwarded: got %q", got)
	}
	if got := captured.Get("X-Auth-Mode"); got != "proxy" {
		t.Errorf("X-Auth-Mode not forwarded: got %q", got)
	}
}

func TestChatHandler_ForwardsAuthorization(t *testing.T) {
	// In jwt mode with token exchange, the auth middleware replaces the
	// inbound user JWT with a downstream-audienced swapped token on the
	// request before the handler runs. The handler must forward that
	// Authorization header to the backend.
	var captured http.Header

	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		captured = r.Header.Clone()
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		w.Write([]byte(`{"id":"chatcmpl-x"}`))
	}))
	defer backend.Close()

	h := &handler.ChatHandler{
		BackendURL: backend.URL,
		Client:     backend.Client(),
	}

	reqBody := `{"model":"m","messages":[{"role":"user","content":"hi"}],"stream":false}`
	req := httptest.NewRequest(http.MethodPost, "/v1/chat/completions", strings.NewReader(reqBody))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer swapped-for-backend")
	rec := httptest.NewRecorder()

	h.ServeHTTP(rec, req)

	if got := captured.Get("Authorization"); got != "Bearer swapped-for-backend" {
		t.Errorf("Authorization not forwarded: got %q", got)
	}
}

func TestChatHandler_OmitsAuthorizationWhenAbsent(t *testing.T) {
	// When the auth middleware strips Authorization (no swap configured,
	// anonymous mode, etc.), the handler must not invent one or forward
	// anything. The backend should receive no Authorization header.
	var captured http.Header

	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		captured = r.Header.Clone()
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		w.Write([]byte(`{"id":"chatcmpl-x"}`))
	}))
	defer backend.Close()

	h := &handler.ChatHandler{
		BackendURL: backend.URL,
		Client:     backend.Client(),
	}

	reqBody := `{"model":"m","messages":[{"role":"user","content":"hi"}],"stream":false}`
	req := httptest.NewRequest(http.MethodPost, "/v1/chat/completions", strings.NewReader(reqBody))
	req.Header.Set("Content-Type", "application/json")
	// No Authorization on inbound — simulates middleware having stripped it.
	rec := httptest.NewRecorder()

	h.ServeHTTP(rec, req)

	if got := captured.Get("Authorization"); got != "" {
		t.Errorf("Authorization should be absent on backend request, got %q", got)
	}
}

func TestChatHandler_ForwardsTraceparent(t *testing.T) {
	// W3C Trace Context (traceparent / tracestate) flows end-to-end so the
	// gateway is a transparent hop for distributed traces. Without this
	// the chain breaks at the gateway and any OTEL backend shows two
	// disconnected traces per request.
	var captured http.Header

	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		captured = r.Header.Clone()
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		w.Write([]byte(`{"id":"chatcmpl-x"}`))
	}))
	defer backend.Close()

	h := &handler.ChatHandler{
		BackendURL: backend.URL,
		Client:     backend.Client(),
	}

	reqBody := `{"model":"m","messages":[{"role":"user","content":"hi"}],"stream":false}`
	req := httptest.NewRequest(http.MethodPost, "/v1/chat/completions", strings.NewReader(reqBody))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Traceparent", "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01")
	req.Header.Set("Tracestate", "vendor=opaque-state")
	rec := httptest.NewRecorder()

	h.ServeHTTP(rec, req)

	if got := captured.Get("Traceparent"); got != "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01" {
		t.Errorf("Traceparent not forwarded: got %q", got)
	}
	if got := captured.Get("Tracestate"); got != "vendor=opaque-state" {
		t.Errorf("Tracestate not forwarded: got %q", got)
	}
}

// TestChatHandler_ForwardsBodyVerbatim pins the transparent-passthrough
// contract: the gateway must forward the request body byte-for-byte to the
// backend, with no field stripping, reordering, or re-marshalling. This
// keeps OpenAI content-block messages (text + image_url, future input_audio,
// etc.) and any newer fields the upstream agent understands flowing through
// without the gateway needing schema-level awareness.
//
// Concretely: messages[].content as an array of content blocks — the shape
// shipped in fipsagents 0.20.0 for vision — must arrive at the backend
// unchanged, including file_id:<id> URLs that the agent rewrites server-side.
func TestChatHandler_ForwardsBodyVerbatim(t *testing.T) {
	cases := []struct {
		name string
		body string
	}{
		{
			name: "image_url content block with file_id URL",
			body: `{"model":"granite-vision","messages":[{"role":"user","content":[{"type":"text","text":"What color is this?"},{"type":"image_url","image_url":{"url":"file_id:abc123"}}]}],"stream":false}`,
		},
		{
			name: "image_url content block with data URL",
			body: `{"model":"granite-vision","messages":[{"role":"user","content":[{"type":"text","text":"Describe"},{"type":"image_url","image_url":{"url":"data:image/png;base64,iVBORw0KGgo="}}]}],"stream":false}`,
		},
		{
			name: "image_url content block with https URL",
			body: `{"model":"granite-vision","messages":[{"role":"user","content":[{"type":"image_url","image_url":{"url":"https://example.com/cat.jpg"}}]}],"stream":false}`,
		},
		{
			name: "future content-block type the gateway has never heard of",
			body: `{"model":"m","messages":[{"role":"user","content":[{"type":"input_audio","input_audio":{"data":"…","format":"wav"}}]}],"stream":false}`,
		},
		{
			name: "streaming request with image_url block",
			body: `{"model":"granite-vision","messages":[{"role":"user","content":[{"type":"text","text":"hi"},{"type":"image_url","image_url":{"url":"file_id:xyz"}}]}],"stream":true}`,
		},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			var captured []byte

			backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				b, err := io.ReadAll(r.Body)
				if err != nil {
					t.Fatalf("backend: read body: %v", err)
				}
				captured = b
				w.Header().Set("Content-Type", "application/json")
				w.WriteHeader(http.StatusOK)
				w.Write([]byte(`{"id":"chatcmpl-x"}`))
			}))
			defer backend.Close()

			h := &handler.ChatHandler{
				BackendURL: backend.URL,
				Client:     backend.Client(),
			}

			req := httptest.NewRequest(http.MethodPost, "/v1/chat/completions", strings.NewReader(tc.body))
			req.Header.Set("Content-Type", "application/json")
			rec := httptest.NewRecorder()

			h.ServeHTTP(rec, req)

			if string(captured) != tc.body {
				t.Errorf("body not forwarded verbatim\n  want: %s\n  got:  %s", tc.body, string(captured))
			}
		})
	}
}

func TestChatHandler_StreamingBackendError(t *testing.T) {
	// Backend returns 500 on a streaming request -- gateway should forward the
	// error status rather than switching to SSE mode.
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusInternalServerError)
		w.Write([]byte(`{"error":"model overloaded"}`))
	}))
	defer backend.Close()

	h := &handler.ChatHandler{
		BackendURL: backend.URL,
		Client:     backend.Client(),
	}

	reqBody := `{"model":"test-model","messages":[{"role":"user","content":"hi"}],"stream":true}`
	req := httptest.NewRequest(http.MethodPost, "/v1/chat/completions", strings.NewReader(reqBody))
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()

	h.ServeHTTP(rec, req)

	if rec.Code != http.StatusInternalServerError {
		t.Fatalf("streaming backend error: want status %d, got %d", http.StatusInternalServerError, rec.Code)
	}

	ct := rec.Header().Get("Content-Type")
	if ct != "application/json" {
		t.Errorf("streaming backend error: want Content-Type application/json, got %q", ct)
	}
}

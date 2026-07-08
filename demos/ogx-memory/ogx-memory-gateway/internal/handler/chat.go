package handler

import (
	"bytes"
	"encoding/json"
	"io"
	"log/slog"
	"net/http"

	"github.com/fips-agents/gateway-template/internal/proxy"
)

// ChatHandler proxies OpenAI-compatible /v1/chat/completions requests to a
// backend agent service. It supports both synchronous and streaming modes.
type ChatHandler struct {
	BackendURL string
	Client     *http.Client
}

// ServeHTTP dispatches the request to either streaming or synchronous proxy
// based on the "stream" field in the JSON body.
func (h *ChatHandler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, `{"error":"method not allowed"}`, http.StatusMethodNotAllowed)
		return
	}

	body, err := io.ReadAll(r.Body)
	if err != nil {
		slog.Error("failed to read request body", "error", err)
		http.Error(w, `{"error":"failed to read request body"}`, http.StatusBadRequest)
		return
	}
	defer r.Body.Close()

	// Peek at the "stream" field to decide the proxy mode.
	var envelope struct {
		Stream bool `json:"stream"`
	}
	if err := json.Unmarshal(body, &envelope); err != nil {
		slog.Warn("failed to parse request JSON", "error", err)
		http.Error(w, `{"error":"invalid JSON body"}`, http.StatusBadRequest)
		return
	}

	if envelope.Stream {
		h.proxyStreaming(w, r, body)
	} else {
		h.proxySync(w, r, body)
	}
}

// passThroughHeaders are response headers copied from the backend to the
// client. The list is deliberately narrow — keep the gateway thin and
// avoid leaking internal headers.
var passThroughHeaders = []string{
	"X-Trace-Id",
}

// copyPassThroughHeaders copies the allowlisted headers from src to dst.
func copyPassThroughHeaders(dst http.Header, src http.Header) {
	for _, name := range passThroughHeaders {
		if v := src.Get(name); v != "" {
			dst.Set(name, v)
		}
	}
}

// proxySync forwards the request and returns the full backend response.
func (h *ChatHandler) proxySync(w http.ResponseWriter, r *http.Request, body []byte) {
	resp, err := h.doBackendRequest(r, body)
	if err != nil {
		slog.Error("backend request failed", "error", err)
		http.Error(w, `{"error":"backend request failed"}`, http.StatusBadGateway)
		return
	}
	defer resp.Body.Close()

	w.Header().Set("Content-Type", "application/json")
	copyPassThroughHeaders(w.Header(), resp.Header)
	w.WriteHeader(resp.StatusCode)
	if _, err := io.Copy(w, resp.Body); err != nil {
		slog.Warn("error copying backend response", "error", err)
	}
}

// proxyStreaming connects to the backend with streaming enabled and relays
// SSE chunks to the client.
func (h *ChatHandler) proxyStreaming(w http.ResponseWriter, r *http.Request, body []byte) {
	resp, err := h.doBackendRequest(r, body)
	if err != nil {
		slog.Error("backend streaming request failed", "error", err)
		http.Error(w, `{"error":"backend request failed"}`, http.StatusBadGateway)
		return
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		w.Header().Set("Content-Type", "application/json")
		copyPassThroughHeaders(w.Header(), resp.Header)
		w.WriteHeader(resp.StatusCode)
		io.Copy(w, resp.Body)
		return
	}

	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("Connection", "keep-alive")
	w.Header().Set("X-Accel-Buffering", "no")
	copyPassThroughHeaders(w.Header(), resp.Header)

	proxy.RelaySSE(resp, w)
}

// forwardedAuthHeaders are the auth-related headers projected by the auth
// middleware and forwarded to the backend agent.
//
// Authorization is included so jwt-mode token-exchange (RFC 8693) works:
// the middleware replaces the inbound user JWT with a downstream-audienced
// swapped token (Identity.BearerToken) before the handler runs, or strips
// Authorization entirely when no swap is configured. We never forward the
// raw inbound user JWT.
var forwardedAuthHeaders = []string{
	"X-Auth-Subject",
	"X-Auth-User",
	"X-Auth-Email",
	"X-Auth-Mode",
	"Authorization",
}

// doBackendRequest sends the request body to the backend's chat completions
// endpoint, forwarding the canonical X-Auth-* headers from the inbound
// request so the agent can attribute the call to the resolved identity.
func (h *ChatHandler) doBackendRequest(r *http.Request, body []byte) (*http.Response, error) {
	url := h.BackendURL + "/v1/chat/completions"
	req, err := http.NewRequest(http.MethodPost, url, bytes.NewReader(body))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/json")
	for _, name := range forwardedAuthHeaders {
		if v := r.Header.Get(name); v != "" {
			req.Header.Set(name, v)
		}
	}
	copyPropagationHeaders(req.Header, r.Header)

	return h.Client.Do(req)
}

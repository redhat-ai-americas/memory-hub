package handler

import (
	"bytes"
	"io"
	"log/slog"
	"net/http"
)

// authHeaders are the auth-related headers forwarded to the backend so it
// can attribute feedback to the calling user. The auth middleware populates
// these from the resolved Identity; inbound spoofed copies are stripped
// before any handler runs. Other headers are dropped.
//
// Authorization is included so jwt-mode token-exchange (RFC 8693) works:
// the middleware replaces the inbound user JWT with a downstream-audienced
// swapped token before the handler runs, or strips Authorization when no
// swap is configured. We never forward the raw inbound user JWT.
var authHeaders = []string{
	"X-Auth-Subject",
	"X-Auth-User",
	"X-Auth-Email",
	"X-Auth-Mode",
	"Authorization",
}

// FeedbackHandler proxies user feedback API requests to the backend agent
// service. It supports POST and GET on /v1/feedback. The companion
// FeedbackStatsHandler covers /v1/feedback/stats.
//
// The gateway does not interpret or store feedback payloads; it forwards
// the body and query string verbatim, with selected authentication headers
// preserved so the backend can attribute the record to the correct user.
type FeedbackHandler struct {
	BackendURL string
	Client     *http.Client
}

// ServeHTTP dispatches POST and GET to the backend, returning 405 for any
// other method.
func (h *FeedbackHandler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	switch r.Method {
	case http.MethodPost, http.MethodGet:
		proxyPassthrough(w, r, h.Client, h.BackendURL+"/v1/feedback")
	default:
		http.Error(w, `{"error":"method not allowed"}`, http.StatusMethodNotAllowed)
	}
}

// FeedbackByIdHandler proxies PATCH /v1/feedback/{feedback_id} to the
// backend.  Registered separately from FeedbackHandler because Go's
// http.ServeMux treats `/v1/feedback` and `/v1/feedback/<id>` as distinct
// patterns.  Wired in main.go via the Go 1.22 pattern syntax.
type FeedbackByIdHandler struct {
	BackendURL string
	Client     *http.Client
}

func (h *FeedbackByIdHandler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPatch {
		http.Error(w, `{"error":"method not allowed"}`, http.StatusMethodNotAllowed)
		return
	}
	id := r.PathValue("feedback_id")
	if id == "" {
		http.Error(w, `{"error":"feedback_id required"}`, http.StatusBadRequest)
		return
	}
	proxyPassthrough(w, r, h.Client, h.BackendURL+"/v1/feedback/"+id)
}

// FeedbackStatsHandler proxies GET /v1/feedback/stats to the backend.
type FeedbackStatsHandler struct {
	BackendURL string
	Client     *http.Client
}

func (h *FeedbackStatsHandler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, `{"error":"method not allowed"}`, http.StatusMethodNotAllowed)
		return
	}
	proxyPassthrough(w, r, h.Client, h.BackendURL+"/v1/feedback/stats")
}

// proxyPassthrough forwards a request to backendURL, preserving method,
// query string, body, Content-Type, and selected auth headers. The backend
// response (status, Content-Type, body) is copied to w.
func proxyPassthrough(w http.ResponseWriter, r *http.Request, client *http.Client, backendURL string) {
	var body io.Reader
	if r.Method == http.MethodPost || r.Method == http.MethodPatch || r.Method == http.MethodPut {
		raw, err := io.ReadAll(r.Body)
		if err != nil {
			slog.Error("failed to read request body", "error", err)
			http.Error(w, `{"error":"failed to read request body"}`, http.StatusBadRequest)
			return
		}
		defer r.Body.Close()
		body = bytes.NewReader(raw)
	}

	url := backendURL
	if r.URL.RawQuery != "" {
		url = url + "?" + r.URL.RawQuery
	}

	req, err := http.NewRequestWithContext(r.Context(), r.Method, url, body)
	if err != nil {
		slog.Error("failed to build backend request", "error", err)
		http.Error(w, `{"error":"failed to build backend request"}`, http.StatusInternalServerError)
		return
	}

	if ct := r.Header.Get("Content-Type"); ct != "" {
		req.Header.Set("Content-Type", ct)
	} else if r.Method == http.MethodPost || r.Method == http.MethodPatch || r.Method == http.MethodPut {
		req.Header.Set("Content-Type", "application/json")
	}
	for _, name := range authHeaders {
		if v := r.Header.Get(name); v != "" {
			req.Header.Set(name, v)
		}
	}
	copyPropagationHeaders(req.Header, r.Header)

	resp, err := client.Do(req)
	if err != nil {
		slog.Error("backend request failed", "error", err, "url", backendURL)
		http.Error(w, `{"error":"backend request failed"}`, http.StatusBadGateway)
		return
	}
	defer resp.Body.Close()

	if ct := resp.Header.Get("Content-Type"); ct != "" {
		w.Header().Set("Content-Type", ct)
	} else {
		w.Header().Set("Content-Type", "application/json")
	}
	copyPassThroughHeaders(w.Header(), resp.Header)
	w.WriteHeader(resp.StatusCode)
	if _, err := io.Copy(w, resp.Body); err != nil {
		slog.Warn("error copying backend response", "error", err)
	}
}

package handler

import (
	"log/slog"
	"net/http"
	"time"
)

// HealthHandler returns a simple liveness check.
type HealthHandler struct{}

func (h *HealthHandler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	w.Write([]byte(`{"status":"ok"}`))
}

// ReadyHandler checks whether the backend is reachable before reporting ready.
type ReadyHandler struct {
	BackendURL string
	Client     *http.Client
}

func (h *ReadyHandler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	ctx := r.Context()

	client := h.Client
	if client == nil {
		client = &http.Client{Timeout: 3 * time.Second}
	}

	req, err := http.NewRequestWithContext(ctx, http.MethodHead, h.BackendURL+"/healthz", nil)
	if err != nil {
		slog.Warn("readiness check: failed to create request", "error", err)
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusServiceUnavailable)
		w.Write([]byte(`{"status":"not ready","reason":"bad backend url"}`))
		return
	}

	resp, err := client.Do(req)
	if err != nil {
		slog.Warn("readiness check: backend unreachable", "error", err)
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusServiceUnavailable)
		w.Write([]byte(`{"status":"not ready","reason":"backend unreachable"}`))
		return
	}
	resp.Body.Close()

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	w.Write([]byte(`{"status":"ok"}`))
}

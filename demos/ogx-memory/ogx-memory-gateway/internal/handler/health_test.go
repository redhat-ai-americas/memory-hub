package handler_test

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/fips-agents/gateway-template/internal/handler"
)

func TestHealthHandler(t *testing.T) {
	h := &handler.HealthHandler{}

	req := httptest.NewRequest(http.MethodGet, "/healthz", nil)
	rec := httptest.NewRecorder()

	h.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("GET /healthz: want status %d, got %d", http.StatusOK, rec.Code)
	}

	ct := rec.Header().Get("Content-Type")
	if ct != "application/json" {
		t.Errorf("GET /healthz: want Content-Type application/json, got %q", ct)
	}

	var body map[string]string
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("GET /healthz: response is not valid JSON: %v", err)
	}
	if body["status"] != "ok" {
		t.Errorf("GET /healthz: want status=ok, got status=%q", body["status"])
	}
}

func TestReadyHandler_BackendReachable(t *testing.T) {
	// Spin up a mock backend that responds to HEAD /healthz.
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodHead {
			t.Errorf("readiness probe: want HEAD, got %s", r.Method)
		}
		w.WriteHeader(http.StatusOK)
	}))
	defer backend.Close()

	h := &handler.ReadyHandler{
		BackendURL: backend.URL,
		Client:     backend.Client(),
	}

	req := httptest.NewRequest(http.MethodGet, "/readyz", nil)
	rec := httptest.NewRecorder()

	h.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("GET /readyz (backend up): want status %d, got %d", http.StatusOK, rec.Code)
	}

	var body map[string]string
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("GET /readyz: response is not valid JSON: %v", err)
	}
	if body["status"] != "ok" {
		t.Errorf("GET /readyz: want status=ok, got status=%q", body["status"])
	}
}

func TestReadyHandler_BackendUnreachable(t *testing.T) {
	// Point at a server that was started and immediately closed, so the URL
	// is well-formed but nobody is listening.
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {}))
	closedURL := backend.URL
	backend.Close()

	h := &handler.ReadyHandler{
		BackendURL: closedURL,
		Client:     &http.Client{},
	}

	req := httptest.NewRequest(http.MethodGet, "/readyz", nil)
	rec := httptest.NewRecorder()

	h.ServeHTTP(rec, req)

	if rec.Code != http.StatusServiceUnavailable {
		t.Fatalf("GET /readyz (backend down): want status %d, got %d",
			http.StatusServiceUnavailable, rec.Code)
	}

	var body map[string]string
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("GET /readyz: response is not valid JSON: %v", err)
	}
	if body["status"] != "not ready" {
		t.Errorf("GET /readyz: want status=\"not ready\", got status=%q", body["status"])
	}
}

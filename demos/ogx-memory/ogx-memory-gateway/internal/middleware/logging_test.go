package middleware_test

import (
	"bytes"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"

	"github.com/fips-agents/gateway-template/internal/middleware"
)

// restoreDefaultLogger resets slog to a safe default that writes to stderr.
// Use as: defer restoreDefaultLogger()
func restoreDefaultLogger() {
	slog.SetDefault(slog.New(slog.NewJSONHandler(os.Stderr, nil)))
}

// dummyHandler writes a known body so we can verify the middleware calls through.
var dummyHandler = http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
	w.WriteHeader(http.StatusOK)
	w.Write([]byte("hello"))
})

func TestLogRequests_CallsNextHandler(t *testing.T) {
	called := false
	inner := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		called = true
		w.WriteHeader(http.StatusOK)
	})

	handler := middleware.LogRequests(inner)
	req := httptest.NewRequest(http.MethodGet, "/v1/chat/completions", nil)
	rec := httptest.NewRecorder()

	handler.ServeHTTP(rec, req)

	if !called {
		t.Fatal("middleware did not call the next handler")
	}
	if rec.Code != http.StatusOK {
		t.Errorf("want status %d, got %d", http.StatusOK, rec.Code)
	}
}

func TestLogRequests_SkipsHealthProbes(t *testing.T) {
	paths := []string{"/healthz", "/readyz"}

	for _, path := range paths {
		t.Run(path, func(t *testing.T) {
			var buf bytes.Buffer
			logger := slog.New(slog.NewJSONHandler(&buf, nil))
			slog.SetDefault(logger)
			defer restoreDefaultLogger()

			handler := middleware.LogRequests(dummyHandler)
			req := httptest.NewRequest(http.MethodGet, path, nil)
			rec := httptest.NewRecorder()

			handler.ServeHTTP(rec, req)

			// The handler should still be called (probe must succeed).
			if rec.Code != http.StatusOK {
				t.Errorf("want status %d, got %d", http.StatusOK, rec.Code)
			}

			// But no "request" log line should be emitted.
			if strings.Contains(buf.String(), `"msg":"request"`) {
				t.Error("health probe path should not produce a request log entry")
			}
		})
	}
}

func TestLogRequests_LogsRequestFields(t *testing.T) {
	var buf bytes.Buffer
	logger := slog.New(slog.NewJSONHandler(&buf, nil))
	slog.SetDefault(logger)
	defer restoreDefaultLogger()

	handler := middleware.LogRequests(dummyHandler)
	req := httptest.NewRequest(http.MethodPost, "/v1/chat/completions", nil)
	rec := httptest.NewRecorder()

	handler.ServeHTTP(rec, req)

	logOutput := buf.String()

	for _, want := range []string{`"msg":"request"`, `"method":"POST"`, `"path":"/v1/chat/completions"`, `"status":200`} {
		if !strings.Contains(logOutput, want) {
			t.Errorf("log output missing %s\ngot: %s", want, logOutput)
		}
	}
}

func TestStatusWriter_CapturesStatusAndBytes(t *testing.T) {
	inner := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusCreated)
		w.Write([]byte("created"))
	})

	handler := middleware.LogRequests(inner)
	req := httptest.NewRequest(http.MethodPost, "/test", nil)
	rec := httptest.NewRecorder()

	var buf bytes.Buffer
	logger := slog.New(slog.NewJSONHandler(&buf, nil))
	slog.SetDefault(logger)
	defer restoreDefaultLogger()

	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusCreated {
		t.Errorf("want status %d, got %d", http.StatusCreated, rec.Code)
	}
	if rec.Body.String() != "created" {
		t.Errorf("want body %q, got %q", "created", rec.Body.String())
	}

	logOutput := buf.String()
	if !strings.Contains(logOutput, `"status":201`) {
		t.Errorf("log should contain status 201, got: %s", logOutput)
	}
	if !strings.Contains(logOutput, `"bytes":7`) {
		t.Errorf("log should contain bytes=7, got: %s", logOutput)
	}
}

func TestStatusWriter_DefaultsToOKWhenWriteCalledWithoutWriteHeader(t *testing.T) {
	inner := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// No explicit WriteHeader call — Go defaults to 200.
		w.Write([]byte("ok"))
	})

	var buf bytes.Buffer
	logger := slog.New(slog.NewJSONHandler(&buf, nil))
	slog.SetDefault(logger)
	defer restoreDefaultLogger()

	handler := middleware.LogRequests(inner)
	req := httptest.NewRequest(http.MethodGet, "/test", nil)
	rec := httptest.NewRecorder()

	handler.ServeHTTP(rec, req)

	logOutput := buf.String()
	if !strings.Contains(logOutput, `"status":200`) {
		t.Errorf("log should contain status 200 when WriteHeader not called, got: %s", logOutput)
	}
}

func TestStatusWriter_ImplementsFlusher(t *testing.T) {
	var buf bytes.Buffer
	slog.SetDefault(slog.New(slog.NewJSONHandler(&buf, nil)))
	defer restoreDefaultLogger()

	// httptest.ResponseRecorder implements http.Flusher, so the statusWriter
	// wrapping it should delegate Flush successfully without panic.
	inner := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		w.Write([]byte("event: data\n\n"))
		if f, ok := w.(http.Flusher); ok {
			f.Flush()
		} else {
			t.Error("statusWriter should implement http.Flusher")
		}
	})

	handler := middleware.LogRequests(inner)
	req := httptest.NewRequest(http.MethodGet, "/stream", nil)
	rec := httptest.NewRecorder()

	handler.ServeHTTP(rec, req)

	if rec.Flushed != true {
		t.Error("Flush should have been called on the underlying ResponseRecorder")
	}
}

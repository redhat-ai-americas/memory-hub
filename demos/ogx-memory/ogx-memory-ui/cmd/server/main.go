package main

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"net/http"
	"net/http/httputil"
	"net/url"
	"os"
	"os/signal"
	"strconv"
	"strings"
	"syscall"
	"time"

	"github.com/fips-agents/ui-template/static"
)

// defaultMaxFileBytes mirrors the gateway's GATEWAY_FILES_MAX_BYTES
// default (25 MiB). The UI uses this to short-circuit obviously
// oversized files before the network sees them, but the gateway is the
// authoritative cap.
const defaultMaxFileBytes int64 = 25 * 1024 * 1024

func main() {
	port := os.Getenv("PORT")
	if port == "" {
		port = "3000"
	}

	apiURL := os.Getenv("API_URL")
	if apiURL == "" {
		apiURL = "http://localhost:8080"
		slog.Warn("API_URL not set, using default", "url", apiURL)
	}

	maxFileBytes, err := parseBytes(os.Getenv("UI_MAX_FILE_BYTES"), defaultMaxFileBytes)
	if err != nil {
		slog.Error("invalid UI_MAX_FILE_BYTES", "error", err)
		os.Exit(1)
	}
	allowedMime := strings.TrimSpace(os.Getenv("UI_ALLOWED_MIME"))

	backendURL, err := url.Parse(apiURL)
	if err != nil {
		slog.Error("invalid API_URL", "url", apiURL, "error", err)
		os.Exit(1)
	}

	configPayload := map[string]any{
		"apiUrl":       apiURL,
		"maxFileBytes": maxFileBytes,
	}
	if allowedMime != "" {
		// Comma-separated list, normalised so the JS can compare
		// case-insensitively without re-parsing.
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

	proxy := &httputil.ReverseProxy{
		Director: func(r *http.Request) {
			r.URL.Scheme = backendURL.Scheme
			r.URL.Host = backendURL.Host
			r.Host = backendURL.Host
		},
		FlushInterval: -1, // flush immediately for SSE streaming
	}

	mux := http.NewServeMux()

	// Reverse proxy: browser -> UI server -> backend (no CORS needed)
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

	srv := &http.Server{
		Addr:         ":" + port,
		Handler:      mux,
		ReadTimeout:  10 * time.Second,
		WriteTimeout: 5 * time.Minute, // SSE streams can run long
		IdleTimeout:  60 * time.Second,
	}

	done := make(chan os.Signal, 1)
	signal.Notify(done, os.Interrupt, syscall.SIGTERM)

	go func() {
		slog.Info("starting server",
			"port", port,
			"api_url", apiURL,
			"max_file_bytes", maxFileBytes,
			"allowed_mime", allowedMime,
		)
		if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			slog.Error("server failed", "error", err)
			os.Exit(1)
		}
	}()

	<-done
	slog.Info("shutting down")

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	if err := srv.Shutdown(ctx); err != nil {
		slog.Error("shutdown failed", "error", err)
		os.Exit(1)
	}
	slog.Info("server stopped")
}

// parseBytes parses a byte-count string with optional k/m/g (binary)
// suffix. Empty string returns the fallback. Mirrors gateway-template's
// envBytesDefault so deployments can use the same value verbatim.
func parseBytes(raw string, fallback int64) (int64, error) {
	s := strings.TrimSpace(strings.ToLower(raw))
	if s == "" {
		return fallback, nil
	}
	mult := int64(1)
	for _, suf := range []struct {
		s string
		m int64
	}{
		{"gib", 1 << 30}, {"gb", 1 << 30}, {"g", 1 << 30},
		{"mib", 1 << 20}, {"mb", 1 << 20}, {"m", 1 << 20},
		{"kib", 1 << 10}, {"kb", 1 << 10}, {"k", 1 << 10},
	} {
		if strings.HasSuffix(s, suf.s) {
			mult = suf.m
			s = strings.TrimSuffix(s, suf.s)
			break
		}
	}
	n, err := strconv.ParseInt(strings.TrimSpace(s), 10, 64)
	if err != nil {
		return 0, fmt.Errorf("invalid byte count %q: %w", raw, err)
	}
	if n <= 0 {
		return 0, fmt.Errorf("byte count must be positive, got %q", raw)
	}
	return n * mult, nil
}

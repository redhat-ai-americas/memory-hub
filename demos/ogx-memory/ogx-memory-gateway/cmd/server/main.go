package main

import (
	"context"
	"io"
	"log/slog"
	"net"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/fips-agents/gateway-template/internal/auth"
	"github.com/fips-agents/gateway-template/internal/config"
	"github.com/fips-agents/gateway-template/internal/handler"
	"github.com/fips-agents/gateway-template/internal/middleware"
)

func main() {
	slog.SetDefault(slog.New(slog.NewJSONHandler(os.Stdout, nil)))

	cfg, err := config.Load()
	if err != nil {
		slog.Error("configuration error", "error", err)
		os.Exit(1)
	}

	var exchanger *auth.TokenExchanger
	if cfg.JWTExchangeEnabled() {
		exchanger, err = auth.NewTokenExchanger(auth.TokenExchangeConfig{
			TokenURL:     cfg.AuthJWTExchangeURL,
			ClientID:     cfg.AuthJWTExchangeClientID,
			ClientSecret: cfg.AuthJWTExchangeClientSecret,
			Audience:     cfg.AuthJWTExchangeAudience,
			Scope:        cfg.AuthJWTExchangeScope,
		})
		if err != nil {
			slog.Error("token exchange configuration error", "error", err)
			os.Exit(1)
		}
	}

	authenticator, err := auth.New(cfg.AuthMode, auth.Options{
		ProxyUserHeader:  cfg.AuthProxyUserHeader,
		ProxyEmailHeader: cfg.AuthProxyEmailHeader,
		JWT: auth.JWTConfig{
			JWKSURL:              cfg.AuthJWTJWKSURL,
			Issuer:               cfg.AuthJWTIssuer,
			Audience:             cfg.AuthJWTAudience,
			SubjectClaim:         cfg.AuthJWTSubjectClaim,
			UserClaim:            cfg.AuthJWTUserClaim,
			EmailClaim:           cfg.AuthJWTEmailClaim,
			JWKSRefreshRateLimit: cfg.AuthJWTJWKSRefreshRateLimit,
		},
		JWTExchanger: exchanger,
	})
	if err != nil {
		slog.Error("auth configuration error", "error", err)
		os.Exit(1)
	}

	client := &http.Client{Timeout: 120 * time.Second}

	mux := http.NewServeMux()
	mux.Handle("/v1/chat/completions", &handler.ChatHandler{
		BackendURL: cfg.BackendURL,
		Client:     client,
	})
	feedbackTarget := cfg.FeedbackTargetURL()
	feedbackHandler := &handler.FeedbackHandler{BackendURL: feedbackTarget, Client: client}
	mux.Handle("POST /v1/feedback", feedbackHandler)
	mux.Handle("GET /v1/feedback", feedbackHandler)
	mux.Handle("GET /v1/feedback/stats", &handler.FeedbackStatsHandler{
		BackendURL: feedbackTarget,
		Client:     client,
	})
	mux.Handle("PATCH /v1/feedback/{feedback_id}", &handler.FeedbackByIdHandler{
		BackendURL: feedbackTarget,
		Client:     client,
	})

	// /v1/sessions/* and /v1/traces/* are platform-routable. When
	// PLATFORM_URL is unset they proxy to the backend agent (preserving
	// existing behavior for deployments that haven't adopted a sibling
	// fipsagents-platform).  GET /v1/sessions/{id}/usage is carved out
	// to always go to the agent because /usage layers PricingConfig
	// over cost_data — it's an agent capability, not a platform one.
	sessionsForward, err := handler.NewForwardingHandler(cfg.SessionsTargetURL())
	if err != nil {
		slog.Error("sessions forward configuration error", "error", err)
		os.Exit(1)
	}
	tracesForward, err := handler.NewForwardingHandler(cfg.TracesTargetURL())
	if err != nil {
		slog.Error("traces forward configuration error", "error", err)
		os.Exit(1)
	}
	usageForward, err := handler.NewForwardingHandler(cfg.BackendURL)
	if err != nil {
		slog.Error("usage forward configuration error", "error", err)
		os.Exit(1)
	}
	// Go 1.22 mux: the more specific pattern wins, so this carve-out
	// runs even though /v1/sessions/ catches everything else.
	mux.Handle("GET /v1/sessions/{session_id}/usage", usageForward)
	mux.Handle("/v1/sessions/", sessionsForward)
	mux.Handle("/v1/traces/", tracesForward)

	// /v1/files: streaming multipart proxy on POST, opaque pass-through
	// on GET/DELETE. The upload path enforces a size cap and MIME
	// allowlist before forwarding; metadata operations don't need
	// special handling. Files are always agent-routed (no platform
	// equivalent today; see agent-template#100).
	filesForward, err := handler.NewForwardingHandler(cfg.BackendURL)
	if err != nil {
		slog.Error("files forward configuration error", "error", err)
		os.Exit(1)
	}
	mux.Handle("POST /v1/files", &handler.FilesUploadHandler{
		BackendURL: cfg.BackendURL,
		MaxBytes:   cfg.FilesMaxBytes,
		Cfg:        cfg,
		Timeout:    cfg.FilesUploadTimeout,
		Client:     &http.Client{},
	})
	mux.Handle("GET /v1/files", filesForward)
	mux.Handle("/v1/files/", filesForward)
	mux.Handle("/healthz", &handler.HealthHandler{})
	mux.Handle("/readyz", &handler.ReadyHandler{
		BackendURL: cfg.BackendURL,
		Client:     &http.Client{Timeout: 3 * time.Second},
	})
	mux.Handle("/.well-known/agent.json", &handler.WellKnownHandler{
		AgentName:    cfg.AgentName,
		AgentVersion: cfg.AgentVersion,
	})
	mux.HandleFunc("GET /v1/agent-info", func(w http.ResponseWriter, r *http.Request) {
		resp, err := client.Get(cfg.BackendURL + "/v1/agent-info")
		if err != nil {
			http.Error(w, "backend unreachable", http.StatusBadGateway)
			return
		}
		defer resp.Body.Close()
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(resp.StatusCode)
		io.Copy(w, resp.Body)
	})

	// Auth runs first so logs (and any later middleware) see the resolved
	// canonical X-Auth-* headers and never see spoofed inbound copies.
	var rootHandler http.Handler = mux
	if cfg.LogRequests {
		rootHandler = middleware.LogRequests(rootHandler)
	}
	rootHandler = auth.Middleware(authenticator)(rootHandler)

	srv := &http.Server{
		Addr:              net.JoinHostPort("", cfg.Port),
		Handler:           rootHandler,
		ReadHeaderTimeout: 10 * time.Second,
	}

	// Graceful shutdown on SIGINT / SIGTERM.
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	go func() {
		slog.Info("gateway starting",
			"port", cfg.Port,
			"backend", cfg.BackendURL,
			"platform", cfg.PlatformURL,
			"platform_route_feedback", cfg.PlatformURL != "" && cfg.PlatformRouteFeedback,
			"platform_route_sessions", cfg.PlatformURL != "" && cfg.PlatformRouteSessions,
			"platform_route_traces", cfg.PlatformURL != "" && cfg.PlatformRouteTraces,
			"agent", cfg.AgentName,
			"version", cfg.AgentVersion,
			"auth_mode", cfg.AuthMode,
			"jwt_token_exchange", exchanger != nil,
			"files_max_bytes", cfg.FilesMaxBytes,
			"files_upload_timeout", cfg.FilesUploadTimeout,
			"files_allowed_mime_count", len(cfg.FilesAllowedMIME),
			"jwt_jwks_refresh_rate_limit", cfg.AuthJWTJWKSRefreshRateLimit,
		)
		if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			slog.Error("server error", "error", err)
			os.Exit(1)
		}
	}()

	<-ctx.Done()
	slog.Info("shutdown signal received, draining connections")

	shutdownCtx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	if err := srv.Shutdown(shutdownCtx); err != nil {
		slog.Error("shutdown error", "error", err)
		os.Exit(1)
	}
	slog.Info("gateway stopped")
}

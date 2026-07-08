package config

import (
	"fmt"
	"os"
	"strconv"
	"strings"
	"time"
)

// FilesMaxBytesDefault is the default cap on multipart upload size (25
// MiB). Sized to comfortably fit reference docs (PDFs, code archives)
// while staying well clear of typical reverse-proxy buffer limits. Raise
// via GATEWAY_FILES_MAX_BYTES for deployments that ingest large media.
const FilesMaxBytesDefault int64 = 25 * 1024 * 1024

// FilesUploadTimeoutDefault is the default per-request deadline applied
// to backend POST /v1/files calls. Larger than the gateway's default 120s
// to accommodate slow links uploading near the size cap.
const FilesUploadTimeoutDefault = 5 * time.Minute

// Config holds the gateway configuration loaded from environment variables.
type Config struct {
	Port         string
	BackendURL   string
	AgentName    string
	AgentVersion string
	LogRequests  bool

	// AuthMode selects the inbound auth strategy: "anonymous" (default),
	// "proxy", or "jwt". See internal/auth.
	AuthMode string
	// AuthProxyUserHeader is the upstream-projected username header
	// consulted in proxy mode. Defaults to "X-Forwarded-User"
	// (oauth-proxy convention).
	AuthProxyUserHeader string
	// AuthProxyEmailHeader is the upstream-projected email header. Empty
	// means the deployment does not surface email.
	AuthProxyEmailHeader string

	// JWT mode: in-process bearer-token validation against a JWKS endpoint.
	// All AuthJWT* fields are consulted only when AuthMode == "jwt".
	AuthJWTJWKSURL      string
	AuthJWTIssuer       string
	AuthJWTAudience     string
	AuthJWTSubjectClaim string
	AuthJWTUserClaim    string
	AuthJWTEmailClaim   string

	// AuthJWTJWKSRefreshRateLimit caps how often the JWKS client will
	// refresh the key set in response to an unknown `kid`. Zero (the
	// default) keeps keyfunc's library default of one refresh per 5
	// minutes — already conservative enough that a forged-kid burst
	// can't hammer Keycloak. Tune lower than 5m only if you've measured
	// a real post-rotation latency problem; tune higher to harden
	// against noisier neighbours. Parsed as a Go duration from
	// GATEWAY_AUTH_JWT_JWKS_REFRESH_RATE_LIMIT.
	AuthJWTJWKSRefreshRateLimit time.Duration

	// Token exchange (RFC 8693): consulted only when AuthMode == "jwt".
	// When all four required fields (URL, ClientID, ClientSecret, Audience)
	// are non-empty, the gateway swaps the inbound user JWT for a
	// downstream-audienced token before forwarding to the backend. Partial
	// configuration (some set, some empty) is rejected at Load() time.
	AuthJWTExchangeURL          string
	AuthJWTExchangeClientID     string
	AuthJWTExchangeClientSecret string
	AuthJWTExchangeAudience     string
	AuthJWTExchangeScope        string

	// PlatformURL is the base URL of a deployed fipsagents-platform
	// service. When set, /v1/feedback*, /v1/sessions/*, and /v1/traces/*
	// route to it instead of fanning out to the per-agent BackendURL.
	// When empty, gateway behavior is unchanged from 0.4.x — every prefix
	// proxies to the backend agent.
	//
	// Per-prefix toggles allow mixing: eg feedback to platform but
	// sessions still on the agent. Toggles default to true when
	// PlatformURL is set; setting them false routes that prefix to the
	// agent. When PlatformURL is empty, toggles are no-ops.
	//
	// GET /v1/sessions/{id}/usage always routes to the agent — that
	// endpoint computes USD cost from the agent's PricingConfig and is
	// not implemented on the platform.
	PlatformURL           string
	PlatformRouteFeedback bool
	PlatformRouteSessions bool
	PlatformRouteTraces   bool

	// FilesMaxBytes caps the size of a single multipart upload at the
	// gateway. Requests advertising a Content-Length over this limit are
	// rejected with 413 before any bytes are read. Streamed bodies are
	// counted with http.MaxBytesReader so chunked clients cannot bypass
	// the check by omitting Content-Length. Default: 25 MiB.
	FilesMaxBytes int64

	// FilesAllowedMIME is the gateway-level MIME allowlist applied to
	// each file part of a multipart upload. Entries may be exact
	// (eg "application/pdf") or wildcard (eg "image/*"); empty means
	// allow-all (the agent's own allowlist still applies). Parsed from
	// the comma-separated GATEWAY_FILES_ALLOWED_MIME variable.
	FilesAllowedMIME []string

	// FilesUploadTimeout is the per-request timeout applied to backend
	// POST /v1/files calls. Default: 5 minutes (vs the 120s used for
	// chat completions) so large uploads on slow links don't trip the
	// gateway-side deadline before the agent finishes parsing.
	FilesUploadTimeout time.Duration
}

// MIMEAllowed reports whether contentType matches the FilesAllowedMIME
// allowlist. An empty allowlist means allow-all. Each list entry may be
// an exact type ("application/pdf") or a wildcard ("image/*"); the
// match is case-insensitive on the type/subtype but ignores any
// boundary parameter the caller might have appended.
func (c *Config) MIMEAllowed(contentType string) bool {
	if len(c.FilesAllowedMIME) == 0 {
		return true
	}
	ct := strings.ToLower(strings.TrimSpace(contentType))
	if i := strings.IndexByte(ct, ';'); i >= 0 {
		ct = strings.TrimSpace(ct[:i])
	}
	if ct == "" {
		return false
	}
	for _, allowed := range c.FilesAllowedMIME {
		if allowed == ct {
			return true
		}
		if strings.HasSuffix(allowed, "/*") {
			prefix := allowed[:len(allowed)-1] // keep trailing slash
			if strings.HasPrefix(ct, prefix) {
				return true
			}
		}
	}
	return false
}

// FeedbackTargetURL returns the base URL that /v1/feedback* requests
// should be proxied to. When platform routing is enabled for feedback,
// returns PlatformURL; otherwise falls back to BackendURL.
func (c *Config) FeedbackTargetURL() string {
	if c.PlatformURL != "" && c.PlatformRouteFeedback {
		return c.PlatformURL
	}
	return c.BackendURL
}

// SessionsTargetURL returns the base URL that /v1/sessions/* requests
// (other than the agent-only /usage carve-out) should be proxied to.
func (c *Config) SessionsTargetURL() string {
	if c.PlatformURL != "" && c.PlatformRouteSessions {
		return c.PlatformURL
	}
	return c.BackendURL
}

// TracesTargetURL returns the base URL that /v1/traces/* requests should
// be proxied to.
func (c *Config) TracesTargetURL() string {
	if c.PlatformURL != "" && c.PlatformRouteTraces {
		return c.PlatformURL
	}
	return c.BackendURL
}

// JWTExchangeEnabled reports whether all four required token-exchange
// fields are populated. Used by the wiring layer to decide whether to
// construct a TokenExchanger.
func (c *Config) JWTExchangeEnabled() bool {
	return c.AuthJWTExchangeURL != "" &&
		c.AuthJWTExchangeClientID != "" &&
		c.AuthJWTExchangeClientSecret != "" &&
		c.AuthJWTExchangeAudience != ""
}

// Load reads configuration from environment variables and validates required fields.
func Load() (*Config, error) {
	cfg := &Config{
		Port:                 envOrDefault("PORT", "8080"),
		BackendURL:           os.Getenv("BACKEND_URL"),
		AgentName:            envOrDefault("AGENT_NAME", "gateway-template"),
		AgentVersion:         envOrDefault("AGENT_VERSION", "0.1.0"),
		LogRequests:          envBool("LOG_REQUESTS"),
		AuthMode:             envOrDefault("GATEWAY_AUTH_MODE", "anonymous"),
		AuthProxyUserHeader:  envOrDefault("GATEWAY_AUTH_PROXY_USER_HEADER", "X-Forwarded-User"),
		AuthProxyEmailHeader: envOrDefault("GATEWAY_AUTH_PROXY_EMAIL_HEADER", "X-Forwarded-Email"),
		AuthJWTJWKSURL:              os.Getenv("GATEWAY_AUTH_JWT_JWKS_URL"),
		AuthJWTIssuer:               os.Getenv("GATEWAY_AUTH_JWT_ISSUER"),
		AuthJWTAudience:             os.Getenv("GATEWAY_AUTH_JWT_AUDIENCE"),
		AuthJWTSubjectClaim:         envOrDefault("GATEWAY_AUTH_JWT_SUBJECT_CLAIM", "sub"),
		AuthJWTUserClaim:            envOrDefault("GATEWAY_AUTH_JWT_USER_CLAIM", "preferred_username"),
		AuthJWTEmailClaim:           envOrDefault("GATEWAY_AUTH_JWT_EMAIL_CLAIM", "email"),
		AuthJWTExchangeURL:          os.Getenv("GATEWAY_AUTH_JWT_TOKEN_EXCHANGE_URL"),
		AuthJWTExchangeClientID:     os.Getenv("GATEWAY_AUTH_JWT_TOKEN_EXCHANGE_CLIENT_ID"),
		AuthJWTExchangeClientSecret: os.Getenv("GATEWAY_AUTH_JWT_TOKEN_EXCHANGE_CLIENT_SECRET"),
		AuthJWTExchangeAudience:     os.Getenv("GATEWAY_AUTH_JWT_TOKEN_EXCHANGE_AUDIENCE"),
		AuthJWTExchangeScope:        os.Getenv("GATEWAY_AUTH_JWT_TOKEN_EXCHANGE_SCOPE"),
		AuthJWTJWKSRefreshRateLimit: 0, // resolved below; 0 ⇒ keyfunc default

		PlatformURL: strings.TrimRight(os.Getenv("GATEWAY_PLATFORM_URL"), "/"),
		// Per-prefix toggles default to true so that setting PLATFORM_URL
		// alone routes all three prefixes. Operators opt out per-prefix
		// by setting the toggle to "false".
		PlatformRouteFeedback: envBoolDefault("GATEWAY_PLATFORM_ROUTE_FEEDBACK", true),
		PlatformRouteSessions: envBoolDefault("GATEWAY_PLATFORM_ROUTE_SESSIONS", true),
		PlatformRouteTraces:   envBoolDefault("GATEWAY_PLATFORM_ROUTE_TRACES", true),
	}

	maxBytes, err := envBytesDefault("GATEWAY_FILES_MAX_BYTES", FilesMaxBytesDefault)
	if err != nil {
		return nil, err
	}
	cfg.FilesMaxBytes = maxBytes
	cfg.FilesAllowedMIME = parseMIMEList(os.Getenv("GATEWAY_FILES_ALLOWED_MIME"))
	timeout, err := envDurationDefault("GATEWAY_FILES_UPLOAD_TIMEOUT", FilesUploadTimeoutDefault)
	if err != nil {
		return nil, err
	}
	cfg.FilesUploadTimeout = timeout

	if cfg.BackendURL == "" {
		return nil, fmt.Errorf("BACKEND_URL environment variable is required")
	}
	if cfg.AuthMode == "jwt" {
		if cfg.AuthJWTJWKSURL == "" {
			return nil, fmt.Errorf("GATEWAY_AUTH_JWT_JWKS_URL is required when GATEWAY_AUTH_MODE=jwt")
		}
		if cfg.AuthJWTIssuer == "" {
			return nil, fmt.Errorf("GATEWAY_AUTH_JWT_ISSUER is required when GATEWAY_AUTH_MODE=jwt")
		}
		if cfg.AuthJWTAudience == "" {
			return nil, fmt.Errorf("GATEWAY_AUTH_JWT_AUDIENCE is required when GATEWAY_AUTH_MODE=jwt")
		}
		if err := validateExchangeConfig(cfg); err != nil {
			return nil, err
		}
		d, err := envDurationDefaultAllowZero("GATEWAY_AUTH_JWT_JWKS_REFRESH_RATE_LIMIT", 0)
		if err != nil {
			return nil, err
		}
		cfg.AuthJWTJWKSRefreshRateLimit = d
	}

	return cfg, nil
}

// envDurationDefaultAllowZero parses a Go duration env var. Empty / unset
// returns fallback. Negative values are rejected, zero is allowed (used by
// JWKS refresh rate limit, where zero means "use keyfunc default").
func envDurationDefaultAllowZero(key string, fallback time.Duration) (time.Duration, error) {
	raw, ok := os.LookupEnv(key)
	if !ok || strings.TrimSpace(raw) == "" {
		return fallback, nil
	}
	d, err := time.ParseDuration(strings.TrimSpace(raw))
	if err != nil {
		return 0, fmt.Errorf("%s: invalid duration %q: %w", key, raw, err)
	}
	if d < 0 {
		return 0, fmt.Errorf("%s: must be >= 0, got %q", key, raw)
	}
	return d, nil
}

// validateExchangeConfig fails closed on partially-configured token
// exchange. Either all four required fields are set (exchange enabled) or
// none are (exchange disabled). Anything in between is almost certainly a
// deployment bug — flag it loudly at startup rather than silently disabling
// the swap.
func validateExchangeConfig(cfg *Config) error {
	required := map[string]string{
		"GATEWAY_AUTH_JWT_TOKEN_EXCHANGE_URL":           cfg.AuthJWTExchangeURL,
		"GATEWAY_AUTH_JWT_TOKEN_EXCHANGE_CLIENT_ID":     cfg.AuthJWTExchangeClientID,
		"GATEWAY_AUTH_JWT_TOKEN_EXCHANGE_CLIENT_SECRET": cfg.AuthJWTExchangeClientSecret,
		"GATEWAY_AUTH_JWT_TOKEN_EXCHANGE_AUDIENCE":      cfg.AuthJWTExchangeAudience,
	}
	var setNames, missingNames []string
	for name, val := range required {
		if val != "" {
			setNames = append(setNames, name)
		} else {
			missingNames = append(missingNames, name)
		}
	}
	if len(setNames) > 0 && len(missingNames) > 0 {
		return fmt.Errorf("token exchange is partially configured: %v set but %v missing — set all four or none", setNames, missingNames)
	}
	return nil
}

func envOrDefault(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

func envBool(key string) bool {
	v := strings.ToLower(os.Getenv(key))
	return v == "true" || v == "1" || v == "yes"
}

// envBoolDefault parses a bool env var with an explicit default returned
// when the variable is unset. Distinct from envBool, which conflates
// unset with "false". Used for opt-out toggles where unset must mean the
// default rather than false.
func envBoolDefault(key string, fallback bool) bool {
	raw, ok := os.LookupEnv(key)
	if !ok || raw == "" {
		return fallback
	}
	v := strings.ToLower(raw)
	return v == "true" || v == "1" || v == "yes"
}

// envBytesDefault parses a byte-count env var. Accepts plain integers
// (bytes) or values suffixed with k/m/g (binary, case-insensitive: 5MiB
// counts as the same thing as 5m). Returns the fallback when the
// variable is unset or empty.
func envBytesDefault(key string, fallback int64) (int64, error) {
	raw, ok := os.LookupEnv(key)
	if !ok || raw == "" {
		return fallback, nil
	}
	s := strings.TrimSpace(strings.ToLower(raw))
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
		return 0, fmt.Errorf("%s: invalid byte count %q: %w", key, raw, err)
	}
	if n <= 0 {
		return 0, fmt.Errorf("%s: must be positive, got %q", key, raw)
	}
	return n * mult, nil
}

// envDurationDefault parses a Go duration string from an env var.
func envDurationDefault(key string, fallback time.Duration) (time.Duration, error) {
	raw, ok := os.LookupEnv(key)
	if !ok || raw == "" {
		return fallback, nil
	}
	d, err := time.ParseDuration(strings.TrimSpace(raw))
	if err != nil {
		return 0, fmt.Errorf("%s: invalid duration %q: %w", key, raw, err)
	}
	if d <= 0 {
		return 0, fmt.Errorf("%s: must be positive, got %q", key, raw)
	}
	return d, nil
}

// parseMIMEList splits a comma-separated MIME-type list, trimming
// whitespace and dropping empty entries. Lowercased so the runtime
// matcher can compare without re-normalising.
func parseMIMEList(raw string) []string {
	if strings.TrimSpace(raw) == "" {
		return nil
	}
	parts := strings.Split(raw, ",")
	out := make([]string, 0, len(parts))
	for _, p := range parts {
		v := strings.ToLower(strings.TrimSpace(p))
		if v != "" {
			out = append(out, v)
		}
	}
	return out
}

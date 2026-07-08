package config_test

import (
	"strings"
	"testing"
	"time"

	"github.com/fips-agents/gateway-template/internal/config"
)

// jwtBaseEnv returns the minimum env vars needed for AuthMode=jwt to pass
// validation. Tests can override individual entries before calling
// loadWithEnv.
func jwtBaseEnv() map[string]string {
	return map[string]string{
		"BACKEND_URL":                "http://backend:8081",
		"GATEWAY_AUTH_MODE":          "jwt",
		"GATEWAY_AUTH_JWT_JWKS_URL":  "https://kc/realms/x/protocol/openid-connect/certs",
		"GATEWAY_AUTH_JWT_ISSUER":    "https://kc/realms/x",
		"GATEWAY_AUTH_JWT_AUDIENCE":  "gateway-template",
	}
}

// loadWithEnv sets env vars for the lifetime of t and calls config.Load.
func loadWithEnv(t *testing.T, env map[string]string) (*config.Config, error) {
	t.Helper()
	for k, v := range env {
		t.Setenv(k, v)
	}
	return config.Load()
}

func TestLoad_JWTExchange_AllFieldsSet(t *testing.T) {
	env := jwtBaseEnv()
	env["GATEWAY_AUTH_JWT_TOKEN_EXCHANGE_URL"] = "https://kc/realms/x/protocol/openid-connect/token"
	env["GATEWAY_AUTH_JWT_TOKEN_EXCHANGE_CLIENT_ID"] = "gw-svc"
	env["GATEWAY_AUTH_JWT_TOKEN_EXCHANGE_CLIENT_SECRET"] = "shh"
	env["GATEWAY_AUTH_JWT_TOKEN_EXCHANGE_AUDIENCE"] = "backend-agent"

	cfg, err := loadWithEnv(t, env)
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if !cfg.JWTExchangeEnabled() {
		t.Fatal("JWTExchangeEnabled() = false, want true")
	}
}

func TestLoad_JWTExchange_NoFieldsSet(t *testing.T) {
	cfg, err := loadWithEnv(t, jwtBaseEnv())
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if cfg.JWTExchangeEnabled() {
		t.Fatal("JWTExchangeEnabled() = true with no exchange fields set, want false")
	}
}

func TestLoad_JWTExchange_PartialConfigRejected(t *testing.T) {
	cases := []struct {
		name    string
		setKeys []string
	}{
		{"only url", []string{"GATEWAY_AUTH_JWT_TOKEN_EXCHANGE_URL"}},
		{"url+client_id", []string{
			"GATEWAY_AUTH_JWT_TOKEN_EXCHANGE_URL",
			"GATEWAY_AUTH_JWT_TOKEN_EXCHANGE_CLIENT_ID",
		}},
		{"missing audience", []string{
			"GATEWAY_AUTH_JWT_TOKEN_EXCHANGE_URL",
			"GATEWAY_AUTH_JWT_TOKEN_EXCHANGE_CLIENT_ID",
			"GATEWAY_AUTH_JWT_TOKEN_EXCHANGE_CLIENT_SECRET",
		}},
		{"missing secret", []string{
			"GATEWAY_AUTH_JWT_TOKEN_EXCHANGE_URL",
			"GATEWAY_AUTH_JWT_TOKEN_EXCHANGE_CLIENT_ID",
			"GATEWAY_AUTH_JWT_TOKEN_EXCHANGE_AUDIENCE",
		}},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			env := jwtBaseEnv()
			for _, k := range tc.setKeys {
				env[k] = "value"
			}
			_, err := loadWithEnv(t, env)
			if err == nil {
				t.Fatal("expected error on partial token-exchange config, got nil")
			}
			if !strings.Contains(err.Error(), "token exchange") {
				t.Errorf("error message should mention token exchange, got: %v", err)
			}
		})
	}
}

func TestLoad_PlatformURL_UnsetMeansLegacyFanout(t *testing.T) {
	cfg, err := loadWithEnv(t, map[string]string{"BACKEND_URL": "http://agent:8080"})
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if cfg.PlatformURL != "" {
		t.Errorf("PlatformURL = %q, want empty", cfg.PlatformURL)
	}
	if got := cfg.FeedbackTargetURL(); got != "http://agent:8080" {
		t.Errorf("FeedbackTargetURL = %q, want backend URL", got)
	}
	if got := cfg.SessionsTargetURL(); got != "http://agent:8080" {
		t.Errorf("SessionsTargetURL = %q, want backend URL", got)
	}
	if got := cfg.TracesTargetURL(); got != "http://agent:8080" {
		t.Errorf("TracesTargetURL = %q, want backend URL", got)
	}
}

func TestLoad_PlatformURL_SetRoutesAllPrefixes(t *testing.T) {
	cfg, err := loadWithEnv(t, map[string]string{
		"BACKEND_URL":          "http://agent:8080",
		"GATEWAY_PLATFORM_URL": "http://platform:8080",
	})
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if cfg.PlatformURL != "http://platform:8080" {
		t.Errorf("PlatformURL = %q, want platform URL", cfg.PlatformURL)
	}
	for name, got := range map[string]string{
		"feedback": cfg.FeedbackTargetURL(),
		"sessions": cfg.SessionsTargetURL(),
		"traces":   cfg.TracesTargetURL(),
	} {
		if got != "http://platform:8080" {
			t.Errorf("%sTargetURL = %q, want platform URL", name, got)
		}
	}
}

func TestLoad_PlatformURL_PerPrefixOptOut(t *testing.T) {
	cfg, err := loadWithEnv(t, map[string]string{
		"BACKEND_URL":                     "http://agent:8080",
		"GATEWAY_PLATFORM_URL":            "http://platform:8080",
		"GATEWAY_PLATFORM_ROUTE_SESSIONS": "false",
	})
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if got := cfg.SessionsTargetURL(); got != "http://agent:8080" {
		t.Errorf("SessionsTargetURL = %q, want backend (opted out)", got)
	}
	if got := cfg.FeedbackTargetURL(); got != "http://platform:8080" {
		t.Errorf("FeedbackTargetURL = %q, want platform (still opted in)", got)
	}
	if got := cfg.TracesTargetURL(); got != "http://platform:8080" {
		t.Errorf("TracesTargetURL = %q, want platform (still opted in)", got)
	}
}

func TestLoad_PlatformURL_TrailingSlashTrimmed(t *testing.T) {
	cfg, err := loadWithEnv(t, map[string]string{
		"BACKEND_URL":          "http://agent:8080",
		"GATEWAY_PLATFORM_URL": "http://platform:8080/",
	})
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if cfg.PlatformURL != "http://platform:8080" {
		t.Errorf("PlatformURL = %q, want trailing slash trimmed", cfg.PlatformURL)
	}
}

func TestLoad_PlatformToggle_NoOpWhenURLUnset(t *testing.T) {
	cfg, err := loadWithEnv(t, map[string]string{
		"BACKEND_URL":                     "http://agent:8080",
		"GATEWAY_PLATFORM_ROUTE_SESSIONS": "true",
		"GATEWAY_PLATFORM_ROUTE_TRACES":   "true",
	})
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	// Toggles set without PLATFORM_URL must still resolve to backend —
	// they're cheap config knobs, not failure modes.
	if got := cfg.SessionsTargetURL(); got != "http://agent:8080" {
		t.Errorf("SessionsTargetURL = %q, want backend (URL unset)", got)
	}
}

func TestLoad_JWKSRefreshRateLimit_DefaultZero(t *testing.T) {
	cfg, err := loadWithEnv(t, jwtBaseEnv())
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if cfg.AuthJWTJWKSRefreshRateLimit != 0 {
		t.Errorf("AuthJWTJWKSRefreshRateLimit = %v, want 0 (keyfunc default)", cfg.AuthJWTJWKSRefreshRateLimit)
	}
}

func TestLoad_JWKSRefreshRateLimit_Parsed(t *testing.T) {
	env := jwtBaseEnv()
	env["GATEWAY_AUTH_JWT_JWKS_REFRESH_RATE_LIMIT"] = "30s"

	cfg, err := loadWithEnv(t, env)
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if got, want := cfg.AuthJWTJWKSRefreshRateLimit, 30*time.Second; got != want {
		t.Errorf("AuthJWTJWKSRefreshRateLimit = %v, want %v", got, want)
	}
}

func TestLoad_JWKSRefreshRateLimit_Invalid(t *testing.T) {
	env := jwtBaseEnv()
	env["GATEWAY_AUTH_JWT_JWKS_REFRESH_RATE_LIMIT"] = "thirty seconds"

	_, err := loadWithEnv(t, env)
	if err == nil {
		t.Fatal("expected error on unparseable duration, got nil")
	}
	if !strings.Contains(err.Error(), "GATEWAY_AUTH_JWT_JWKS_REFRESH_RATE_LIMIT") {
		t.Errorf("error should reference the env var, got: %v", err)
	}
}

func TestLoad_JWKSRefreshRateLimit_Negative(t *testing.T) {
	env := jwtBaseEnv()
	env["GATEWAY_AUTH_JWT_JWKS_REFRESH_RATE_LIMIT"] = "-5s"

	_, err := loadWithEnv(t, env)
	if err == nil {
		t.Fatal("expected error on negative duration, got nil")
	}
}

func TestLoad_JWKSRefreshRateLimit_NotConsultedInAnonymousMode(t *testing.T) {
	t.Setenv("BACKEND_URL", "http://backend:8081")
	t.Setenv("GATEWAY_AUTH_MODE", "anonymous")
	t.Setenv("GATEWAY_AUTH_JWT_JWKS_REFRESH_RATE_LIMIT", "garbage")

	cfg, err := config.Load()
	if err != nil {
		t.Fatalf("Load in anonymous mode should ignore the JWKS rate-limit var: %v", err)
	}
	if cfg.AuthJWTJWKSRefreshRateLimit != 0 {
		t.Errorf("AuthJWTJWKSRefreshRateLimit = %v, want 0 in anonymous mode", cfg.AuthJWTJWKSRefreshRateLimit)
	}
}

func TestLoad_JWTExchange_NotConsultedInAnonymousMode(t *testing.T) {
	// Setting exchange env vars while in anonymous mode should not trigger
	// the partial-config validator. They're inert outside jwt mode, so
	// leaving them set during a mode flip should not break startup.
	t.Setenv("BACKEND_URL", "http://backend:8081")
	t.Setenv("GATEWAY_AUTH_MODE", "anonymous")
	t.Setenv("GATEWAY_AUTH_JWT_TOKEN_EXCHANGE_URL", "https://kc/.../token")
	// (deliberately leave the other three unset)

	if _, err := config.Load(); err != nil {
		t.Fatalf("Load in anonymous mode should ignore exchange env vars: %v", err)
	}
}

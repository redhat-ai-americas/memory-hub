//go:build integration

// Package-level integration test for JWT mode against a live Keycloak.
//
// Run by setting KC_INTEGRATION=1 plus the env vars below, then:
//
//	go test -tags integration -run TestJWTAuth_LiveKeycloak ./internal/auth/...
//
// The companion script `scripts/keycloak-test-setup.sh` provisions a clean
// realm + client + user inside the keycloak-keycloak namespace and prints
// an eval-able env block:
//
//	eval "$(scripts/keycloak-test-setup.sh)"
//	go test -tags integration -run TestJWTAuth_LiveKeycloak ./internal/auth/...
//
// The test is skipped when KC_INTEGRATION is unset so CI without cluster
// access stays green.

package auth_test

import (
	"crypto/tls"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"strings"
	"testing"
	"time"

	"github.com/fips-agents/gateway-template/internal/auth"
)

func mustEnv(t *testing.T, key string) string {
	t.Helper()
	v := os.Getenv(key)
	if v == "" {
		t.Fatalf("integration test requires env %s", key)
	}
	return v
}

// liveKeycloakHTTPClient skips TLS verify because the sandbox cluster uses
// a self-signed wildcard cert. Production deployments should use the
// system CA bundle.
func liveKeycloakHTTPClient() *http.Client {
	return &http.Client{
		Timeout: 10 * time.Second,
		Transport: &http.Transport{
			TLSClientConfig: &tls.Config{InsecureSkipVerify: true}, //nolint:gosec // sandbox-only
		},
	}
}

// fetchUserToken does a Resource Owner Password Credentials grant. This is
// the simplest way to get a user-bearing access token in a test; production
// callers use the auth-code flow.
func fetchUserToken(t *testing.T, tokenURL, clientID, clientSecret, user, password string) string {
	t.Helper()
	form := url.Values{}
	form.Set("grant_type", "password")
	form.Set("client_id", clientID)
	form.Set("client_secret", clientSecret)
	form.Set("username", user)
	form.Set("password", password)
	form.Set("scope", "openid email profile")

	req, err := http.NewRequest("POST", tokenURL, strings.NewReader(form.Encode()))
	if err != nil {
		t.Fatalf("NewRequest: %v", err)
	}
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")

	resp, err := liveKeycloakHTTPClient().Do(req)
	if err != nil {
		t.Fatalf("token request: %v", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		body := make([]byte, 512)
		n, _ := resp.Body.Read(body)
		t.Fatalf("token endpoint returned %d: %s", resp.StatusCode, body[:n])
	}
	var payload struct {
		AccessToken string `json:"access_token"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&payload); err != nil {
		t.Fatalf("decode token response: %v", err)
	}
	if payload.AccessToken == "" {
		t.Fatal("token endpoint returned empty access_token")
	}
	return payload.AccessToken
}

// jwtAuthForLive constructs a JWTAuth that points at the live Keycloak.
// It also patches the default http.DefaultTransport to skip TLS verify so
// the JWKS fetch succeeds against the sandbox cluster's self-signed cert.
//
// We do this with a defer-restore so the global is only mutated for the
// duration of the test. This is gross but localised — the alternative is
// to plumb an http.Client through JWTAuth's surface, which we can do in
// a follow-up if real deployments need it.
func jwtAuthForLive(t *testing.T) (auth.Authenticator, func()) {
	t.Helper()
	orig := http.DefaultTransport
	http.DefaultTransport = &http.Transport{
		TLSClientConfig: &tls.Config{InsecureSkipVerify: true}, //nolint:gosec // sandbox-only
	}
	cleanup := func() { http.DefaultTransport = orig }

	a, err := auth.New(auth.ModeJWT, auth.Options{
		JWT: auth.JWTConfig{
			JWKSURL:  mustEnv(t, "KC_JWKS_URL"),
			Issuer:   mustEnv(t, "KC_ISSUER"),
			Audience: mustEnv(t, "KC_AUDIENCE"),
		},
	})
	if err != nil {
		cleanup()
		t.Fatalf("auth.New(jwt): %v", err)
	}
	return a, cleanup
}

func TestJWTAuth_LiveKeycloak_HappyPath(t *testing.T) {
	if os.Getenv("KC_INTEGRATION") == "" {
		t.Skip("set KC_INTEGRATION=1 (and run scripts/keycloak-test-setup.sh) to enable")
	}

	a, cleanup := jwtAuthForLive(t)
	defer cleanup()

	tok := fetchUserToken(t,
		mustEnv(t, "KC_TOKEN_URL"),
		mustEnv(t, "KC_CLIENT_ID"),
		mustEnv(t, "KC_CLIENT_SECRET"),
		mustEnv(t, "KC_USERNAME"),
		mustEnv(t, "KC_PASSWORD"),
	)

	r := httptest.NewRequest("POST", "/v1/chat/completions", nil)
	r.Header.Set("Authorization", "Bearer "+tok)

	id, err := a.Authenticate(r)
	if err != nil {
		t.Fatalf("Authenticate: %v", err)
	}
	if id.Subject == "" {
		t.Errorf("expected non-empty subject, got %+v", id)
	}
	if id.Mode != auth.ModeJWT {
		t.Errorf("expected mode=jwt, got %q", id.Mode)
	}
	wantUser := os.Getenv("KC_USERNAME")
	if id.User != wantUser {
		t.Errorf("expected User=%q, got %q", wantUser, id.User)
	}
	wantEmail := os.Getenv("KC_USER_EMAIL")
	if id.Email != wantEmail {
		t.Errorf("expected Email=%q, got %q", wantEmail, id.Email)
	}
}

func TestJWTAuth_LiveKeycloak_TokenExchange(t *testing.T) {
	if os.Getenv("KC_INTEGRATION") == "" {
		t.Skip("set KC_INTEGRATION=1 to enable")
	}
	if os.Getenv("KC_EXCHANGE_AUDIENCE") == "" {
		t.Skip("set KC_EXCHANGE_* (run scripts/keycloak-test-setup.sh against Keycloak 26+) to enable")
	}

	orig := http.DefaultTransport
	http.DefaultTransport = &http.Transport{
		TLSClientConfig: &tls.Config{InsecureSkipVerify: true}, //nolint:gosec // sandbox-only
	}
	defer func() { http.DefaultTransport = orig }()

	ex, err := auth.NewTokenExchanger(auth.TokenExchangeConfig{
		TokenURL:     mustEnv(t, "KC_EXCHANGE_TOKEN_URL"),
		ClientID:     mustEnv(t, "KC_EXCHANGE_CLIENT_ID"),
		ClientSecret: mustEnv(t, "KC_EXCHANGE_CLIENT_SECRET"),
		Audience:     mustEnv(t, "KC_EXCHANGE_AUDIENCE"),
		HTTPClient:   liveKeycloakHTTPClient(),
	})
	if err != nil {
		t.Fatalf("NewTokenExchanger: %v", err)
	}

	a, err := auth.New(auth.ModeJWT, auth.Options{
		JWT: auth.JWTConfig{
			JWKSURL:  mustEnv(t, "KC_JWKS_URL"),
			Issuer:   mustEnv(t, "KC_ISSUER"),
			Audience: mustEnv(t, "KC_AUDIENCE"),
		},
		JWTExchanger: ex,
	})
	if err != nil {
		t.Fatalf("auth.New(jwt+exchange): %v", err)
	}

	userTok := fetchUserToken(t,
		mustEnv(t, "KC_TOKEN_URL"),
		mustEnv(t, "KC_CLIENT_ID"),
		mustEnv(t, "KC_CLIENT_SECRET"),
		mustEnv(t, "KC_USERNAME"),
		mustEnv(t, "KC_PASSWORD"),
	)

	r := httptest.NewRequest("POST", "/v1/chat/completions", nil)
	r.Header.Set("Authorization", "Bearer "+userTok)

	id, err := a.Authenticate(r)
	if err != nil {
		t.Fatalf("Authenticate (with exchange): %v", err)
	}
	if id.BearerToken == "" {
		t.Fatal("expected non-empty BearerToken from exchange, got empty")
	}
	if id.BearerToken == userTok {
		t.Error("BearerToken equals input — Keycloak did not actually swap the token")
	}

	// Round-trip the swapped token through a fresh validator pointed at
	// the *exchange* audience. Successful validation proves: Keycloak
	// signed the swap (cryptographic assertion), aud matches the
	// downstream resource the gateway requested, and any downstream MCP
	// server using the same JWKS can verify the swap the same way.
	downstream, err := auth.New(auth.ModeJWT, auth.Options{
		JWT: auth.JWTConfig{
			JWKSURL:  mustEnv(t, "KC_JWKS_URL"),
			Issuer:   mustEnv(t, "KC_ISSUER"),
			Audience: mustEnv(t, "KC_EXCHANGE_AUDIENCE"),
		},
	})
	if err != nil {
		t.Fatalf("downstream validator: %v", err)
	}

	r2 := httptest.NewRequest("POST", "/v1/chat/completions", nil)
	r2.Header.Set("Authorization", "Bearer "+id.BearerToken)
	swapID, err := downstream.Authenticate(r2)
	if err != nil {
		t.Fatalf("downstream validation of swapped token: %v", err)
	}
	if swapID.Subject != id.Subject {
		t.Errorf("swapped sub %q != original sub %q (user identity must be preserved through the swap)", swapID.Subject, id.Subject)
	}
}

func TestJWTAuth_LiveKeycloak_RejectsTamperedToken(t *testing.T) {
	if os.Getenv("KC_INTEGRATION") == "" {
		t.Skip("set KC_INTEGRATION=1 to enable")
	}

	a, cleanup := jwtAuthForLive(t)
	defer cleanup()

	tok := fetchUserToken(t,
		mustEnv(t, "KC_TOKEN_URL"),
		mustEnv(t, "KC_CLIENT_ID"),
		mustEnv(t, "KC_CLIENT_SECRET"),
		mustEnv(t, "KC_USERNAME"),
		mustEnv(t, "KC_PASSWORD"),
	)
	// Flip a byte in the signature so the JWS verification fails.
	tampered := tok[:len(tok)-2] + "AA"

	r := httptest.NewRequest("POST", "/v1/chat/completions", nil)
	r.Header.Set("Authorization", "Bearer "+tampered)

	if _, err := a.Authenticate(r); err == nil {
		t.Fatal("Authenticate accepted a tampered token")
	}
}

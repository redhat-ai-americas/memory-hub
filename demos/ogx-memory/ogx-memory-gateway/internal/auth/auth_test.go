package auth_test

import (
	"errors"
	"net/http/httptest"
	"testing"

	"github.com/fips-agents/gateway-template/internal/auth"
)

func TestNew_DefaultsToAnonymous(t *testing.T) {
	a, err := auth.New("", auth.Options{})
	if err != nil {
		t.Fatalf("New(\"\"): unexpected error: %v", err)
	}
	if _, ok := a.(*auth.AnonymousAuth); !ok {
		t.Fatalf("New(\"\"): want *AnonymousAuth, got %T", a)
	}
}

func TestNew_AnonymousMode(t *testing.T) {
	a, err := auth.New(auth.ModeAnonymous, auth.Options{})
	if err != nil {
		t.Fatalf("New(anonymous): unexpected error: %v", err)
	}
	if _, ok := a.(*auth.AnonymousAuth); !ok {
		t.Fatalf("New(anonymous): want *AnonymousAuth, got %T", a)
	}
}

func TestNew_ProxyMode(t *testing.T) {
	a, err := auth.New(auth.ModeProxy, auth.Options{
		ProxyUserHeader:  "X-Forwarded-User",
		ProxyEmailHeader: "X-Forwarded-Email",
	})
	if err != nil {
		t.Fatalf("New(proxy): unexpected error: %v", err)
	}
	pa, ok := a.(*auth.ProxyAuth)
	if !ok {
		t.Fatalf("New(proxy): want *ProxyAuth, got %T", a)
	}
	if pa.UserHeader != "X-Forwarded-User" || pa.EmailHeader != "X-Forwarded-Email" {
		t.Errorf("New(proxy): headers not propagated: %+v", pa)
	}
}

func TestNew_ProxyRequiresUserHeader(t *testing.T) {
	if _, err := auth.New(auth.ModeProxy, auth.Options{ProxyEmailHeader: "X-Forwarded-Email"}); err == nil {
		t.Fatal("New(proxy, empty user header): expected error, got nil")
	}
}

func TestNew_UnknownModeRejected(t *testing.T) {
	if _, err := auth.New("garbage", auth.Options{}); err == nil {
		t.Fatal("New(garbage): expected error for unsupported mode, got nil")
	}
}

func TestNew_JWTRequiresJWKSURL(t *testing.T) {
	if _, err := auth.New(auth.ModeJWT, auth.Options{
		JWT: auth.JWTConfig{Issuer: "https://kc/realms/x", Audience: "gw"},
	}); err == nil {
		t.Fatal("New(jwt, missing JWKSURL): expected error, got nil")
	}
}

func TestAnonymousAuth_AlwaysAnonymous(t *testing.T) {
	a := &auth.AnonymousAuth{}
	req := httptest.NewRequest("GET", "/", nil)
	// Even if someone forges X-Auth-* on the way in, the strategy returns
	// canonical anonymous. (The middleware is the layer that strips
	// inbound headers before calling Authenticate.)
	req.Header.Set("X-Auth-Subject", "evil")
	req.Header.Set("X-Forwarded-User", "evil")

	id, err := a.Authenticate(req)
	if err != nil {
		t.Fatalf("Authenticate: unexpected error: %v", err)
	}
	if id.Subject != "anonymous" || id.Mode != auth.ModeAnonymous {
		t.Errorf("anonymous identity: got %+v", id)
	}
	if id.User != "" || id.Email != "" {
		t.Errorf("anonymous identity should have empty User/Email, got %+v", id)
	}
}

func TestProxyAuth_HappyPath(t *testing.T) {
	p := &auth.ProxyAuth{
		UserHeader:  "X-Forwarded-User",
		EmailHeader: "X-Forwarded-Email",
	}
	req := httptest.NewRequest("GET", "/", nil)
	req.Header.Set("X-Forwarded-User", "alice")
	req.Header.Set("X-Forwarded-Email", "alice@example.com")

	id, err := p.Authenticate(req)
	if err != nil {
		t.Fatalf("Authenticate: unexpected error: %v", err)
	}
	want := auth.Identity{
		Subject: "alice",
		User:    "alice",
		Email:   "alice@example.com",
		Mode:    auth.ModeProxy,
	}
	if id != want {
		t.Errorf("proxy identity: got %+v, want %+v", id, want)
	}
}

func TestProxyAuth_MissingUserHeaderFailsClosed(t *testing.T) {
	p := &auth.ProxyAuth{
		UserHeader:  "X-Forwarded-User",
		EmailHeader: "X-Forwarded-Email",
	}
	req := httptest.NewRequest("GET", "/", nil)
	// Email present but user missing — must error so the caller can
	// return 503. Silent fallback to anonymous would mask a misconfigured
	// proxy.
	req.Header.Set("X-Forwarded-Email", "alice@example.com")

	_, err := p.Authenticate(req)
	if !errors.Is(err, auth.ErrMissingProxyHeaders) {
		t.Fatalf("Authenticate: want ErrMissingProxyHeaders, got %v", err)
	}
}

func TestProxyAuth_EmailOptional(t *testing.T) {
	p := &auth.ProxyAuth{
		UserHeader:  "X-Forwarded-User",
		EmailHeader: "X-Forwarded-Email",
	}
	req := httptest.NewRequest("GET", "/", nil)
	req.Header.Set("X-Forwarded-User", "alice")

	id, err := p.Authenticate(req)
	if err != nil {
		t.Fatalf("Authenticate: unexpected error: %v", err)
	}
	if id.Email != "" {
		t.Errorf("expected empty email when header absent, got %q", id.Email)
	}
	if id.Subject != "alice" || id.User != "alice" {
		t.Errorf("expected user=alice, got %+v", id)
	}
}

func TestProxyAuth_EmptyEmailHeaderName(t *testing.T) {
	// EmailHeader = "" means "this deployment doesn't surface email".
	// Must not panic; identity has no email.
	p := &auth.ProxyAuth{UserHeader: "X-Forwarded-User"}
	req := httptest.NewRequest("GET", "/", nil)
	req.Header.Set("X-Forwarded-User", "alice")
	req.Header.Set("X-Forwarded-Email", "alice@example.com") // ignored

	id, err := p.Authenticate(req)
	if err != nil {
		t.Fatalf("Authenticate: unexpected error: %v", err)
	}
	if id.Email != "" {
		t.Errorf("expected empty email when EmailHeader unset, got %q", id.Email)
	}
}

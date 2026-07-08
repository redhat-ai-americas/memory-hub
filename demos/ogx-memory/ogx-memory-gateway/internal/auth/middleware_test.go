package auth_test

import (
	"errors"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/fips-agents/gateway-template/internal/auth"
)

// captureHandler records the headers of the request that reaches it so
// tests can assert on what the middleware projected.
type captureHandler struct {
	got http.Header
}

func (c *captureHandler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	c.got = r.Header.Clone()
	w.WriteHeader(http.StatusNoContent)
}

func TestMiddleware_AnonymousProjectsCanonicalHeaders(t *testing.T) {
	cap := &captureHandler{}
	mw := auth.Middleware(&auth.AnonymousAuth{})
	h := mw(cap)

	req := httptest.NewRequest("POST", "/v1/feedback", nil)
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)

	if rec.Code != http.StatusNoContent {
		t.Fatalf("status: got %d, want 204", rec.Code)
	}
	if got := cap.got.Get(auth.HeaderSubject); got != "anonymous" {
		t.Errorf("X-Auth-Subject: got %q, want %q", got, "anonymous")
	}
	if got := cap.got.Get(auth.HeaderMode); got != auth.ModeAnonymous {
		t.Errorf("X-Auth-Mode: got %q, want %q", got, auth.ModeAnonymous)
	}
}

func TestMiddleware_StripsInboundSpoofedHeaders(t *testing.T) {
	cap := &captureHandler{}
	mw := auth.Middleware(&auth.AnonymousAuth{})
	h := mw(cap)

	req := httptest.NewRequest("POST", "/v1/feedback", nil)
	// Client tries to forge identity. Middleware must replace these with
	// the strategy's resolved identity.
	req.Header.Set("X-Auth-Subject", "evil-admin")
	req.Header.Set("X-Auth-User", "evil")
	req.Header.Set("X-Auth-Email", "evil@example.com")
	req.Header.Set("X-Auth-Mode", "proxy")

	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)

	if got := cap.got.Get(auth.HeaderSubject); got != "anonymous" {
		t.Errorf("forged X-Auth-Subject leaked through: got %q", got)
	}
	if got := cap.got.Get(auth.HeaderMode); got != auth.ModeAnonymous {
		t.Errorf("forged X-Auth-Mode leaked through: got %q", got)
	}
	if got := cap.got.Get(auth.HeaderUser); got != "" {
		t.Errorf("forged X-Auth-User leaked through: got %q", got)
	}
	if got := cap.got.Get(auth.HeaderEmail); got != "" {
		t.Errorf("forged X-Auth-Email leaked through: got %q", got)
	}
}

func TestMiddleware_ProxyModeProjectsUpstreamIdentity(t *testing.T) {
	cap := &captureHandler{}
	pa := &auth.ProxyAuth{UserHeader: "X-Forwarded-User", EmailHeader: "X-Forwarded-Email"}
	h := auth.Middleware(pa)(cap)

	req := httptest.NewRequest("POST", "/v1/feedback", nil)
	req.Header.Set("X-Forwarded-User", "alice")
	req.Header.Set("X-Forwarded-Email", "alice@example.com")

	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)

	if got := cap.got.Get(auth.HeaderSubject); got != "alice" {
		t.Errorf("X-Auth-Subject: got %q, want alice", got)
	}
	if got := cap.got.Get(auth.HeaderUser); got != "alice" {
		t.Errorf("X-Auth-User: got %q, want alice", got)
	}
	if got := cap.got.Get(auth.HeaderEmail); got != "alice@example.com" {
		t.Errorf("X-Auth-Email: got %q, want alice@example.com", got)
	}
	if got := cap.got.Get(auth.HeaderMode); got != auth.ModeProxy {
		t.Errorf("X-Auth-Mode: got %q, want proxy", got)
	}
}

func TestMiddleware_ProxyModeFailsClosedOn503(t *testing.T) {
	called := false
	next := http.HandlerFunc(func(http.ResponseWriter, *http.Request) { called = true })

	pa := &auth.ProxyAuth{UserHeader: "X-Forwarded-User"}
	h := auth.Middleware(pa)(next)

	req := httptest.NewRequest("POST", "/v1/feedback", nil)
	// No X-Forwarded-User → ErrMissingProxyHeaders.
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)

	if rec.Code != http.StatusServiceUnavailable {
		t.Fatalf("status: got %d, want 503", rec.Code)
	}
	if called {
		t.Error("downstream handler ran despite auth failure")
	}
}

func TestMiddleware_HealthProbesBypassAuth(t *testing.T) {
	// In proxy mode the kubelet's liveness/readiness probes hit the
	// gateway directly with no X-Forwarded-User, which would otherwise
	// trip ErrMissingProxyHeaders → 503 → crash loop. The middleware
	// must let probe paths through unauthenticated.
	cap := &captureHandler{}
	pa := &auth.ProxyAuth{UserHeader: "X-Forwarded-User"}
	h := auth.Middleware(pa)(cap)

	for _, path := range []string{"/healthz", "/readyz", "/.well-known/agent.json"} {
		req := httptest.NewRequest("GET", path, nil)
		rec := httptest.NewRecorder()
		h.ServeHTTP(rec, req)
		if rec.Code == http.StatusServiceUnavailable {
			t.Errorf("path %q: probe path should bypass auth, got 503", path)
		}
	}
}

func TestMiddleware_HealthProbesStillStripSpoofedHeaders(t *testing.T) {
	// Probe paths bypass the strategy but must still strip inbound
	// X-Auth-* so they can't be used as a spoof channel.
	cap := &captureHandler{}
	h := auth.Middleware(&auth.AnonymousAuth{})(cap)

	req := httptest.NewRequest("GET", "/healthz", nil)
	req.Header.Set("X-Auth-Subject", "evil")
	req.Header.Set("X-Auth-User", "evil")
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)

	if got := cap.got.Get("X-Auth-Subject"); got != "" {
		t.Errorf("inbound X-Auth-Subject leaked through probe path: got %q", got)
	}
}

// TestMiddleware_GenericErrorReturns503 ensures that any non-sentinel
// error from the authenticator (deployment-level failure) causes a 503.
func TestMiddleware_GenericErrorReturns503(t *testing.T) {
	called := false
	next := http.HandlerFunc(func(http.ResponseWriter, *http.Request) { called = true })

	stub := stubAuth{err: errors.New("boom")}
	h := auth.Middleware(stub)(next)

	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, httptest.NewRequest("GET", "/", nil))

	if rec.Code != http.StatusServiceUnavailable {
		t.Fatalf("want 503, got %d", rec.Code)
	}
	if called {
		t.Error("downstream handler ran despite auth error")
	}
}

// TestMiddleware_InvalidTokenReturns401 ensures ErrInvalidToken is
// distinguished from deployment-level failures and produces 401.
func TestMiddleware_InvalidTokenReturns401(t *testing.T) {
	called := false
	next := http.HandlerFunc(func(http.ResponseWriter, *http.Request) { called = true })

	stub := stubAuth{err: auth.ErrInvalidToken}
	h := auth.Middleware(stub)(next)

	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, httptest.NewRequest("GET", "/", nil))

	if rec.Code != http.StatusUnauthorized {
		t.Fatalf("want 401, got %d", rec.Code)
	}
	if called {
		t.Error("downstream handler ran despite auth error")
	}
}

// TestMiddleware_WrappedInvalidTokenReturns401 ensures errors.Is unwrapping
// works so jwt.go can wrap ErrInvalidToken with details.
func TestMiddleware_WrappedInvalidTokenReturns401(t *testing.T) {
	stub := stubAuth{err: errors.Join(auth.ErrInvalidToken, errors.New("token expired"))}
	h := auth.Middleware(stub)(http.HandlerFunc(func(http.ResponseWriter, *http.Request) {}))

	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, httptest.NewRequest("GET", "/", nil))

	if rec.Code != http.StatusUnauthorized {
		t.Fatalf("want 401, got %d", rec.Code)
	}
}

type stubAuth struct {
	id  auth.Identity
	err error
}

func (s stubAuth) Authenticate(*http.Request) (auth.Identity, error) {
	return s.id, s.err
}

// TestMiddleware_StripsInboundAuthorizationByDefault ensures that, when the
// strategy resolves an Identity without a BearerToken, the inbound
// Authorization header does not leak through to the handler. The gateway
// should never forward a bearer token it has not derived itself.
func TestMiddleware_StripsInboundAuthorizationByDefault(t *testing.T) {
	cap := &captureHandler{}
	h := auth.Middleware(&auth.AnonymousAuth{})(cap)

	req := httptest.NewRequest("POST", "/v1/feedback", nil)
	req.Header.Set("Authorization", "Bearer raw-user-jwt")

	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)

	if got := cap.got.Get("Authorization"); got != "" {
		t.Errorf("inbound Authorization leaked through: got %q", got)
	}
}

// TestMiddleware_ProjectsBearerTokenFromIdentity verifies that when the
// strategy populates Identity.BearerToken (e.g. an RFC 8693 swapped token),
// the middleware writes it as `Authorization: Bearer <token>` so handlers
// can forward it to the backend.
func TestMiddleware_ProjectsBearerTokenFromIdentity(t *testing.T) {
	cap := &captureHandler{}
	stub := stubAuth{id: auth.Identity{
		Subject:     "user-123",
		Mode:        auth.ModeJWT,
		BearerToken: "swapped-for-backend",
	}}
	h := auth.Middleware(stub)(cap)

	req := httptest.NewRequest("POST", "/v1/chat/completions", nil)
	// Inbound Authorization (the user's JWT) must be replaced by the swap.
	req.Header.Set("Authorization", "Bearer raw-user-jwt")

	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)

	if got := cap.got.Get("Authorization"); got != "Bearer swapped-for-backend" {
		t.Errorf("Authorization: got %q, want %q", got, "Bearer swapped-for-backend")
	}
}

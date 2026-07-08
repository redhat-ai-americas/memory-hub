package auth_test

import (
	"crypto/rand"
	"crypto/rsa"
	"crypto/sha256"
	"crypto/x509"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"sync/atomic"
	"testing"
	"time"

	"github.com/fips-agents/gateway-template/internal/auth"
	"github.com/golang-jwt/jwt/v5"
)

// jwksFixture is a minimal JWKS server backed by an RSA keypair. It tracks
// fetch attempts so tests can assert cache behaviour, and supports forcing
// a 503 to simulate Keycloak unavailability.
type jwksFixture struct {
	priv     *rsa.PrivateKey
	kid      string
	server   *httptest.Server
	fetches  atomic.Int64
	failNext atomic.Bool
}

func newJWKSFixture(t *testing.T) *jwksFixture {
	t.Helper()
	priv, err := rsa.GenerateKey(rand.Reader, 2048)
	if err != nil {
		t.Fatalf("rsa.GenerateKey: %v", err)
	}
	// Derive a stable kid from the public modulus.
	hash := sha256.Sum256(priv.PublicKey.N.Bytes())
	kid := base64.RawURLEncoding.EncodeToString(hash[:8])

	f := &jwksFixture{priv: priv, kid: kid}
	f.server = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		f.fetches.Add(1)
		if f.failNext.Load() {
			w.WriteHeader(http.StatusServiceUnavailable)
			return
		}
		n := base64.RawURLEncoding.EncodeToString(priv.PublicKey.N.Bytes())
		// Encode public exponent as big-endian, trim leading zero bytes.
		eBytes := []byte{
			byte(priv.PublicKey.E >> 16),
			byte(priv.PublicKey.E >> 8),
			byte(priv.PublicKey.E),
		}
		for len(eBytes) > 1 && eBytes[0] == 0 {
			eBytes = eBytes[1:]
		}
		e := base64.RawURLEncoding.EncodeToString(eBytes)
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(map[string]any{
			"keys": []map[string]any{
				{
					"kty": "RSA",
					"alg": "RS256",
					"use": "sig",
					"kid": f.kid,
					"n":   n,
					"e":   e,
				},
			},
		})
	}))
	t.Cleanup(f.server.Close)
	return f
}

// signToken signs a token with the fixture's key. claims overrides the
// default exp/nbf/iss/aud — pass any subset.
func (f *jwksFixture) signToken(t *testing.T, claims jwt.MapClaims, kid string) string {
	t.Helper()
	if kid == "" {
		kid = f.kid
	}
	tok := jwt.NewWithClaims(jwt.SigningMethodRS256, claims)
	tok.Header["kid"] = kid
	signed, err := tok.SignedString(f.priv)
	if err != nil {
		t.Fatalf("SignedString: %v", err)
	}
	return signed
}

// signWithOtherKey signs with a fresh key the JWKS does not advertise.
func (f *jwksFixture) signWithOtherKey(t *testing.T, claims jwt.MapClaims, kid string) string {
	t.Helper()
	other, err := rsa.GenerateKey(rand.Reader, 2048)
	if err != nil {
		t.Fatalf("rsa.GenerateKey: %v", err)
	}
	tok := jwt.NewWithClaims(jwt.SigningMethodRS256, claims)
	tok.Header["kid"] = kid
	// Discard the public key; we only need the signature to fail validation.
	_ = x509.MarshalPKCS1PublicKey(&other.PublicKey)
	signed, err := tok.SignedString(other)
	if err != nil {
		t.Fatalf("SignedString: %v", err)
	}
	return signed
}

// defaultClaims returns a baseline set of valid claims.
func defaultClaims(iss, aud string) jwt.MapClaims {
	now := time.Now()
	return jwt.MapClaims{
		"iss":                iss,
		"aud":                aud,
		"sub":                "user-123",
		"preferred_username": "alice",
		"email":              "alice@example.com",
		"iat":                now.Unix(),
		"nbf":                now.Add(-1 * time.Minute).Unix(),
		"exp":                now.Add(5 * time.Minute).Unix(),
	}
}

func newJWTAuth(t *testing.T, f *jwksFixture, iss, aud string) auth.Authenticator {
	t.Helper()
	a, err := auth.New(auth.ModeJWT, auth.Options{
		JWT: auth.JWTConfig{
			JWKSURL:  f.server.URL,
			Issuer:   iss,
			Audience: aud,
		},
	})
	if err != nil {
		t.Fatalf("New(jwt): %v", err)
	}
	return a
}

func reqWithBearer(token string) *http.Request {
	r := httptest.NewRequest("POST", "/v1/chat/completions", nil)
	if token != "" {
		r.Header.Set("Authorization", "Bearer "+token)
	}
	return r
}

const (
	testIssuer   = "https://kc.example/realms/test"
	testAudience = "gateway-template"
)

func TestJWTAuth_HappyPath(t *testing.T) {
	f := newJWKSFixture(t)
	a := newJWTAuth(t, f, testIssuer, testAudience)

	tok := f.signToken(t, defaultClaims(testIssuer, testAudience), "")
	id, err := a.Authenticate(reqWithBearer(tok))
	if err != nil {
		t.Fatalf("Authenticate: %v", err)
	}
	want := auth.Identity{
		Subject: "user-123",
		User:    "alice",
		Email:   "alice@example.com",
		Mode:    auth.ModeJWT,
	}
	if id != want {
		t.Errorf("identity: got %+v, want %+v", id, want)
	}
}

func TestJWTAuth_RejectsExpired(t *testing.T) {
	f := newJWKSFixture(t)
	a := newJWTAuth(t, f, testIssuer, testAudience)

	c := defaultClaims(testIssuer, testAudience)
	c["exp"] = time.Now().Add(-2 * time.Minute).Unix()
	tok := f.signToken(t, c, "")

	_, err := a.Authenticate(reqWithBearer(tok))
	if !errors.Is(err, auth.ErrInvalidToken) {
		t.Fatalf("want ErrInvalidToken, got %v", err)
	}
}

func TestJWTAuth_RejectsNotYetValid(t *testing.T) {
	f := newJWKSFixture(t)
	a := newJWTAuth(t, f, testIssuer, testAudience)

	c := defaultClaims(testIssuer, testAudience)
	// Push nbf well past the parser's 30s leeway.
	c["nbf"] = time.Now().Add(5 * time.Minute).Unix()
	tok := f.signToken(t, c, "")

	_, err := a.Authenticate(reqWithBearer(tok))
	if !errors.Is(err, auth.ErrInvalidToken) {
		t.Fatalf("want ErrInvalidToken, got %v", err)
	}
}

func TestJWTAuth_RejectsWrongIssuer(t *testing.T) {
	f := newJWKSFixture(t)
	a := newJWTAuth(t, f, testIssuer, testAudience)

	tok := f.signToken(t, defaultClaims("https://other.example/realms/x", testAudience), "")
	_, err := a.Authenticate(reqWithBearer(tok))
	if !errors.Is(err, auth.ErrInvalidToken) {
		t.Fatalf("want ErrInvalidToken, got %v", err)
	}
}

func TestJWTAuth_RejectsWrongAudience(t *testing.T) {
	f := newJWKSFixture(t)
	a := newJWTAuth(t, f, testIssuer, testAudience)

	tok := f.signToken(t, defaultClaims(testIssuer, "some-other-service"), "")
	_, err := a.Authenticate(reqWithBearer(tok))
	if !errors.Is(err, auth.ErrInvalidToken) {
		t.Fatalf("want ErrInvalidToken, got %v", err)
	}
}

func TestJWTAuth_RejectsBadSignature(t *testing.T) {
	f := newJWKSFixture(t)
	a := newJWTAuth(t, f, testIssuer, testAudience)

	// Sign with a key the JWKS does not advertise, but advertise our kid
	// so the validator fetches the real public key and rejects the signature.
	tok := f.signWithOtherKey(t, defaultClaims(testIssuer, testAudience), f.kid)
	_, err := a.Authenticate(reqWithBearer(tok))
	if !errors.Is(err, auth.ErrInvalidToken) {
		t.Fatalf("want ErrInvalidToken, got %v", err)
	}
}

func TestJWTAuth_RejectsUnknownKid(t *testing.T) {
	f := newJWKSFixture(t)
	a := newJWTAuth(t, f, testIssuer, testAudience)

	tok := f.signToken(t, defaultClaims(testIssuer, testAudience), "kid-not-in-jwks")
	_, err := a.Authenticate(reqWithBearer(tok))
	if !errors.Is(err, auth.ErrInvalidToken) {
		t.Fatalf("want ErrInvalidToken, got %v", err)
	}
}

func TestJWTAuth_RejectsMissingAuthorization(t *testing.T) {
	f := newJWKSFixture(t)
	a := newJWTAuth(t, f, testIssuer, testAudience)

	_, err := a.Authenticate(reqWithBearer(""))
	if !errors.Is(err, auth.ErrInvalidToken) {
		t.Fatalf("want ErrInvalidToken, got %v", err)
	}
}

func TestJWTAuth_RejectsMalformedAuthorization(t *testing.T) {
	f := newJWKSFixture(t)
	a := newJWTAuth(t, f, testIssuer, testAudience)

	r := httptest.NewRequest("POST", "/v1/chat/completions", nil)
	// Wrong scheme.
	r.Header.Set("Authorization", "Basic dXNlcjpwYXNz")

	_, err := a.Authenticate(r)
	if !errors.Is(err, auth.ErrInvalidToken) {
		t.Fatalf("want ErrInvalidToken, got %v", err)
	}
}

func TestJWTAuth_RejectsMissingSubjectClaim(t *testing.T) {
	f := newJWKSFixture(t)
	a := newJWTAuth(t, f, testIssuer, testAudience)

	c := defaultClaims(testIssuer, testAudience)
	delete(c, "sub")
	tok := f.signToken(t, c, "")

	_, err := a.Authenticate(reqWithBearer(tok))
	if !errors.Is(err, auth.ErrInvalidToken) {
		t.Fatalf("want ErrInvalidToken, got %v", err)
	}
}

func TestJWTAuth_CustomClaimMapping(t *testing.T) {
	f := newJWKSFixture(t)
	a, err := auth.New(auth.ModeJWT, auth.Options{
		JWT: auth.JWTConfig{
			JWKSURL:      f.server.URL,
			Issuer:       testIssuer,
			Audience:     testAudience,
			SubjectClaim: "uid",
			UserClaim:    "username",
			EmailClaim:   "mail",
		},
	})
	if err != nil {
		t.Fatalf("New: %v", err)
	}

	c := defaultClaims(testIssuer, testAudience)
	c["uid"] = "u-7"
	c["username"] = "bob"
	c["mail"] = "bob@x.test"

	tok := f.signToken(t, c, "")
	id, err := a.Authenticate(reqWithBearer(tok))
	if err != nil {
		t.Fatalf("Authenticate: %v", err)
	}
	want := auth.Identity{
		Subject: "u-7",
		User:    "bob",
		Email:   "bob@x.test",
		Mode:    auth.ModeJWT,
	}
	if id != want {
		t.Errorf("identity: got %+v, want %+v", id, want)
	}
}

func TestJWTAuth_WarmCacheSurvivesJWKSOutage(t *testing.T) {
	f := newJWKSFixture(t)
	a := newJWTAuth(t, f, testIssuer, testAudience)

	// First call populates the cache.
	tok := f.signToken(t, defaultClaims(testIssuer, testAudience), "")
	if _, err := a.Authenticate(reqWithBearer(tok)); err != nil {
		t.Fatalf("warmup Authenticate: %v", err)
	}

	// Now break the JWKS endpoint and verify another valid token still works.
	f.failNext.Store(true)

	tok2 := f.signToken(t, defaultClaims(testIssuer, testAudience), "")
	if _, err := a.Authenticate(reqWithBearer(tok2)); err != nil {
		t.Fatalf("post-outage Authenticate: %v (cache should have served us)", err)
	}
}

func TestJWTAuth_RejectsNoneAlg(t *testing.T) {
	// Defence against the classic "alg=none" downgrade. The parser is
	// configured with WithValidMethods so unsigned tokens must fail.
	f := newJWKSFixture(t)
	a := newJWTAuth(t, f, testIssuer, testAudience)

	tok := jwt.NewWithClaims(jwt.SigningMethodNone, defaultClaims(testIssuer, testAudience))
	tok.Header["kid"] = f.kid
	signed, err := tok.SignedString(jwt.UnsafeAllowNoneSignatureType)
	if err != nil {
		t.Fatalf("SignedString: %v", err)
	}

	_, err = a.Authenticate(reqWithBearer(signed))
	if !errors.Is(err, auth.ErrInvalidToken) {
		t.Fatalf("want ErrInvalidToken for alg=none, got %v", err)
	}
}

// newJWTAuthWithExchanger constructs a JWTAuth backed by f's JWKS and the
// supplied TokenExchanger. Mirrors newJWTAuth but exercises the exchange
// path so we can assert Identity.BearerToken behaviour.
func newJWTAuthWithExchanger(t *testing.T, f *jwksFixture, ex *auth.TokenExchanger) auth.Authenticator {
	t.Helper()
	a, err := auth.New(auth.ModeJWT, auth.Options{
		JWT: auth.JWTConfig{
			JWKSURL:  f.server.URL,
			Issuer:   testIssuer,
			Audience: testAudience,
		},
		JWTExchanger: ex,
	})
	if err != nil {
		t.Fatalf("New(jwt+exchanger): %v", err)
	}
	return a
}

func TestJWTAuth_WithExchanger_PopulatesBearerToken(t *testing.T) {
	f := newJWKSFixture(t)
	xf := newExchangeFixture(t)
	xf.accessToken = "swapped-for-backend"

	ex := newExchanger(t, xf)
	a := newJWTAuthWithExchanger(t, f, ex)

	tok := f.signToken(t, defaultClaims(testIssuer, testAudience), "")
	id, err := a.Authenticate(reqWithBearer(tok))
	if err != nil {
		t.Fatalf("Authenticate: %v", err)
	}
	if id.BearerToken != "swapped-for-backend" {
		t.Errorf("Identity.BearerToken: got %q, want %q", id.BearerToken, "swapped-for-backend")
	}
	// Other identity fields should still resolve from the inbound JWT.
	if id.Subject != "user-123" || id.Mode != auth.ModeJWT {
		t.Errorf("identity: got %+v", id)
	}
	if got := xf.calls.Load(); got != 1 {
		t.Errorf("expected 1 token-exchange call, got %d", got)
	}
	// The exchange must receive the inbound subject token verbatim.
	if got := xf.lastForm.Get("subject_token"); got != tok {
		t.Errorf("exchange subject_token: got %q, want inbound JWT", got)
	}
}

func TestJWTAuth_WithExchanger_FailureSurfacesAsExchangeFailed(t *testing.T) {
	f := newJWKSFixture(t)
	xf := newExchangeFixture(t)
	xf.status = http.StatusBadGateway

	ex := newExchanger(t, xf)
	a := newJWTAuthWithExchanger(t, f, ex)

	tok := f.signToken(t, defaultClaims(testIssuer, testAudience), "")
	_, err := a.Authenticate(reqWithBearer(tok))
	if !errors.Is(err, auth.ErrExchangeFailed) {
		t.Fatalf("want ErrExchangeFailed, got %v", err)
	}
	// Crucially: NOT ErrInvalidToken. The middleware must distinguish
	// degraded-deployment failures from caller-token failures.
	if errors.Is(err, auth.ErrInvalidToken) {
		t.Errorf("exchange failure must not present as ErrInvalidToken: %v", err)
	}
}

func TestJWTAuth_WithoutExchanger_LeavesBearerTokenEmpty(t *testing.T) {
	f := newJWKSFixture(t)
	a := newJWTAuth(t, f, testIssuer, testAudience)

	tok := f.signToken(t, defaultClaims(testIssuer, testAudience), "")
	id, err := a.Authenticate(reqWithBearer(tok))
	if err != nil {
		t.Fatalf("Authenticate: %v", err)
	}
	if id.BearerToken != "" {
		t.Errorf("Identity.BearerToken should be empty when no exchanger configured, got %q", id.BearerToken)
	}
}

// Sanity check that the fixture itself round-trips, so a real failure in
// the validation path can be told apart from a fixture bug.
func TestJWKSFixture_RoundTrip(t *testing.T) {
	f := newJWKSFixture(t)
	tok := f.signToken(t, defaultClaims(testIssuer, testAudience), "")
	if tok == "" {
		t.Fatal("signed token should not be empty")
	}
	resp, err := http.Get(f.server.URL)
	if err != nil {
		t.Fatalf("GET JWKS: %v", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("JWKS status: %d", resp.StatusCode)
	}
	if got := f.fetches.Load(); got < 1 {
		t.Errorf("expected at least 1 JWKS fetch, got %d", got)
	}
	// Silence unused-import warnings for fmt when test fails are commented out.
	_ = fmt.Sprintf
}

func TestJWTAuth_AcceptsJWKSRefreshRateLimit(t *testing.T) {
	// Smoke test: NewJWTAuth must accept a JWKSRefreshRateLimit field
	// without erroring. The keyfunc/jwkset internals enforce the
	// limiter; we only assert that our wiring builds the auth object
	// successfully and validates a normal token.
	f := newJWKSFixture(t)
	a, err := auth.New(auth.ModeJWT, auth.Options{
		JWT: auth.JWTConfig{
			JWKSURL:              f.server.URL,
			Issuer:               testIssuer,
			Audience:             testAudience,
			JWKSRefreshRateLimit: 50 * time.Millisecond,
		},
	})
	if err != nil {
		t.Fatalf("New(jwt) with refresh-rate-limit: %v", err)
	}
	tok := f.signToken(t, defaultClaims(testIssuer, testAudience), "")
	if _, err := a.Authenticate(reqWithBearer(tok)); err != nil {
		t.Fatalf("Authenticate (rate-limit configured): %v", err)
	}
}

func TestJWTAuth_UnknownKidRefreshIsRateLimited(t *testing.T) {
	// keyfunc/jwkset implements the limiter via rate.Limiter.Wait,
	// which blocks the unknown-kid lookup until the limiter allows
	// the next refresh — it serialises rather than skips. So the
	// observable signal that the limiter is wired through is
	// elapsed wall time across a burst of unknown-kid tokens.
	//
	// With a 200ms rate-every and three forged-kid requests, the
	// first goes through immediately and the next two each wait
	// ~200ms — total ~400ms elapsed. Without the limiter (or with
	// it broken), all three would resolve in milliseconds.
	f := newJWKSFixture(t)
	a, err := auth.New(auth.ModeJWT, auth.Options{
		JWT: auth.JWTConfig{
			JWKSURL:              f.server.URL,
			Issuer:               testIssuer,
			Audience:             testAudience,
			JWKSRefreshRateLimit: 200 * time.Millisecond,
		},
	})
	if err != nil {
		t.Fatalf("New(jwt): %v", err)
	}

	// Warm the cache with one valid request so the startup fetch
	// isn't part of the elapsed-time measurement.
	tok := f.signToken(t, defaultClaims(testIssuer, testAudience), "")
	if _, err := a.Authenticate(reqWithBearer(tok)); err != nil {
		t.Fatalf("warm-up Authenticate: %v", err)
	}

	start := time.Now()
	for i := 0; i < 3; i++ {
		c := defaultClaims(testIssuer, testAudience)
		forged := f.signToken(t, c, fmt.Sprintf("forged-kid-%d", i))
		_, _ = a.Authenticate(reqWithBearer(forged))
	}
	elapsed := time.Since(start)

	// First request consumes the burst-1 token immediately. The
	// remaining two wait ~200ms each — at least 300ms total is a
	// safe lower bound that still tolerates timer jitter.
	if elapsed < 300*time.Millisecond {
		t.Errorf("limiter not engaged: elapsed=%v across 3 forged-kid requests (want >= 300ms)", elapsed)
	}
}

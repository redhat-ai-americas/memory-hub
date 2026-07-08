package auth_test

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"net/url"
	"sync/atomic"
	"testing"
	"time"

	"github.com/fips-agents/gateway-template/internal/auth"
)

// exchangeFixture stands in for an RFC 8693 token endpoint. It records every
// inbound request so tests can assert on form fields and cache behaviour.
type exchangeFixture struct {
	server      *httptest.Server
	calls       atomic.Int64
	lastForm    url.Values
	lastHeaders http.Header

	// response controls the next reply.
	status      int
	accessToken string
	expiresIn   int
	body        string // when non-empty, used verbatim and JSON encoding is skipped
}

func newExchangeFixture(t *testing.T) *exchangeFixture {
	t.Helper()
	f := &exchangeFixture{
		status:      http.StatusOK,
		accessToken: "swapped-token-XYZ",
		expiresIn:   300,
	}
	f.server = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		f.calls.Add(1)
		_ = r.ParseForm()
		f.lastForm = r.PostForm
		f.lastHeaders = r.Header.Clone()
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(f.status)
		if f.body != "" {
			_, _ = w.Write([]byte(f.body))
			return
		}
		_, _ = fmt.Fprintf(w, `{"access_token":%q,"token_type":"Bearer","expires_in":%d}`, f.accessToken, f.expiresIn)
	}))
	t.Cleanup(f.server.Close)
	return f
}

func newExchanger(t *testing.T, f *exchangeFixture, opts ...func(*auth.TokenExchangeConfig)) *auth.TokenExchanger {
	t.Helper()
	cfg := auth.TokenExchangeConfig{
		TokenURL:     f.server.URL,
		ClientID:     "gw-svc",
		ClientSecret: "shh",
		Audience:     "backend-agent",
		HTTPClient:   f.server.Client(),
	}
	for _, opt := range opts {
		opt(&cfg)
	}
	ex, err := auth.NewTokenExchanger(cfg)
	if err != nil {
		t.Fatalf("NewTokenExchanger: %v", err)
	}
	return ex
}

func TestNewTokenExchanger_RequiresFields(t *testing.T) {
	cases := []struct {
		name string
		mut  func(*auth.TokenExchangeConfig)
	}{
		{"missing token url", func(c *auth.TokenExchangeConfig) { c.TokenURL = "" }},
		{"missing client id", func(c *auth.TokenExchangeConfig) { c.ClientID = "" }},
		{"missing client secret", func(c *auth.TokenExchangeConfig) { c.ClientSecret = "" }},
		{"missing audience", func(c *auth.TokenExchangeConfig) { c.Audience = "" }},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			cfg := auth.TokenExchangeConfig{
				TokenURL:     "https://kc/realms/x/protocol/openid-connect/token",
				ClientID:     "id",
				ClientSecret: "secret",
				Audience:     "aud",
			}
			tc.mut(&cfg)
			if _, err := auth.NewTokenExchanger(cfg); err == nil {
				t.Fatalf("expected error, got nil")
			}
		})
	}
}

func TestTokenExchanger_HappyPath_PostsRFC8693Form(t *testing.T) {
	f := newExchangeFixture(t)
	ex := newExchanger(t, f, func(c *auth.TokenExchangeConfig) { c.Scope = "openid email" })

	got, err := ex.Exchange(context.Background(), "user-jwt-input", nil)
	if err != nil {
		t.Fatalf("Exchange: %v", err)
	}
	if got != "swapped-token-XYZ" {
		t.Errorf("Exchange returned %q, want %q", got, "swapped-token-XYZ")
	}
	if f.calls.Load() != 1 {
		t.Errorf("expected 1 token-endpoint call, got %d", f.calls.Load())
	}

	want := map[string]string{
		"grant_type":           "urn:ietf:params:oauth:grant-type:token-exchange",
		"subject_token":        "user-jwt-input",
		"subject_token_type":   "urn:ietf:params:oauth:token-type:access_token",
		"requested_token_type": "urn:ietf:params:oauth:token-type:access_token",
		"audience":             "backend-agent",
		"client_id":            "gw-svc",
		"client_secret":        "shh",
		"scope":                "openid email",
	}
	for k, v := range want {
		if got := f.lastForm.Get(k); got != v {
			t.Errorf("form[%s] = %q, want %q", k, got, v)
		}
	}
}

func TestTokenExchanger_PropagatesTraceContext(t *testing.T) {
	// W3C Trace Context headers (traceparent / tracestate) on the inbound
	// user request must land on the outbound POST to the authorization
	// server's token endpoint, so trace tooling can correlate exchange-call
	// latency with the user request that triggered it.
	f := newExchangeFixture(t)
	ex := newExchanger(t, f)

	inbound := http.Header{}
	inbound.Set("Traceparent", "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01")
	inbound.Set("Tracestate", "vendor=opaque-state")

	if _, err := ex.Exchange(context.Background(), "user-jwt", inbound); err != nil {
		t.Fatalf("Exchange: %v", err)
	}
	if got := f.lastHeaders.Get("Traceparent"); got != "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01" {
		t.Errorf("Traceparent on token-endpoint call = %q, want propagated value", got)
	}
	if got := f.lastHeaders.Get("Tracestate"); got != "vendor=opaque-state" {
		t.Errorf("Tracestate on token-endpoint call = %q, want propagated value", got)
	}
}

func TestTokenExchanger_NilHeadersOmitsPropagation(t *testing.T) {
	// Programmatic / test callers pass nil; the exchanger must not blow up
	// and must not invent headers the inbound request didn't carry.
	f := newExchangeFixture(t)
	ex := newExchanger(t, f)

	if _, err := ex.Exchange(context.Background(), "user-jwt", nil); err != nil {
		t.Fatalf("Exchange: %v", err)
	}
	if got := f.lastHeaders.Get("Traceparent"); got != "" {
		t.Errorf("Traceparent should be absent when inbound headers nil, got %q", got)
	}
}

func TestTokenExchanger_OmitsScopeWhenEmpty(t *testing.T) {
	f := newExchangeFixture(t)
	ex := newExchanger(t, f)

	if _, err := ex.Exchange(context.Background(), "user-jwt", nil); err != nil {
		t.Fatalf("Exchange: %v", err)
	}
	if _, present := f.lastForm["scope"]; present {
		t.Errorf("scope should be omitted when not configured, got form %+v", f.lastForm)
	}
}

func TestTokenExchanger_CachesByToken(t *testing.T) {
	f := newExchangeFixture(t)
	ex := newExchanger(t, f)

	for i := 0; i < 3; i++ {
		got, err := ex.Exchange(context.Background(), "same-input", nil)
		if err != nil {
			t.Fatalf("Exchange (iter %d): %v", i, err)
		}
		if got != "swapped-token-XYZ" {
			t.Errorf("Exchange returned %q", got)
		}
	}
	if got := f.calls.Load(); got != 1 {
		t.Errorf("expected 1 token-endpoint call (cache hits after first), got %d", got)
	}

	// A different subject token must trigger a fresh call.
	if _, err := ex.Exchange(context.Background(), "different-input", nil); err != nil {
		t.Fatalf("Exchange (different input): %v", err)
	}
	if got := f.calls.Load(); got != 2 {
		t.Errorf("expected 2 calls after distinct input, got %d", got)
	}
}

func TestTokenExchanger_CacheRespectsExpiry(t *testing.T) {
	f := newExchangeFixture(t)
	f.expiresIn = 60 // 60s server TTL → 30s effective cache TTL after safety margin.

	clock := time.Now()
	ex := newExchanger(t, f, func(c *auth.TokenExchangeConfig) {
		c.Now = func() time.Time { return clock }
	})

	if _, err := ex.Exchange(context.Background(), "tok", nil); err != nil {
		t.Fatalf("first Exchange: %v", err)
	}
	if got := f.calls.Load(); got != 1 {
		t.Errorf("expected 1 call, got %d", got)
	}

	// Within cache TTL → no new call.
	clock = clock.Add(20 * time.Second)
	if _, err := ex.Exchange(context.Background(), "tok", nil); err != nil {
		t.Fatalf("cached Exchange: %v", err)
	}
	if got := f.calls.Load(); got != 1 {
		t.Errorf("expected 1 call (cache hit), got %d", got)
	}

	// Past cache TTL (server expires_in 60s − 30s safety margin = 30s cap),
	// jumping 45s forward should evict.
	clock = clock.Add(45 * time.Second)
	if _, err := ex.Exchange(context.Background(), "tok", nil); err != nil {
		t.Fatalf("post-expiry Exchange: %v", err)
	}
	if got := f.calls.Load(); got != 2 {
		t.Errorf("expected 2 calls (cache expired), got %d", got)
	}
}

func TestTokenExchanger_DoesNotCacheNearExpiryTokens(t *testing.T) {
	f := newExchangeFixture(t)
	f.expiresIn = 20 // less than 30s safety margin → never cache

	ex := newExchanger(t, f)

	for i := 0; i < 3; i++ {
		if _, err := ex.Exchange(context.Background(), "tok", nil); err != nil {
			t.Fatalf("Exchange (iter %d): %v", i, err)
		}
	}
	if got := f.calls.Load(); got != 3 {
		t.Errorf("expected 3 calls when ttl < safety margin, got %d", got)
	}
}

func TestTokenExchanger_HonoursCacheTTLCap(t *testing.T) {
	f := newExchangeFixture(t)
	f.expiresIn = 3600 // server says 1h

	clock := time.Now()
	ex := newExchanger(t, f, func(c *auth.TokenExchangeConfig) {
		c.Now = func() time.Time { return clock }
		c.CacheTTLCap = 2 * time.Minute
	})

	if _, err := ex.Exchange(context.Background(), "tok", nil); err != nil {
		t.Fatalf("first Exchange: %v", err)
	}
	// Cap should kick in well before the server's 1h.
	clock = clock.Add(3 * time.Minute)
	if _, err := ex.Exchange(context.Background(), "tok", nil); err != nil {
		t.Fatalf("post-cap Exchange: %v", err)
	}
	if got := f.calls.Load(); got != 2 {
		t.Errorf("expected 2 calls after cache cap exceeded, got %d", got)
	}
}

func TestTokenExchanger_4xxFails(t *testing.T) {
	f := newExchangeFixture(t)
	f.status = http.StatusBadRequest
	f.body = `{"error":"invalid_grant"}`

	ex := newExchanger(t, f)

	_, err := ex.Exchange(context.Background(), "tok", nil)
	if !errors.Is(err, auth.ErrExchangeFailed) {
		t.Fatalf("want ErrExchangeFailed, got %v", err)
	}
}

func TestTokenExchanger_5xxFails(t *testing.T) {
	f := newExchangeFixture(t)
	f.status = http.StatusServiceUnavailable
	f.body = "upstream down"

	ex := newExchanger(t, f)

	_, err := ex.Exchange(context.Background(), "tok", nil)
	if !errors.Is(err, auth.ErrExchangeFailed) {
		t.Fatalf("want ErrExchangeFailed, got %v", err)
	}
}

func TestTokenExchanger_MalformedJSONFails(t *testing.T) {
	f := newExchangeFixture(t)
	f.body = "not json"

	ex := newExchanger(t, f)

	_, err := ex.Exchange(context.Background(), "tok", nil)
	if !errors.Is(err, auth.ErrExchangeFailed) {
		t.Fatalf("want ErrExchangeFailed, got %v", err)
	}
}

func TestTokenExchanger_MissingAccessTokenFails(t *testing.T) {
	f := newExchangeFixture(t)
	f.body = `{"token_type":"Bearer","expires_in":300}` // no access_token

	ex := newExchanger(t, f)

	_, err := ex.Exchange(context.Background(), "tok", nil)
	if !errors.Is(err, auth.ErrExchangeFailed) {
		t.Fatalf("want ErrExchangeFailed, got %v", err)
	}
}

func TestTokenExchanger_TransportErrorFails(t *testing.T) {
	// Point at an unreachable URL — no listener on this port.
	cfg := auth.TokenExchangeConfig{
		TokenURL:     "http://127.0.0.1:1/no-such-endpoint",
		ClientID:     "id",
		ClientSecret: "secret",
		Audience:     "aud",
		HTTPClient:   &http.Client{Timeout: 200 * time.Millisecond},
	}
	ex, err := auth.NewTokenExchanger(cfg)
	if err != nil {
		t.Fatalf("NewTokenExchanger: %v", err)
	}

	_, err = ex.Exchange(context.Background(), "tok", nil)
	if !errors.Is(err, auth.ErrExchangeFailed) {
		t.Fatalf("want ErrExchangeFailed, got %v", err)
	}
}

func TestTokenExchanger_RequestUsesContext(t *testing.T) {
	f := newExchangeFixture(t)
	ex := newExchanger(t, f)

	ctx, cancel := context.WithCancel(context.Background())
	cancel() // cancel immediately

	_, err := ex.Exchange(ctx, "tok", nil)
	if err == nil {
		t.Fatal("expected error from cancelled context")
	}
	// We don't require ErrExchangeFailed here because the canceled-context
	// failure path may surface as the URL error; we only assert that the
	// server was not actually contacted.
	if got := f.calls.Load(); got != 0 {
		t.Errorf("expected 0 endpoint calls under cancelled context, got %d", got)
	}
}

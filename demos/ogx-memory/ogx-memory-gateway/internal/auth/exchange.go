package auth

import (
	"context"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"sync"
	"time"
)

// RFC 8693 grant and token-type identifiers.
const (
	grantTypeTokenExchange = "urn:ietf:params:oauth:grant-type:token-exchange"
	tokenTypeAccessToken   = "urn:ietf:params:oauth:token-type:access_token"
)

// exchangePropagationHeaders are W3C Trace Context headers forwarded from
// the inbound user request onto the outbound POST to the authorization
// server's token endpoint. Lets trace tooling correlate exchange-call
// latency with the user request that triggered it.
var exchangePropagationHeaders = []string{
	"Traceparent",
	"Tracestate",
}

// ErrExchangeFailed signals that a token exchange call to the authorization
// server did not yield a usable swapped token. The middleware maps it to 503:
// a configured exchange that does not succeed means the gateway cannot vouch
// for the downstream call, so we fail closed rather than forward an
// unverifiable identity.
var ErrExchangeFailed = errors.New("auth: token exchange failed")

// TokenExchangeConfig is the parsed configuration for RFC 8693 token
// exchange. All fields except Scope, HTTPClient, CacheTTLCap, and Now are
// required.
type TokenExchangeConfig struct {
	// TokenURL is the authorization server's RFC 8693 token endpoint.
	TokenURL string
	// ClientID and ClientSecret authenticate the gateway as a confidential
	// client (client_secret_post).
	ClientID     string
	ClientSecret string
	// Audience is the resource indicator placed into the swapped token's
	// `aud` claim. v2 supports a single audience — the backend agent.
	Audience string
	// Scope is an optional space-separated scope set requested on the swap.
	// Empty means no scope narrowing.
	Scope string
	// HTTPClient lets tests inject a custom transport. nil → a 10s-timeout
	// http.Client.
	HTTPClient *http.Client
	// CacheTTLCap caps the cache TTL regardless of token expiry. nil/0 →
	// 5 minutes.
	CacheTTLCap time.Duration
	// Now lets tests inject a clock. nil → time.Now.
	Now func() time.Time
}

// TokenExchanger swaps an inbound subject token for a downstream-audienced
// token via RFC 8693. Results are cached in-process keyed by
// sha256(subject_token); the raw user JWT is not stored.
type TokenExchanger struct {
	cfg        TokenExchangeConfig
	httpClient *http.Client
	cache      sync.Map // string → cachedToken
	now        func() time.Time
	cacheCap   time.Duration
}

type cachedToken struct {
	token   string
	expires time.Time
}

// NewTokenExchanger validates the config and returns an exchanger ready to
// serve concurrent Exchange calls.
func NewTokenExchanger(cfg TokenExchangeConfig) (*TokenExchanger, error) {
	if cfg.TokenURL == "" {
		return nil, fmt.Errorf("auth: token exchange requires TokenURL")
	}
	if cfg.ClientID == "" {
		return nil, fmt.Errorf("auth: token exchange requires ClientID")
	}
	if cfg.ClientSecret == "" {
		return nil, fmt.Errorf("auth: token exchange requires ClientSecret")
	}
	if cfg.Audience == "" {
		return nil, fmt.Errorf("auth: token exchange requires Audience")
	}
	httpClient := cfg.HTTPClient
	if httpClient == nil {
		httpClient = &http.Client{Timeout: 10 * time.Second}
	}
	now := cfg.Now
	if now == nil {
		now = time.Now
	}
	cap := cfg.CacheTTLCap
	if cap <= 0 {
		cap = 5 * time.Minute
	}
	return &TokenExchanger{
		cfg:        cfg,
		httpClient: httpClient,
		now:        now,
		cacheCap:   cap,
	}, nil
}

// Exchange returns a swapped token for subjectToken, using the cache when
// the cached entry is still well within its TTL. Errors wrap
// ErrExchangeFailed so callers can distinguish degraded-deployment failures
// from caller-token failures (ErrInvalidToken).
//
// inboundHeaders carries W3C Trace Context (traceparent / tracestate) from
// the inbound request; on a cache miss the values are propagated onto the
// outbound POST to the authorization server so exchange-call latency lands
// under the same trace as the user request. Pass nil when no inbound
// headers are available (eg unit tests, programmatic use). Cache hits do
// not perform an outbound call, so headers are inspected only on miss.
func (e *TokenExchanger) Exchange(ctx context.Context, subjectToken string, inboundHeaders http.Header) (string, error) {
	key := cacheKey(subjectToken)
	if hit, ok := e.cache.Load(key); ok {
		ct := hit.(cachedToken)
		if e.now().Before(ct.expires) {
			return ct.token, nil
		}
		e.cache.Delete(key)
	}
	swapped, ttl, err := e.fetch(ctx, subjectToken, inboundHeaders)
	if err != nil {
		return "", err
	}
	// Subtract a 30s safety margin so we never forward a token that is
	// about to expire by the time the downstream validates it.
	cacheTTL := ttl - 30*time.Second
	if cacheTTL > e.cacheCap {
		cacheTTL = e.cacheCap
	}
	if cacheTTL > 0 {
		e.cache.Store(key, cachedToken{token: swapped, expires: e.now().Add(cacheTTL)})
	}
	return swapped, nil
}

// cacheKey hashes the subject token so the in-memory cache never holds the
// raw user JWT. SHA-256 is overkill for a cache key but cheap.
func cacheKey(token string) string {
	sum := sha256.Sum256([]byte(token))
	return base64.RawURLEncoding.EncodeToString(sum[:])
}

func (e *TokenExchanger) fetch(ctx context.Context, subjectToken string, inboundHeaders http.Header) (string, time.Duration, error) {
	form := url.Values{}
	form.Set("grant_type", grantTypeTokenExchange)
	form.Set("subject_token", subjectToken)
	form.Set("subject_token_type", tokenTypeAccessToken)
	form.Set("requested_token_type", tokenTypeAccessToken)
	form.Set("audience", e.cfg.Audience)
	form.Set("client_id", e.cfg.ClientID)
	form.Set("client_secret", e.cfg.ClientSecret)
	if e.cfg.Scope != "" {
		form.Set("scope", e.cfg.Scope)
	}

	req, err := http.NewRequestWithContext(ctx, http.MethodPost, e.cfg.TokenURL, strings.NewReader(form.Encode()))
	if err != nil {
		return "", 0, fmt.Errorf("%w: build request: %v", ErrExchangeFailed, err)
	}
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	req.Header.Set("Accept", "application/json")
	for _, name := range exchangePropagationHeaders {
		if v := inboundHeaders.Get(name); v != "" {
			req.Header.Set(name, v)
		}
	}

	resp, err := e.httpClient.Do(req)
	if err != nil {
		return "", 0, fmt.Errorf("%w: %v", ErrExchangeFailed, err)
	}
	defer resp.Body.Close()

	body, _ := io.ReadAll(io.LimitReader(resp.Body, 64*1024))
	if resp.StatusCode != http.StatusOK {
		return "", 0, fmt.Errorf("%w: %s: %s", ErrExchangeFailed, resp.Status, truncate(string(body), 256))
	}
	var payload struct {
		AccessToken string `json:"access_token"`
		ExpiresIn   int    `json:"expires_in"`
		TokenType   string `json:"token_type"`
	}
	if err := json.Unmarshal(body, &payload); err != nil {
		return "", 0, fmt.Errorf("%w: decode response: %v", ErrExchangeFailed, err)
	}
	if payload.AccessToken == "" {
		return "", 0, fmt.Errorf("%w: empty access_token in response", ErrExchangeFailed)
	}
	return payload.AccessToken, time.Duration(payload.ExpiresIn) * time.Second, nil
}

func truncate(s string, n int) string {
	if len(s) <= n {
		return s
	}
	return s[:n] + "…"
}

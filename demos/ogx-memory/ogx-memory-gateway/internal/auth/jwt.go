package auth

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"strings"
	"time"

	"github.com/MicahParks/keyfunc/v3"
	"github.com/golang-jwt/jwt/v5"
	"golang.org/x/time/rate"
)

// ErrInvalidToken signals that the inbound bearer token failed validation
// (bad signature, expired, wrong issuer/audience, malformed). The middleware
// maps it to 401 — distinct from ErrMissingProxyHeaders / generic auth errors
// which map to 503.
var ErrInvalidToken = errors.New("auth: invalid bearer token")

// ErrJWKSUnavailable signals that the JWKS endpoint could not be reached
// and the cache is cold (no keys to validate against). The middleware maps
// this to 503 — the deployment is degraded, not the caller's fault.
var ErrJWKSUnavailable = errors.New("auth: JWKS endpoint unavailable and cache is cold")

// JWTConfig is the parsed configuration for jwt mode. All fields are
// required except SubjectClaim/UserClaim/EmailClaim, which default to
// "sub" / "preferred_username" / "email", and JWKSRefreshRateLimit,
// which is optional and inherits the keyfunc default when zero.
type JWTConfig struct {
	JWKSURL      string
	Issuer       string
	Audience     string
	SubjectClaim string
	UserClaim    string
	EmailClaim   string

	// JWKSRefreshRateLimit caps how often the JWKS client will refresh
	// the remote key set in response to a token bearing a `kid` it has
	// not seen. When > 0 the underlying keyfunc client uses
	// rate.NewLimiter(rate.Every(d), 1); when 0 the keyfunc default of
	// 1 refresh per 5 minutes applies (i.e. zero means "use library
	// default", which is conservative enough for most deployments).
	//
	// Tune this when a noisy-neighbour burst with forged or unknown
	// `kid` values could otherwise hammer the JWKS endpoint. Lower
	// values increase JWKS load; higher values delay legitimate
	// post-rotation traffic by up to the configured interval.
	JWKSRefreshRateLimit time.Duration
}

// JWTAuth validates an inbound bearer token against a JWKS endpoint and
// projects the resolved claims onto a canonical Identity.
//
// Validation rules:
//   - Signature must verify against a key in the JWKS (matched by `kid`).
//   - `exp` must be in the future, `nbf` (if present) must not be in the future.
//   - `iss` must equal the configured issuer.
//   - `aud` must contain the configured audience.
//
// All failures collapse to ErrInvalidToken so the middleware emits a uniform
// 401 without leaking validation details to the caller. Detailed reasons are
// logged.
type JWTAuth struct {
	cfg       JWTConfig
	keyfunc   jwt.Keyfunc
	parser    *jwt.Parser
	exchanger *TokenExchanger
}

// NewJWTAuth constructs a JWTAuth. JWKS fetch happens lazily — the first
// request triggers a fetch, subsequent requests use the cache. This means
// the gateway can start up while Keycloak is still warming.
//
// exchanger is optional. When non-nil, every successful Authenticate call
// performs an RFC 8693 swap of the inbound subject token before returning,
// populating Identity.BearerToken with the swapped value.
//
// If you need eager JWKS warmup at startup, call (j *JWTAuth).Warm(ctx).
func NewJWTAuth(cfg JWTConfig, exchanger *TokenExchanger) (*JWTAuth, error) {
	if cfg.JWKSURL == "" {
		return nil, fmt.Errorf("auth: jwt mode requires JWKSURL")
	}
	if cfg.Issuer == "" {
		return nil, fmt.Errorf("auth: jwt mode requires Issuer")
	}
	if cfg.Audience == "" {
		return nil, fmt.Errorf("auth: jwt mode requires Audience")
	}
	if cfg.SubjectClaim == "" {
		cfg.SubjectClaim = "sub"
	}
	if cfg.UserClaim == "" {
		cfg.UserClaim = "preferred_username"
	}
	if cfg.EmailClaim == "" {
		cfg.EmailClaim = "email"
	}

	override := keyfunc.Override{}
	if cfg.JWKSRefreshRateLimit > 0 {
		// One refresh per cfg.JWKSRefreshRateLimit, burst 1. Mirrors
		// the shape of keyfunc's own default (rate.Every(5*time.Minute)),
		// which makes it easy to reason about: a single forged-kid
		// burst can fire at most one JWKS refresh per window.
		override.RefreshUnknownKID = rate.NewLimiter(
			rate.Every(cfg.JWKSRefreshRateLimit), 1,
		)
	}
	k, err := keyfunc.NewDefaultOverrideCtx(
		context.Background(),
		[]string{cfg.JWKSURL},
		override,
	)
	if err != nil {
		return nil, fmt.Errorf("auth: failed to initialise JWKS client: %w", err)
	}

	parser := jwt.NewParser(
		jwt.WithIssuer(cfg.Issuer),
		jwt.WithAudience(cfg.Audience),
		jwt.WithExpirationRequired(),
		jwt.WithValidMethods([]string{"RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384", "ES512"}),
		jwt.WithLeeway(30*time.Second),
	)

	return &JWTAuth{
		cfg:       cfg,
		keyfunc:   k.Keyfunc,
		parser:    parser,
		exchanger: exchanger,
	}, nil
}

// Authenticate extracts the bearer token, validates it, and projects the
// resolved claims onto an Identity.
func (j *JWTAuth) Authenticate(r *http.Request) (Identity, error) {
	tokenStr, ok := bearerToken(r)
	if !ok {
		return Identity{}, ErrInvalidToken
	}

	claims := jwt.MapClaims{}
	tok, err := j.parser.ParseWithClaims(tokenStr, claims, j.keyfunc)
	if err != nil {
		// keyfunc returns a wrapped error when the JWKS endpoint is
		// unreachable AND the cache is cold. Surface that distinctly so
		// the middleware can emit 503 instead of 401.
		if isJWKSColdCacheError(err) {
			return Identity{}, ErrJWKSUnavailable
		}
		return Identity{}, fmt.Errorf("%w: %v", ErrInvalidToken, err)
	}
	if !tok.Valid {
		return Identity{}, ErrInvalidToken
	}

	subject := stringClaim(claims, j.cfg.SubjectClaim)
	if subject == "" {
		// A token without a usable subject is unusable downstream.
		return Identity{}, fmt.Errorf("%w: missing %q claim", ErrInvalidToken, j.cfg.SubjectClaim)
	}

	id := Identity{
		Subject: subject,
		User:    stringClaim(claims, j.cfg.UserClaim),
		Email:   stringClaim(claims, j.cfg.EmailClaim),
		Mode:    ModeJWT,
	}

	if j.exchanger != nil {
		swapped, err := j.exchanger.Exchange(r.Context(), tokenStr, r.Header)
		if err != nil {
			// Exchange errors flow through ErrExchangeFailed (NOT
			// ErrInvalidToken). The middleware maps non-ErrInvalidToken
			// errors to 503 — token exchange that does not succeed means
			// the gateway cannot vouch for the downstream call, so we fail
			// closed rather than silently forward an unverifiable identity.
			return Identity{}, err
		}
		id.BearerToken = swapped
	}

	return id, nil
}

// bearerToken extracts the token from an `Authorization: Bearer <token>`
// header. Returns ok=false when the header is missing, malformed, or uses
// a scheme other than Bearer.
func bearerToken(r *http.Request) (string, bool) {
	h := r.Header.Get("Authorization")
	if h == "" {
		return "", false
	}
	const prefix = "Bearer "
	if len(h) <= len(prefix) || !strings.EqualFold(h[:len(prefix)], prefix) {
		return "", false
	}
	tok := strings.TrimSpace(h[len(prefix):])
	if tok == "" {
		return "", false
	}
	return tok, true
}

// stringClaim returns the named claim as a string, or "" if absent or not
// a string.
func stringClaim(claims jwt.MapClaims, name string) string {
	if v, ok := claims[name].(string); ok {
		return v
	}
	return ""
}

// isJWKSColdCacheError returns true when err indicates the JWKS endpoint
// could not be reached AND no key was available in the cache.
//
// keyfunc/v3 returns jwkset.ErrNewClient or wraps a network error from the
// initial fetch when the cache has nothing to fall back on. In that case
// the gateway is degraded — emit 503, not 401, so a client retry behind a
// load balancer has a chance to land on a healthier replica.
func isJWKSColdCacheError(err error) bool {
	// keyfunc surfaces a sentinel ErrKeyfunc on signing-key lookup failure;
	// when the cache is cold the wrapped error is the underlying network
	// error. We can't import private sentinels, so match on the message
	// fragment that keyfunc emits in this case.
	msg := err.Error()
	return strings.Contains(msg, "could not find kid") ||
		strings.Contains(msg, "failed to refresh") ||
		strings.Contains(msg, "no keys in JWK Set")
}

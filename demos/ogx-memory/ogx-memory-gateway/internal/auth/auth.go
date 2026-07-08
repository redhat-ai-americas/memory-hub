// Package auth resolves the identity of inbound requests and projects it
// onto a canonical set of trusted headers that the gateway forwards to the
// backend agent.
//
// Header contract emitted to the backend:
//
//	X-Auth-Subject  — stable identifier (JWT sub, OpenShift uid, or "anonymous")
//	X-Auth-User     — human-readable username, may be empty
//	X-Auth-Email    — email address, may be empty
//	X-Auth-Mode     — "anonymous" | "proxy"
//
// The header names match Kagenti's JWT claim shape so the contract survives
// a future swap to AuthBridge / in-process JWKS without breaking the agent.
package auth

import (
	"errors"
	"fmt"
	"net/http"
)

// Mode names. Keep in sync with config.Config.AuthMode validation.
const (
	ModeAnonymous = "anonymous"
	ModeProxy     = "proxy"
	ModeJWT       = "jwt"
)

// Canonical header names emitted to the backend.
const (
	HeaderSubject = "X-Auth-Subject"
	HeaderUser    = "X-Auth-User"
	HeaderEmail   = "X-Auth-Email"
	HeaderMode    = "X-Auth-Mode"
)

// CanonicalHeaders lists every header the gateway issues. Inbound copies
// of these are stripped before the strategy runs to prevent client spoofing.
var CanonicalHeaders = []string{
	HeaderSubject,
	HeaderUser,
	HeaderEmail,
	HeaderMode,
}

// Identity is the resolved caller identity.
type Identity struct {
	Subject string
	User    string
	Email   string
	Mode    string
	// BearerToken is the value the middleware will project as
	// `Authorization: Bearer <token>` to the backend. Empty means the
	// middleware strips Authorization from the inbound request — the gateway
	// only forwards a bearer token it has cryptographically derived (e.g.
	// via RFC 8693 token exchange in jwt mode).
	BearerToken string
}

// ErrMissingProxyHeaders signals that proxy mode was configured but the
// upstream did not project the expected user header. Surfaced as 503 so a
// misconfigured deployment fails closed instead of silently degrading to
// anonymous.
var ErrMissingProxyHeaders = errors.New("auth: proxy mode but upstream identity headers are missing")

// Authenticator resolves an Identity from an inbound request. Implementations
// must not mutate r.
type Authenticator interface {
	Authenticate(r *http.Request) (Identity, error)
}

// Options bundles every parameter New() may consume. Each field is only
// consulted by the corresponding mode; unused fields are ignored.
type Options struct {
	// ProxyUserHeader / ProxyEmailHeader are consulted only in proxy mode.
	ProxyUserHeader  string
	ProxyEmailHeader string

	// JWT is consulted only in jwt mode.
	JWT JWTConfig
	// JWTExchanger is consulted only in jwt mode. When non-nil the gateway
	// performs an RFC 8693 token exchange after validating the inbound
	// token, projecting the swapped token onto Identity.BearerToken so the
	// middleware can forward a downstream-audienced bearer instead of the
	// raw user JWT. Optional — jwt mode without an exchanger validates and
	// emits canonical X-Auth-* headers but forwards no Authorization
	// downstream.
	JWTExchanger *TokenExchanger
}

// New returns the authenticator for the given mode.
func New(mode string, opts Options) (Authenticator, error) {
	switch mode {
	case ModeAnonymous, "":
		return &AnonymousAuth{}, nil
	case ModeProxy:
		if opts.ProxyUserHeader == "" {
			return nil, fmt.Errorf("auth: proxy mode requires a non-empty user header name")
		}
		return &ProxyAuth{
			UserHeader:  opts.ProxyUserHeader,
			EmailHeader: opts.ProxyEmailHeader,
		}, nil
	case ModeJWT:
		return NewJWTAuth(opts.JWT, opts.JWTExchanger)
	default:
		return nil, fmt.Errorf("auth: unknown mode %q (want %q, %q, or %q)", mode, ModeAnonymous, ModeProxy, ModeJWT)
	}
}

// AnonymousAuth always returns the anonymous identity. Used for local dev,
// the smoke script, and any deployment where identity is not required.
type AnonymousAuth struct{}

// Authenticate returns the canonical anonymous identity.
func (a *AnonymousAuth) Authenticate(r *http.Request) (Identity, error) {
	return Identity{
		Subject: "anonymous",
		User:    "",
		Email:   "",
		Mode:    ModeAnonymous,
	}, nil
}

// ProxyAuth trusts an upstream OAuth proxy (or service-mesh authn filter)
// to project the authenticated user into request headers. The gateway pod
// must be unreachable except via that proxy, otherwise a client can spoof
// the headers.
type ProxyAuth struct {
	// UserHeader is the request header carrying the username, e.g.
	// "X-Forwarded-User" (oauth-proxy default).
	UserHeader string
	// EmailHeader is the request header carrying the email address, e.g.
	// "X-Forwarded-Email". Optional — when empty or unset the resolved
	// identity has no email.
	EmailHeader string
}

// Authenticate reads the configured upstream headers and projects them
// onto the canonical Identity. Returns ErrMissingProxyHeaders when the
// user header is absent so the caller can fail closed.
func (p *ProxyAuth) Authenticate(r *http.Request) (Identity, error) {
	user := r.Header.Get(p.UserHeader)
	if user == "" {
		return Identity{}, ErrMissingProxyHeaders
	}

	email := ""
	if p.EmailHeader != "" {
		email = r.Header.Get(p.EmailHeader)
	}

	return Identity{
		Subject: user,
		User:    user,
		Email:   email,
		Mode:    ModeProxy,
	}, nil
}

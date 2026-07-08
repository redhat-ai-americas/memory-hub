package auth

import (
	"errors"
	"log/slog"
	"net/http"
)

// unauthenticatedPaths are exempt from auth resolution. Kubelet liveness
// and readiness probes hit the gateway directly (not through the upstream
// OAuth proxy) and have no identity, so in proxy mode they would otherwise
// fail closed and crash-loop the pod. The agent card is metadata and is
// safe to expose anonymously.
var unauthenticatedPaths = map[string]struct{}{
	"/healthz":                 {},
	"/readyz":                  {},
	"/.well-known/agent.json":  {},
}

// Middleware returns an HTTP middleware that resolves caller identity using
// the supplied Authenticator and projects it onto canonical X-Auth-*
// headers. Inbound copies of the canonical headers are stripped before the
// strategy runs so clients cannot spoof identity.
//
// On ErrMissingProxyHeaders the middleware returns 503 — fail-closed, since
// a missing upstream identity in proxy mode means the deployment is
// misconfigured.
//
// Probe and discovery paths (see unauthenticatedPaths) bypass the strategy
// entirely. Inbound canonical headers are still stripped on those paths so
// they cannot be used as a spoof channel into downstream handlers — but
// since those handlers don't call any backend, this is defence in depth.
func Middleware(a Authenticator) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			stripCanonicalHeaders(r.Header)

			if _, exempt := unauthenticatedPaths[r.URL.Path]; exempt {
				next.ServeHTTP(w, r)
				return
			}

			id, err := a.Authenticate(r)
			if err != nil {
				// ErrInvalidToken → 401: caller's bearer token is bad.
				// Everything else (ErrMissingProxyHeaders, ErrJWKSUnavailable,
				// arbitrary errors) → 503: deployment is degraded.
				if errors.Is(err, ErrInvalidToken) {
					slog.Info("auth: rejecting invalid bearer token",
						"error", err,
						"path", r.URL.Path,
						"method", r.Method,
					)
					http.Error(w, `{"error":"invalid bearer token"}`, http.StatusUnauthorized)
					return
				}
				slog.Error("auth: identity resolution failed",
					"error", err,
					"path", r.URL.Path,
					"method", r.Method,
				)
				http.Error(w, `{"error":"upstream identity unavailable"}`, http.StatusServiceUnavailable)
				return
			}

			setCanonicalHeaders(r.Header, id)
			projectAuthorization(r.Header, id)
			next.ServeHTTP(w, r)
		})
	}
}

// projectAuthorization replaces the inbound Authorization header with the
// gateway-derived bearer token (e.g. an RFC 8693 swapped token) when the
// strategy populated id.BearerToken. Otherwise it strips Authorization so
// the raw inbound bearer never leaks downstream — the gateway forwards only
// what it can vouch for.
func projectAuthorization(h http.Header, id Identity) {
	if id.BearerToken != "" {
		h.Set("Authorization", "Bearer "+id.BearerToken)
		return
	}
	h.Del("Authorization")
}

// stripCanonicalHeaders removes any inbound copies of the canonical X-Auth-*
// headers so a client cannot pre-populate them.
func stripCanonicalHeaders(h http.Header) {
	for _, name := range CanonicalHeaders {
		h.Del(name)
	}
}

// setCanonicalHeaders writes the canonical headers from id onto h. Empty
// fields are still written (as empty strings) so downstream handlers see a
// uniform contract.
func setCanonicalHeaders(h http.Header, id Identity) {
	h.Set(HeaderSubject, id.Subject)
	h.Set(HeaderUser, id.User)
	h.Set(HeaderEmail, id.Email)
	h.Set(HeaderMode, id.Mode)
}

package handler

import (
	"log/slog"
	"net/http"
	"net/http/httputil"
	"net/url"
	"strings"
)

// ForwardingHandler is a thin reverse-proxy handler that forwards every
// inbound request under a path prefix to a target base URL verbatim. It
// preserves the request method, body, query string, and headers (subject
// to standard hop-by-hop stripping that net/http/httputil.ReverseProxy
// performs automatically).
//
// Used to proxy /v1/feedback*, /v1/sessions/*, and /v1/traces/* to a
// deployed fipsagents-platform service when the gateway is configured
// with a non-empty PLATFORM_URL. The auth middleware runs before the
// proxy fires, so the Authorization, X-Auth-*, and X-Tenant headers it
// projects are forwarded to the platform unchanged. The W3C Trace
// Context traceparent header is also end-to-end and forwarded as-is.
//
// The handler does not interpret request bodies — every prefix is
// proxied as opaque bytes, matching the issue's "no payload
// interpretation" contract.
type ForwardingHandler struct {
	// TargetURL is the base URL that requests are forwarded to (eg
	// "http://fipsagents-platform.svc:8080"). Trailing slashes are
	// trimmed by the config layer. The inbound request path is
	// appended as-is.
	TargetURL string

	// Logger receives forwarding events. When nil, slog.Default() is
	// used.
	Logger *slog.Logger

	proxy *httputil.ReverseProxy
}

// New returns a ForwardingHandler whose underlying ReverseProxy is wired
// up against TargetURL. Returns an error if TargetURL is empty or not a
// parseable URL.
func NewForwardingHandler(targetURL string) (*ForwardingHandler, error) {
	target, err := url.Parse(strings.TrimRight(targetURL, "/"))
	if err != nil {
		return nil, err
	}
	h := &ForwardingHandler{TargetURL: target.String()}
	h.proxy = &httputil.ReverseProxy{
		Rewrite: func(pr *httputil.ProxyRequest) {
			// Preserve the inbound path + query verbatim; only the
			// scheme + host change.
			pr.Out.URL.Scheme = target.Scheme
			pr.Out.URL.Host = target.Host
			// Some platform deployments live under a path prefix
			// (eg /platform). Honor TargetURL.Path as a base.
			pr.Out.URL.Path = singleJoiningSlash(target.Path, pr.In.URL.Path)
			pr.Out.URL.RawPath = ""
			pr.Out.Host = target.Host
			// Preserve client headers (Authorization, X-Auth-*,
			// X-Tenant, traceparent). httputil strips hop-by-hop
			// automatically.
			pr.Out.Header = pr.In.Header.Clone()
			// Drop any inbound Host header echo so the upstream
			// sees the platform host.
			pr.Out.Header.Del("Host")
		},
		ErrorHandler: func(w http.ResponseWriter, r *http.Request, err error) {
			logger := h.Logger
			if logger == nil {
				logger = slog.Default()
			}
			logger.Error("platform proxy failed",
				"error", err,
				"target", target.String(),
				"path", r.URL.Path,
				"method", r.Method,
			)
			http.Error(w, `{"error":"platform unreachable"}`, http.StatusBadGateway)
		},
	}
	return h, nil
}

func (h *ForwardingHandler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	h.proxy.ServeHTTP(w, r)
}

// singleJoiningSlash concatenates two URL path components ensuring
// exactly one slash between them. Mirrors the helper in stdlib's
// httputil but is unexported there. Empty target prefix is the common
// case (TargetURL has no path); this still works.
func singleJoiningSlash(a, b string) string {
	aslash := strings.HasSuffix(a, "/")
	bslash := strings.HasPrefix(b, "/")
	switch {
	case aslash && bslash:
		return a + b[1:]
	case !aslash && !bslash && a != "" && b != "":
		return a + "/" + b
	}
	return a + b
}

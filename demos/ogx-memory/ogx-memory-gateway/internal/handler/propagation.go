package handler

import "net/http"

// propagationHeaders are W3C Trace Context headers forwarded end-to-end so
// the gateway becomes a transparent hop in distributed traces. The agent
// layer's `fipsagents.server.propagation` extracts traceparent on inbound
// and joins the trace; without forwarding here, the chain breaks at the
// gateway and any OTEL backend shows two disconnected traces per request.
//
// Kept separate from forwardedAuthHeaders / authHeaders so the auth and
// observability concerns stay independently auditable.
var propagationHeaders = []string{
	"Traceparent",
	"Tracestate",
}

// copyPropagationHeaders copies the W3C Trace Context headers from src to
// dst. Header lookups are case-insensitive (http.Header.Get canonicalizes),
// so this works regardless of how the inbound client cased them.
func copyPropagationHeaders(dst http.Header, src http.Header) {
	for _, name := range propagationHeaders {
		if v := src.Get(name); v != "" {
			dst.Set(name, v)
		}
	}
}

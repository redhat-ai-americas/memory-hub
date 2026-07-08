package proxy_test

import (
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/fips-agents/gateway-template/internal/proxy"
)

// fakeResponse builds an *http.Response whose Body reads from the given string.
func fakeResponse(body string) *http.Response {
	return &http.Response{
		StatusCode: http.StatusOK,
		Body:       io.NopCloser(strings.NewReader(body)),
		Header:     http.Header{"Content-Type": []string{"text/event-stream"}},
	}
}

func TestRelaySSE_ForwardsChunks(t *testing.T) {
	ssePayload := strings.Join([]string{
		`data: {"choices":[{"delta":{"content":"Hel"}}]}`,
		"",
		`data: {"choices":[{"delta":{"content":"lo"}}]}`,
		"",
		"data: [DONE]",
		"",
	}, "\n")

	resp := fakeResponse(ssePayload)
	rec := httptest.NewRecorder()

	proxy.RelaySSE(resp, rec)

	body := rec.Body.String()

	// Both data lines should appear in the output.
	if !strings.Contains(body, `"content":"Hel"`) {
		t.Errorf("RelaySSE: missing first chunk in output:\n%s", body)
	}
	if !strings.Contains(body, `"content":"lo"`) {
		t.Errorf("RelaySSE: missing second chunk in output:\n%s", body)
	}
	if !strings.Contains(body, "data: [DONE]") {
		t.Errorf("RelaySSE: missing DONE terminator in output:\n%s", body)
	}
}

func TestRelaySSE_StopsOnDone(t *testing.T) {
	// Put extra data after [DONE] -- it should not appear in output.
	ssePayload := strings.Join([]string{
		`data: {"choices":[{"delta":{"content":"A"}}]}`,
		"",
		"data: [DONE]",
		"",
		`data: {"choices":[{"delta":{"content":"SHOULD NOT APPEAR"}}]}`,
		"",
	}, "\n")

	resp := fakeResponse(ssePayload)
	rec := httptest.NewRecorder()

	proxy.RelaySSE(resp, rec)

	body := rec.Body.String()
	if strings.Contains(body, "SHOULD NOT APPEAR") {
		t.Errorf("RelaySSE: data after [DONE] was relayed:\n%s", body)
	}
}

func TestRelaySSE_HandlesEmptyLines(t *testing.T) {
	// SSE spec uses blank lines as event separators; they should pass through
	// without causing errors.
	ssePayload := strings.Join([]string{
		"",
		"",
		`data: {"choices":[{"delta":{"content":"ok"}}]}`,
		"",
		"data: [DONE]",
		"",
	}, "\n")

	resp := fakeResponse(ssePayload)
	rec := httptest.NewRecorder()

	proxy.RelaySSE(resp, rec)

	body := rec.Body.String()
	if !strings.Contains(body, `"content":"ok"`) {
		t.Errorf("RelaySSE: missing data chunk after empty lines:\n%s", body)
	}
}

func TestRelaySSE_BackendClosesWithoutDone(t *testing.T) {
	// If the backend closes the stream without sending [DONE], RelaySSE
	// should return gracefully once the reader hits EOF.
	ssePayload := strings.Join([]string{
		`data: {"choices":[{"delta":{"content":"partial"}}]}`,
		"",
	}, "\n")

	resp := fakeResponse(ssePayload)
	rec := httptest.NewRecorder()

	proxy.RelaySSE(resp, rec)

	body := rec.Body.String()
	if !strings.Contains(body, "partial") {
		t.Errorf("RelaySSE: missing data from truncated stream:\n%s", body)
	}
}

package proxy

import (
	"bufio"
	"log/slog"
	"net/http"
	"strings"
	"time"
)

const heartbeatInterval = 15 * time.Second

// RelaySSE reads an SSE stream from backendResp and writes each event to the
// client. It flushes after every line and sends periodic heartbeat comments
// to keep the connection alive through intermediate proxies.
func RelaySSE(backendResp *http.Response, w http.ResponseWriter) {
	flusher, ok := w.(http.Flusher)
	if !ok {
		slog.Error("response writer does not support flushing")
		http.Error(w, "streaming not supported", http.StatusInternalServerError)
		return
	}

	scanner := bufio.NewScanner(backendResp.Body)
	heartbeat := time.NewTicker(heartbeatInterval)
	defer heartbeat.Stop()

	lines := make(chan string)
	done := make(chan struct{})
	defer close(done)

	// Read lines from the backend in a goroutine so we can interleave heartbeats.
	go func() {
		defer close(lines)
		for scanner.Scan() {
			select {
			case lines <- scanner.Text():
			case <-done:
				return
			}
		}
		if err := scanner.Err(); err != nil {
			slog.Warn("scanner error reading backend SSE stream", "error", err)
		}
	}()

	for {
		select {
		case line, ok := <-lines:
			if !ok {
				// Backend closed the stream.
				return
			}
			// Write the line as-is (preserves "data: ..." formatting).
			_, _ = w.Write([]byte(line + "\n"))
			flusher.Flush()

			// Detect the OpenAI SSE terminator.
			if strings.TrimSpace(line) == "data: [DONE]" {
				return
			}

		case <-heartbeat.C:
			// SSE comment to keep the connection alive.
			_, _ = w.Write([]byte(": heartbeat\n\n"))
			flusher.Flush()
		}
	}
}

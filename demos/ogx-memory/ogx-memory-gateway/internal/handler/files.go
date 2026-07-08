package handler

import (
	"context"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"mime"
	"mime/multipart"
	"net/http"
	"net/textproto"
	"strings"
	"time"

	"github.com/fips-agents/gateway-template/internal/config"
)

// FilesUploadHandler proxies POST /v1/files multipart uploads to the
// backend agent, enforcing a size cap and a MIME-type allowlist before
// any bytes leave the gateway. The proxy is streaming: the file body
// is piped chunk-by-chunk into a fresh multipart writer wrapping a
// pipe that feeds the upstream request, never buffered whole.
//
// The size cap is enforced two ways: an immediate 413 when the inbound
// Content-Length exceeds MaxBytes, and a wrapping http.MaxBytesReader
// that interrupts mid-stream uploads (chunked transfers, missing
// Content-Length) once the limit is reached.
//
// MIME validation runs on each "file" part's declared Content-Type.
// The first file part is validated synchronously — failing fast with
// 415 before any upstream request fires. Subsequent file parts (rare
// in practice; the agent contract is single-file-per-request) are
// validated as they're encountered. The agent does its own libmagic
// content sniffing — gateway validation is defense in depth against
// obviously-misclassified uploads.
type FilesUploadHandler struct {
	BackendURL string
	MaxBytes   int64
	Cfg        *config.Config
	Timeout    time.Duration
	// Client is the HTTP client used for the upstream request. The
	// caller owns the timeout via Timeout — Client.Timeout is ignored
	// so it can be shared with other handlers.
	Client *http.Client
}

// ServeHTTP enforces method, size, and MIME constraints, then streams
// the multipart upload to the backend's /v1/files endpoint with the
// canonical X-Auth-* headers preserved.
func (h *FilesUploadHandler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, `{"error":"method not allowed"}`, http.StatusMethodNotAllowed)
		return
	}

	mediaType, params, err := mime.ParseMediaType(r.Header.Get("Content-Type"))
	if err != nil || !strings.EqualFold(mediaType, "multipart/form-data") {
		http.Error(w, `{"error":"Content-Type must be multipart/form-data"}`, http.StatusUnsupportedMediaType)
		return
	}
	if params["boundary"] == "" {
		http.Error(w, `{"error":"multipart boundary missing"}`, http.StatusBadRequest)
		return
	}

	if r.ContentLength > 0 && h.MaxBytes > 0 && r.ContentLength > h.MaxBytes {
		http.Error(w, fmt.Sprintf(
			`{"error":"upload exceeds max size","max_bytes":%d}`, h.MaxBytes,
		), http.StatusRequestEntityTooLarge)
		return
	}

	body := r.Body
	if h.MaxBytes > 0 {
		body = http.MaxBytesReader(w, body, h.MaxBytes)
	}
	defer body.Close()

	mr := multipart.NewReader(body, params["boundary"])

	// Walk parts synchronously up to and including the first file
	// part. Form fields encountered along the way are buffered (they
	// are small by spec — session_id, etc.). The first file part's
	// header is validated before we commit to any upstream request.
	prefix, firstFile, err := h.collectPrefix(mr)
	if err != nil {
		var ve *validationError
		if errors.As(err, &ve) {
			http.Error(w, ve.body, ve.status)
			return
		}
		var mbe *http.MaxBytesError
		if errors.As(err, &mbe) {
			http.Error(w, fmt.Sprintf(
				`{"error":"upload exceeds max size","max_bytes":%d}`, h.MaxBytes,
			), http.StatusRequestEntityTooLarge)
			return
		}
		slog.Warn("multipart prefix parse failed", "error", err)
		http.Error(w, `{"error":"invalid multipart body"}`, http.StatusBadRequest)
		return
	}

	// Pipe the re-encoded multipart body to the backend. The pipe
	// lets us start the upstream request as soon as the first byte
	// is ready and surfaces any read error from the inbound side as
	// a write error on the upstream side.
	pr, pw := io.Pipe()
	mw := multipart.NewWriter(pw)

	go func() {
		defer pw.Close()
		err := h.streamRest(mr, mw, prefix, firstFile)
		if err != nil {
			_ = mw.Close()
			pw.CloseWithError(err)
			return
		}
		if err := mw.Close(); err != nil {
			pw.CloseWithError(err)
		}
	}()

	ctx := r.Context()
	if h.Timeout > 0 {
		var cancel context.CancelFunc
		ctx, cancel = context.WithTimeout(ctx, h.Timeout)
		defer cancel()
	}

	upstream, err := http.NewRequestWithContext(ctx, http.MethodPost, h.BackendURL+"/v1/files", pr)
	if err != nil {
		slog.Error("failed to build upstream request", "error", err)
		http.Error(w, `{"error":"failed to build backend request"}`, http.StatusInternalServerError)
		return
	}
	upstream.Header.Set("Content-Type", mw.FormDataContentType())
	for _, name := range forwardedAuthHeaders {
		if v := r.Header.Get(name); v != "" {
			upstream.Header.Set(name, v)
		}
	}
	copyPropagationHeaders(upstream.Header, r.Header)

	resp, err := h.Client.Do(upstream)
	if err != nil {
		var mbe *http.MaxBytesError
		if errors.As(err, &mbe) {
			http.Error(w, fmt.Sprintf(
				`{"error":"upload exceeds max size","max_bytes":%d}`, h.MaxBytes,
			), http.StatusRequestEntityTooLarge)
			return
		}
		var ve *validationError
		if errors.As(err, &ve) {
			http.Error(w, ve.body, ve.status)
			return
		}
		if errors.Is(err, context.DeadlineExceeded) {
			http.Error(w, `{"error":"upload timed out"}`, http.StatusGatewayTimeout)
			return
		}
		slog.Error("backend upload failed", "error", err)
		http.Error(w, `{"error":"backend request failed"}`, http.StatusBadGateway)
		return
	}
	defer resp.Body.Close()

	if ct := resp.Header.Get("Content-Type"); ct != "" {
		w.Header().Set("Content-Type", ct)
	} else {
		w.Header().Set("Content-Type", "application/json")
	}
	copyPassThroughHeaders(w.Header(), resp.Header)
	w.WriteHeader(resp.StatusCode)
	if _, err := io.Copy(w, resp.Body); err != nil {
		slog.Warn("error copying backend response", "error", err)
	}
}

// bufferedField is a non-file multipart part read into memory so it can
// be replayed to the upstream writer after the file part's MIME has
// been validated. Form fields in the agent contract are small
// (session_id is at most 128 chars), so memory is bounded.
type bufferedField struct {
	header textproto.MIMEHeader
	body   []byte
}

// collectPrefix walks mr until it has either encountered the first
// file part (whose header passes MIME validation) or exhausted the
// multipart body. Non-file form fields encountered along the way are
// fully read into memory and returned as the prefix to be replayed by
// the streaming goroutine. Returns the open file part for streaming;
// firstFile may be nil if the upload contained no file parts (rare —
// surfaced as a 400 by the caller).
func (h *FilesUploadHandler) collectPrefix(mr *multipart.Reader) ([]bufferedField, *multipart.Part, error) {
	var prefix []bufferedField
	for {
		part, err := mr.NextPart()
		if err == io.EOF {
			return prefix, nil, &validationError{
				status: http.StatusBadRequest,
				body:   `{"error":"multipart body has no file part"}`,
			}
		}
		if err != nil {
			return nil, nil, err
		}
		if part.FileName() == "" {
			data, err := io.ReadAll(part)
			_ = part.Close()
			if err != nil {
				return nil, nil, err
			}
			prefix = append(prefix, bufferedField{
				header: cloneHeader(part.Header),
				body:   data,
			})
			continue
		}
		ct := part.Header.Get("Content-Type")
		if ct == "" {
			ct = "application/octet-stream"
		}
		if !h.Cfg.MIMEAllowed(ct) {
			_ = part.Close()
			return nil, nil, &validationError{
				status: http.StatusUnsupportedMediaType,
				body: fmt.Sprintf(
					`{"error":"MIME type not allowed","content_type":%q}`, ct,
				),
			}
		}
		return prefix, part, nil
	}
}

// streamRest writes the buffered form fields, then the file part body
// (streamed via io.Copy), then walks any remaining parts and forwards
// them. Any subsequent file part with a disallowed MIME closes the
// pipe with a validationError so the upstream HTTP client returns it
// to the main handler.
func (h *FilesUploadHandler) streamRest(
	mr *multipart.Reader,
	mw *multipart.Writer,
	prefix []bufferedField,
	firstFile *multipart.Part,
) error {
	for _, f := range prefix {
		out, err := mw.CreatePart(f.header)
		if err != nil {
			return err
		}
		if _, err := out.Write(f.body); err != nil {
			return err
		}
	}
	if firstFile != nil {
		if err := copyPart(mw, firstFile); err != nil {
			return err
		}
	}
	for {
		part, err := mr.NextPart()
		if err == io.EOF {
			return nil
		}
		if err != nil {
			return err
		}
		if part.FileName() != "" {
			ct := part.Header.Get("Content-Type")
			if ct == "" {
				ct = "application/octet-stream"
			}
			if !h.Cfg.MIMEAllowed(ct) {
				_ = part.Close()
				return &validationError{
					status: http.StatusUnsupportedMediaType,
					body: fmt.Sprintf(
						`{"error":"MIME type not allowed","content_type":%q}`, ct,
					),
				}
			}
		}
		if err := copyPart(mw, part); err != nil {
			return err
		}
	}
}

func copyPart(mw *multipart.Writer, part *multipart.Part) error {
	out, err := mw.CreatePart(part.Header)
	if err != nil {
		_ = part.Close()
		return err
	}
	if _, err := io.Copy(out, part); err != nil {
		_ = part.Close()
		return err
	}
	return part.Close()
}

func cloneHeader(h textproto.MIMEHeader) textproto.MIMEHeader {
	out := make(textproto.MIMEHeader, len(h))
	for k, v := range h {
		out[k] = append([]string(nil), v...)
	}
	return out
}

// validationError carries an HTTP status and a JSON body string so a
// failure inside the streaming goroutine can be mapped back to a
// precise client response from ServeHTTP.
type validationError struct {
	status int
	body   string
}

func (e *validationError) Error() string {
	return fmt.Sprintf("validation: status=%d body=%s", e.status, e.body)
}

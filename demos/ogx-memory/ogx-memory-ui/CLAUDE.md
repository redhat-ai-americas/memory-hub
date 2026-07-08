# CLAUDE.md

## Project Overview

A minimal, self-contained chat UI that connects to any OpenAI-compatible API endpoint. The Go server embeds static files into a single binary and serves them alongside a config endpoint that tells the frontend where the API lives.

## Build and Run

```bash
# Build binary
make build

# Run locally (connects to localhost:8080 by default)
make run

# Run with custom API endpoint
API_URL=https://my-agent.apps.cluster.example.com make run
```

## Architecture

The project has two layers:

**Go server** (`cmd/server/main.go`) -- a ~90-line HTTP server that:
- Embeds static files via Go's `embed` package (through `static/embed.go`)
- Reverse-proxies `/v1/*` requests to the backend, eliminating CORS issues
- Serves `GET /api/config` returning the API_URL as JSON
- Serves `GET /healthz` for container probes
- Handles graceful shutdown on SIGTERM

**Static frontend** (`static/`) -- vanilla HTML/CSS/JS, no build step:
- Fetches `/api/config` on load; fetches `/v1/agent-info` to populate a settings panel with model info, parameters, tools, and system prompt
- Posts to the local `/v1/chat/completions` proxy with `stream: true`
- Parses SSE responses with streaming display, reasoning/thinking content panel, tool call visualization, and stream metrics (tokens/s, inter-token latency)
- **Subagent delegation rendering** — handles `delta.subagent` events emitted by fipsagents 0.22.0+ agents that use the subagent-as-tool feature. Renders a delegation card per `span_id` that transitions through `invoked` → `completed` / `failed` states. The subagent's content is folded into the parent assistant message via the parent's normal `content` deltas; the card surfaces only the delegation framing (target agent, task, status, token totals on completion). Style mirrors the existing tool-call pill (`.tool-call` ↔ `.subagent-delegation`).
- **ask_user question rendering** — when the `ask_user` tool completes, `completeToolCall` parses the result JSON, extracts the `prompt` and `options`, and calls `renderQuestion()` to surface the question as visible chat content with clickable pill-shaped option buttons. Clicking a button sends the selected value as the next user message. Also handles `delta.question` events as a forward-compat path if the framework emits them directly.
- **Markdown table rendering** — `renderTable()` detects pipe-delimited table rows in the line-by-line markdown loop, parses header/separator/body rows into `<table>` HTML with `<thead>`/`<tbody>`, styled with borders, header shading, and zebra striping.
- Maintains conversation history in memory

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `API_URL` | `http://localhost:8080` | OpenAI-compatible API endpoint |
| `PORT` | `3000` | Server listen port |
| `UI_MAX_FILE_BYTES` | `26214400` (25 MiB) | Pre-flight client-side size cap surfaced via `/api/config`. Plain bytes or `k`/`m`/`g` (binary) suffix. The gateway is the authoritative cap; this is only used to fail fast in the browser. |
| `UI_ALLOWED_MIME` | -- | Optional comma-separated client-side MIME allowlist surfaced via `/api/config`. Empty defers entirely to the gateway. |

## File uploads

The chat input supports drag-and-drop, paste, and a file-picker button. Each attached file is `POST`'d to `/v1/files` (proxied through the UI server to the gateway, which streams it to the agent), and the resulting `file_id` is included in the `file_ids` array on the next `POST /v1/chat/completions`. Uploads use `XMLHttpRequest` so the chip shows real upload progress.

Pre-flight client-side validation against `UI_MAX_FILE_BYTES` and `UI_ALLOWED_MIME` is best-effort — the gateway re-validates and returns 413 / 415 / 422 (virus scan) on its own, and those errors surface on the chip too. The send button is disabled while any chip is still uploading; failed chips don't block sending (they're effectively no-ops since they have no `file_id`).

## Deployment to OpenShift

```bash
# Build on the cluster via BuildConfig + ImageStream
make build-openshift PROJECT=my-project

# Deploy via Helm
make deploy PROJECT=my-project
```

`PROJECT` is the target namespace only. `RELEASE_NAME` (Helm release name) and `IMAGE_NAME` (ImageStream / BuildConfig / image name) default to the chart name (`ui-template`) and can be overridden independently — important when the UI shares a namespace with another release that already uses those identifiers, e.g. an agent in `calculus-agent`:

```bash
make build-openshift PROJECT=calculus-agent IMAGE_NAME=calculus-ui
make deploy PROJECT=calculus-agent RELEASE_NAME=calculus-ui IMAGE_NAME=calculus-ui
```

For local builds (e.g. for testing), `make image-build` produces a podman image that you'd push to a registry the cluster can pull from; override `image.repository`/`image.tag` on `helm upgrade` accordingly.

## How the UI Discovers the API

The frontend never hardcodes an API URL. On page load, `app.js` calls `GET /api/config`, which returns `{"apiUrl": "..."}` sourced from the `API_URL` environment variable. However, all actual API traffic flows through the server's `/v1/` reverse proxy -- the browser posts to `/v1/chat/completions` on its own origin, and the server forwards the request to the configured backend. This eliminates CORS issues and keeps the static files truly static. The API URL is configured at deploy time via the ConfigMap.

## Sentinel Strings

This is a template repository. During scaffolding, `"ui-template"` is replaced with the actual project name. Sentinel occurrences:
- `index.html` title and header
- `go.mod` module path
- `Chart.yaml` name
- `Containerfile` label
- `Makefile` PROJECT/RELEASE_NAME/IMAGE_NAME defaults
- `chart/values.yaml` image repository
- `chart/templates/_helpers.tpl` template names
- `llms.txt` H1 title and GitHub URLs

## Testing

```bash
make lint    # go vet
make test    # go test (currently no test files)
```

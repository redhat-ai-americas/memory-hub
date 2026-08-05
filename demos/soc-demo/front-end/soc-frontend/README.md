# MemoryHub SOC Demo — Frontend

Operational-awareness display for the four-agent incident-response demo.
Static SPA (no build step) + a ~50-line Python relay server. The frontend
is purely a renderer: all scenario logic stays in the harness, which
pushes structured JSON events over WebSocket.

## Why this stack

- **Frontend: vanilla HTML/CSS/JS** — matches the brief's "static SPA, no
  build step". No Node, no Next, no bundler. One file: `static/index.html`.
- **Server: Python + FastAPI** — the harness is already Python, so the
  relay lives in the same runtime. FastAPI gives WebSocket + static file
  serving in one file. Django/Node would add scaffolding for zero benefit.

## Deploy to OpenShift

```bash
make deploy        # project soc-demo + manifests + in-cluster build + rollout
make replay        # feed the scripted scenario to the deployed display (4 s pace)
make replay PACE=0 # burst: presenter clicks through with SPACE
make url           # print the route URL
```

`make deploy` uses an in-cluster binary build (BuildConfig + ImageStream,
Docker strategy on the `Containerfile`) — no external registry, and the
Deployment's image-change trigger rolls out each new build. The Route is
edge-TLS with an 8 h HAProxy timeout so viewer WebSockets survive a full
demo. Namespace is `soc-demo`; to change it, update `Makefile`,
`manifests/kustomization.yaml`, and the image path in
`manifests/deployment.yaml`.

The `/emit` endpoint is open by default. On a shared cluster, set
`EMIT_TOKEN` on the Deployment (commented stub in `deployment.yaml`) and
pass `--token` to `replay.py` / send `X-Emit-Token` from the harness.

## Run it locally

```bash
pip install fastapi uvicorn
uvicorn server:app --port 8000
```

Open http://localhost:8000 — the display sits on the standby screen.

Then feed it events. Two modes:

```bash
# Auto-play (recording mode): one event every 4 s
python replay.py --pace 4

# Click-through (live presentation): burst all events, presenter steps
# through with SPACE / arrow keys (display drops to STEP mode on first ←/SPACE)
python replay.py --pace 0
```

## Wiring the real harness

Replace `replay.py`: have `harness.py` POST each event to
`http://localhost:8000/emit` (or keep replay.py and just regenerate
`scenario.json`). The server rebroadcasts verbatim to all connected
viewers and replays history to late joiners. `POST /reset` clears history
between runs.

## Event schema

One JSON object per event. `type` is required; unknown types are ignored
by the renderer (safe to extend).

| type | key fields |
|---|---|
| `phase_start` | `phase` (1–7), `label`, `description`, `timestamp` |
| `agent_register` | `agent`, `framework`, `actor_id`, `driver_id`, `model` |
| `alert` / `decision` | `agent`, `content` |
| `memory_search` | `agent`, `query` |
| `memory_hit` | `agent`, `memory_id`, `content`, `metadata{incident_id, age, author_agent, author_driver, self_authored, weight}` |
| `memory_write` | `agent`, `memory_id`, `content`, `metadata{incident_id, weight, references[]}` |
| `memory_read` | `agent`, `memory_ids[]`, `content` |
| `contradiction` | `memory_id`, `contradicts` |
| `quarantine` | `agent`, `content` |
| `shift_change` | `changes{agent: new_driver_id}` |
| `audit_query` | `rows[{ts, actor, driver, op, mem}]` |
| `session_end` | `banner` |

Presentation cues (optional on any event): `banner` (text ribbon),
`bcolor` (ribbon accent), `detail: true` (auto-open the side panel),
`moment` (1–5, for the five landing points).

Agent keys are fixed: `tier1`, `forensics`, `intel`, `ic` (colors and
constellation positions live in `AGENTS` at the top of `index.html`).

## Presenter controls

SPACE / → advance · ← back · ESC dismiss panel · L toggle LIVE/STEP ·
click a timeline chip for its memory detail · RESET rewinds the cursor
(events stay buffered).

## Files

- `server.py` — FastAPI relay: `/ws` (viewers), `POST /emit` (producer), `POST /reset`, `/healthz`, serves `static/`
- `static/index.html` — the entire display
- `replay.py` — stand-in harness, stdlib only
- `scenario.json` — the scripted IR-2024-184 scenario (37 events, 7 phases)
- `Containerfile` — UBI9 python-311 image
- `Makefile` — `deploy` / `build` / `replay` / `url` / `logs` / `clean`
- `manifests/` — kustomize: ImageStream, BuildConfig (binary), Deployment, Service, Route

# SOC Demo: Cross-Framework Incident Response with Shared Memory

Four AI agents built on different frameworks investigate a cybersecurity
incident together, sharing context through MemoryHub. Each agent makes
real LLM calls and real MemoryHub MCP tool operations (search, write,
report contradiction). Nothing is scripted; the agents reason over the
scenario and their shared memory in real time.

| Agent | Framework | Model | Role |
|-------|-----------|-------|------|
| Tier 1 SOC Analyst | Claude Code | GPT-OSS 20B (on-cluster) | Alert triage, escalation |
| Forensics Specialist | FIPS-Agent | GPT-OSS 20B (on-cluster) | Timeline reconstruction |
| Threat Intel Analyst | Hermes | GPT-OSS 20B (on-cluster) | Attribution, TTP correlation |
| Incident Commander | OpenClaw | GPT-OSS 20B (on-cluster) | Synthesis, containment |

## Scenario phases

The harness drives the agents through a 7-phase incident response for
IR-2024-184 (credential compromise via phishing, data staging on file
servers):

1. **Detection** (02:14 AM) -- CrowdStrike SIEM alert on unusual service account logon
2. **Triage & Escalation** (02:14--02:55) -- Tier 1 searches shared memory, matches a prior incident pattern, escalates
3. **Investigation** (02:55--06:00) -- Forensics builds a timeline; Threat Intel assesses attribution
4. **Scoping** (04:00--06:30) -- Shift change, attribution contradiction, PII quarantine demo
5. **Containment** (06:00--08:00) -- IC synthesizes findings, coordinates credential rotation
6. **Audit Trail** (post-containment) -- Chain-of-evidence queries across roles and drivers
7. **Post-Incident Learning** (24--72 hours later) -- Lessons captured into shared memory

## What's implemented

- **Orchestration harness** (`harness.py`) -- drives all 7 phases with live LLM inference and real MemoryHub operations
- **Seed memories** (`seed-memories.py`) -- pre-populates the project with 6 cross-incident memories the agents discover during the scenario
- **Smoke test** (`smoke-test.py`) -- validates cross-framework memory sharing without LLM calls
- **Recording pipeline** (`record.sh`) -- captures terminal output via asciinema
- **Web frontend** (`front-end/soc-frontend/`) -- operational-awareness display with WebSocket event streaming, deployable to OpenShift
- **Push bridge** (`push-bridge.py`) -- forwards MemoryHub push notifications to the frontend
- **FIPS-Agent forensics agent** (`agents/soc-forensics/`) -- full fips-agents scaffold with Helm chart, evals, and OpenShift deployment
- **Agent configs** (`agents/soc-*-config/`) -- persona and system prompt configs for the other three agents

## Prerequisites

**Cluster services:**

- MemoryHub MCP server deployed and accessible (the harness calls it for search/write/contradiction)
- A FIPS-Agent instance deployed on OpenShift with access to an LLM endpoint (GPT-OSS 20B or equivalent via vLLM)

**Local environment:**

- Python 3.11+
- MemoryHub Python SDK (from `sdk/` in this repo)
- `rich` and `httpx` packages (`pip install rich httpx`)
- MemoryHub credentials configured in `~/.config/memoryhub/credentials` (INI format, `[mcp-rhoai]` section with `url` and `api_key`)

**For recording:**

- `asciinema` (terminal recording)
- Optionally `agg` (GIF export) or `svg-term-cli` (SVG export)

**For the web frontend:**

- `fastapi` and `uvicorn` (`pip install fastapi uvicorn`)
- Or deploy to OpenShift with `cd front-end/soc-frontend && make deploy`

## How to run

### 1. Seed the shared memory

```bash
python demos/soc-demo/seed-memories.py
```

This creates the `midwest-financial-soc` project in MemoryHub and writes
6 pre-incident memories (prior incident patterns, team heuristics,
operational lessons).

### 2. Run the smoke test (no LLM needed)

```bash
python demos/soc-demo/smoke-test.py
```

Validates that memories written by one agent are readable by any other
agent in the same project. Does not require an LLM endpoint.

### 3. Run the full demo (requires LLM endpoint)

```bash
SOC_FORENSICS_URL=https://<fips-agent-route> python demos/soc-demo/harness.py
```

**Environment variables:**

| Variable | Required | Description |
|----------|----------|-------------|
| `SOC_FORENSICS_URL` | Yes | FIPS-Agent route URL (the shared LLM + MCP gateway) |
| `FRONTEND_URL` | No | Frontend relay URL for live visualization |
| `FRONTEND_TOKEN` | No | `X-Emit-Token` for frontend auth |
| `HARNESS_PHASE_PAUSE` | No | Seconds between phases (default: 2.0) |
| `HARNESS_ACTION_PAUSE` | No | Seconds between actions (default: 1.0) |

### 4. Record a terminal session

```bash
bash demos/soc-demo/record.sh
```

Produces an asciinema `.cast` file in `recordings/`.

### 5. Run the web frontend

```bash
cd demos/soc-demo/front-end/soc-frontend
pip install fastapi uvicorn
uvicorn server:app --port 8000
```

Then either connect the harness (`FRONTEND_URL=http://localhost:8000`) or
replay the scripted scenario:

```bash
python replay.py --pace 4    # auto-play at 4s intervals
python replay.py --pace 0    # click-through mode (SPACE to advance)
```

## Key files

| File | Purpose |
|------|---------|
| `harness.py` | Main orchestration: 7 phases, 6 LLM calls, real MemoryHub ops |
| `seed-memories.py` | Populate MemoryHub with pre-incident context |
| `smoke-test.py` | Cross-framework memory sharing validation |
| `push-bridge.py` | MemoryHub push notifications to frontend bridge |
| `record.sh` | asciinema recording wrapper |
| `FRONTEND_DESIGN.md` | Design brief for the web visualization |
| `front-end/soc-frontend/` | FastAPI + vanilla JS operational display |
| `agents/soc-forensics/` | Full FIPS-Agent scaffold (Helm, evals, deploy) |
| `agents/soc-*-config/` | Persona configs for Tier 1, Threat Intel, IC |
| `openshift/` | Cluster policies and Helm values |

# Agent Name

> A brief description of what this agent does.

<!-- Populated by /create-agent from AGENT_PLAN.md. -->

## Quickstart

```sh
make install       # Create .venv, install dependencies
make run-local     # Start HTTP server on port 8080
```

Test it:

```sh
curl -s http://localhost:8080/healthz
curl -s http://localhost:8080/v1/agent-info | python -m json.tool
curl -s http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "Hello"}]}'
```

## Project Structure

| Path | Purpose |
|------|---------|
| `src/agent.py` | Agent subclass — your main logic |
| `tools/` | One `@tool`-decorated file per tool |
| `prompts/` | Markdown + YAML frontmatter, one per prompt |
| `skills/` | agentskills.io directories (lazy-loaded) |
| `rules/` | Plain Markdown constraints (loaded at startup) |
| `agent.yaml` | Configuration with `${VAR:-default}` substitution |
| `chart/` | Helm chart for OpenShift deployment |
| `evals/` | Eval cases (`make eval`) |

## Configuration

All configuration lives in `agent.yaml`. Every value supports `${VAR:-default}`
environment variable substitution — same file works for local dev and production.

| Section | Key env vars | Purpose |
|---------|-------------|---------|
| `agent` | `AGENT_NAME` | Name, description, version |
| `model` | `MODEL_ENDPOINT`, `MODEL_NAME` | LLM endpoint (OpenAI-compatible) |
| `mcp_servers` | `MCP_*_URL` | Remote MCP server connections |
| `prompts` | — | Prompt directory and system prompt designation |
| `server` | `HOST`, `PORT` | HTTP server binding |
| `loop` | `MAX_ITERATIONS` | Agent loop cap + backoff |
| `memory` | `MEMORY_BACKEND` | Optional: memoryhub, sqlite, pgvector, null |
| `security` | `SECURITY_MODE` | Tool inspection and guardrails |

In production, override values via ConfigMap env vars — the image is immutable.

## Adding Tools

Create a file in `tools/` with the `@tool` decorator:

```python
from fipsagents.baseagent import tool

@tool(description="Search the web", visibility="llm_only")
async def web_search(query: str, max_results: int = 5) -> str:
    ...
```

Visibility controls who can call the tool:

| Visibility | Caller | Use for |
|-----------|--------|---------|
| `llm_only` | LLM via tool calling | Search, retrieval, external APIs |
| `agent_only` | Agent code via `self.use_tool()` | Validation, formatting, internal logic |
| `both` | Either plane | Rare — only when genuinely needed by both |

Tools are auto-discovered at startup. No registration code needed.

## Adding Prompts

Create a Markdown file in `prompts/` with YAML frontmatter:

```markdown
---
name: summarize
description: Summarize a document
variables:
  - name: document
    required: true
  - name: max_length
    default: "500 words"
---

Summarize the following in {max_length} or less:

{document}
```

Load in agent code: `prompt = await self.load_prompt("summarize", document=text)`

The `system` key in `agent.yaml` designates which prompt becomes the system prompt
(default: `system`, i.e. `prompts/system.md`).

## MCP Servers

Add an MCP server in `agent.yaml`:

```yaml
mcp_servers:
  - url: ${MCP_SEARCH_URL:-http://search-mcp:8080/mcp}
```

BaseAgent auto-discovers three capability types at startup:

| Capability | Access in agent code |
|-----------|---------------------|
| **Tools** | Auto-registered with `llm_only` visibility. The LLM calls them. |
| **Prompts** | `await self.get_mcp_prompt(name, arguments)` |
| **Resources** | `await self.read_resource(uri)` |

Discovery helpers: `self.list_mcp_prompts()`, `self.list_mcp_resources()`,
`self.list_mcp_resource_templates()`.

Both HTTP (`url:`) and stdio (`command:`) transports are supported.

## Framework

This agent is built on **fipsagents** (`BaseAgent`).

- **Monorepo**: `packages/fipsagents/` — the source, tests, and full API reference
- **PyPI**: `pip install fipsagents` (when scaffolded via `fips-agents create`)
- **Vendored**: `fips-agents vendor` or `make vendor` copies the source into `src/fipsagents/` for full control

Key methods on `BaseAgent`:

| Method | Purpose |
|--------|---------|
| `call_model()` | LLM completion with auto-included tool schemas |
| `run_tool_calls(response)` | Execute tool calls, loop until model stops calling tools |
| `call_model_json(schema)` | Structured output with Pydantic validation |
| `call_model_validated(fn)` | Call model, validate, retry with backoff |
| `use_tool(name, **kw)` | Agent-code tool call (plane 1) |
| `get_mcp_prompt(name)` | Render an MCP-provided prompt |
| `read_resource(uri)` | Read an MCP-provided resource |
| `build_system_prompt()` | Assemble system prompt + rules + skills |

## Deployment

```sh
make build                          # Build container (podman, linux/amd64)
podman push $IMAGE quay.io/...      # Push to registry
make deploy PROJECT=my-namespace    # Deploy via Helm
make redeploy PROJECT=my-namespace  # Force-redeploy (fresh image pull)
make clean PROJECT=my-namespace     # Remove from OpenShift
```

`make redeploy` forces OpenShift to pull the latest image and restart pods —
use this when deploying with the same tag (e.g. `:latest`).

### Image size notes

The base image (no extras) lands around ~1 GB. Extras grow it noticeably:

| Extra | Adds | Why |
|---|---|---|
| `[server]` | ~50 MB | FastAPI + uvicorn + aiosqlite |
| `[metrics]` | ~5 MB | `prometheus_client` |
| `[otel]` | ~80 MB | OpenTelemetry SDK + OTLP gRPC exporter |
| **`[files]`** | **~5–6 GB** | **Docling pulls in `torch` + `transformers` for document parsing.** Plain text / Markdown / JSON do not require Docling — leave the extra off if your agent only ingests those formats and rely on the built-in `PlaintextParser`. |
| `[s3]` | ~30 MB | `aioboto3` for S3-compatible bytes storage (per ADR-0001). Required when `files.bytesBackend.type: s3`; safe to skip otherwise. |

A typical `[server, files]` build lands around 6.5–7 GB. Plan PVC and image-pull
budgets accordingly; first-pull on a fresh node takes 60–90 s.

### OpenShift binary BuildConfig

The build context ships a `Containerfile` (Podman convention, identical syntax
to a `Dockerfile`). `oc new-build --binary --strategy=docker` defaults to
expecting a file literally named `Dockerfile`, so set `dockerfilePath` after
creating the BuildConfig:

```sh
oc new-build --binary --strategy=docker --name=$NAME -n $NS
oc patch bc/$NAME -n $NS --type=merge \
  -p '{"spec":{"strategy":{"dockerStrategy":{"dockerfilePath":"Containerfile"}}}}'
oc start-build $NAME -n $NS --from-dir=. --follow
```

`make build` (Podman locally) and the OpenShift `BuildConfig` rendered by
the chart already handle this — the snippet above is for ad-hoc binary
builds (eg cluster smokes).

## Development Commands

```sh
make test          # Run pytest
make test-cov      # Run pytest with coverage
make eval          # Run eval cases (mock LLM)
make lint          # Run ruff linter
make vendor        # Vendor fipsagents source (replaces PyPI dep)
make update-fipsagents # Update vendored source from upstream
make help          # Show all targets
```

## AI-Assisted Development

This project includes Claude Code slash commands in `.claude/commands/`:

```
/plan-agent       Design the agent (produces AGENT_PLAN.md)
/create-agent     Generate code from the plan
/add-tool         Add a new tool
/add-skill        Add a new skill
/add-memory       Wire MemoryHub integration
/exercise-agent   Test agent behavior
/deploy-agent     Build and deploy to OpenShift
```

See `CLAUDE.md` for the full AI-assisted development guide.

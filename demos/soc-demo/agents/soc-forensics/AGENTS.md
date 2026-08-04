# Agent Project

An AI agent built on the fipsagents BaseAgent framework. Runs as an
OpenAI-compatible HTTP server (`/v1/chat/completions`).

## Build and Run

```bash
make install       # Create .venv, install dependencies
make run-local     # Run the agent locally (port 8080)
make test          # Run pytest
make lint          # Lint with ruff
make build         # Build container (podman, linux/amd64)
make deploy PROJECT=<ns>   # Deploy to OpenShift via Helm
```

## Project Structure

```
src/agent.py       # Agent subclass — implements step()
tools/             # One @tool-decorated .py file per tool
prompts/           # Markdown with YAML frontmatter, one per prompt
skills/            # agentskills.io directories with SKILL.md
rules/             # Plain Markdown, one constraint per file
agent.yaml         # Config with ${VAR:-default} env var substitution
chart/             # Helm chart for OpenShift deployment
evals/             # Eval cases
```

## Conventions

- Tools use `@tool(description=..., visibility=...)` — every tool must
  declare its visibility plane (`llm_only`, `agent_only`, or `both`).
- Do not edit `src/fipsagents/baseagent/` — that is the framework.
- Do not import `openai` directly — use BaseAgent's `call_model*` methods.
- Do not hardcode model names or endpoints — use `agent.yaml` with env
  var substitution.
- Run `make test && make lint` before committing.

## Testing

```bash
make test          # Unit tests
make test-cov      # With coverage report
make eval          # Run eval cases from evals/evals.yaml
```

## Configuration

`agent.yaml` controls agent behavior. All values support `${VAR:-default}`
environment variable substitution. Key env vars:

- `MODEL_ENDPOINT` — LLM API endpoint
- `MODEL_NAME` — Model identifier
- `MAX_ITERATIONS` — Agent loop cap
- `LOG_LEVEL` — Python logging level

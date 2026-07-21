# MemoryHub

## Project Overview
MemoryHub is a Kubernetes-native agent memory component for OpenShift AI. See docs/ARCHITECTURE.md for the full architecture and docs/SYSTEMS.md for subsystem inventory.

## Branch Strategy

Main is protected. Never push directly to main.

Most work targets **feature branches**, not main. PRs to main happen only when a feature branch is ready to land as a cohesive unit.

**Branch hierarchy:**
- `feat/<topic>` -- long-lived feature branches forked from main
- `feat/<topic>/<subtask>` -- short-lived branches forked from a feature branch for incremental work
- `fix/<description>` -- bugfix branches (target main or a feature branch, depending on scope)

**Workflow:**
1. Create or check out the feature branch (`git checkout -b feat/topic`)
2. For sub-work, branch off the feature branch (`git checkout -b feat/topic/subtask`)
3. PR sub-branches into the parent feature branch, not main
4. When the feature is complete, PR the feature branch into main

**PR targeting rules:**
- Sub-branches PR into their parent feature branch
- Feature branches PR into main only when the work is ready to ship
- Hotfixes (`fix/`) may target main directly when urgency warrants it

This applies to all changes including docs, config, and demo code.

## Issue Management
Use the `/issue-tracker` skill for ALL issue operations. Never create issues manually without using the skill -- it enforces our conventions:
- Every issue references a design document
- Every issue starts in Backlog
- Issues flow: Backlog -> In Progress -> Done

## Development Conventions
- Python with FastAPI for services
- Kubernetes Operator in Python (kopf or operator-sdk)
- Red Hat UBI base images only
- FIPS compliance required
- Use Podman, not Docker
- Use Containerfile, not Dockerfile
- PostgreSQL (OOTB, ships with OpenShift) + pgvector for vector search
- PostgreSQL for graph queries (evolution path to dedicated graph DB)
- MinIO for S3/object storage
- MCP server via fips-agents CLI workflow

## Cluster Contexts

This project deploys to the **mcp-rhoai** cluster context. Other clusters are used for unrelated work. All are configured as named contexts in `~/.kube/config`:

- `mcp-rhoai` — MemoryHub's cluster (n7pd5, sandbox5167)
- `kagenti-rhoai` — Kagenti deployment cluster (gs4bz)
- `memory-hub-fips` — FIPS verification cluster (zks6c, sandbox417)

> **Note:** The FIPS context was previously `fips-rhoai` (l78nk, sandbox1834) which expired 2026-06-09. The main context was previously `workshop-cluster`, renamed to `mcp-rhoai` circa 2026-04-17. Old session notes and retros may reference old names.

**Always pass `--context mcp-rhoai`** on every `oc` / `kubectl` command for this project. Do not rely on the current context, and do not switch contexts with `oc login` or `oc config use-context` — that would break whichever session isn't expecting the switch.

```bash
# Correct — explicit context + explicit namespace
oc get pods --context mcp-rhoai -n memoryhub

# Wrong — relies on implicit current context
oc get pods -n memoryhub
```

This extends the existing `-n` namespace rule: explicit context *and* explicit namespace on every command.

## MCP Server (memory-hub-mcp/)
The MCP server lives in `memory-hub-mcp/` and was scaffolded from the fips-agents MCP template. Follow the workflow in order:

1. `/plan-tools` — Design tools, produces TOOLS_PLAN.md (no code)
2. `/create-tools` — Generate and implement tools via parallel subagents
3. `/exercise-tools` — Test from an agent's perspective, refine ergonomics
4. `/write-system-prompt` — Create SYSTEM_PROMPT.md for consuming agents
5. `/update-docs` — Update README and ARCHITECTURE docs
6. `/deploy-mcp PROJECT=memory-hub-mcp` — Deploy to OpenShift with verification

When working in the MCP server, read `memory-hub-mcp/CLAUDE.md` for import conventions, testing patterns, and architecture details. Key points:
- Always use `src.` prefix for imports
- Call decorated tools directly in tests — FastMCP 3's `@mcp.tool(...)` returns the function itself, no `.fn` access needed
- `fips-agents` is a global CLI (pipx), not in the venv
- Fix file permissions before deployment: `find src -name "*.py" -perm 600 -exec chmod 644 {} \;`

### MCP Tool Creation — MUST use fips-agents workflow
**Never create MCP tools by hand or via sub-agents.** Always use the slash command workflow: `/plan-tools` → `/create-tools` → `/exercise-tools`. Sub-agents cannot run slash commands and will skip the scaffold step, producing tools that lack the template's test structure, permission handling, and registration patterns. This was learned the hard way in Phase 2 — tools created by sub-agents had to be entirely redone. The fips-agents scaffold produces materially better tools with proper test coverage and consistent patterns. When adding tools in future sessions, follow this workflow in the main conversation context, not delegated to sub-agents.

## Onboarding and Process

If this is your first session on this project, read [CONTRIBUTING.md](CONTRIBUTING.md) before writing code. It covers repo layout, dev environment setup, PR expectations, and the same-commit consumer audit rule.

Use `/issue-tracker` for all issue operations (filing, updating, closing). Use `/retro` after completing a major feature, fixing a gnarly bug, or finishing a multi-session effort — retros are where the project's institutional knowledge accumulates (see `retrospectives/`).

## Design Documents
Shipped architecture and subsystem designs live in docs/. In-flight designs for unimplemented or skeleton-stage features live in planning/. Research investigations live in research/. Demo scripts live in demos/. When implementing a feature, always read the relevant design doc first. If the design doc is a skeleton or has TBD sections, flesh it out before implementing.

## Commit Messages
Use conventional commit format: `subsystem: Description in imperative mood`
Example: `memory-tree: Add versioning with isCurrent flag`

## Credential Hygiene

Credentials, API keys, and tokens must never appear in session summaries, plans, issues, or any committed documentation. Reference the secret's storage location instead (e.g., "stored in memoryhub-auth cluster secret" or "see ~/.config/memoryhub/api-key"). This applies to all key formats including hex-format keys (`mh-dev-<hex>`), OAuth client secrets, and database passwords. Incident: a hex-format API key committed in a session summary (2026-07-14) required rotation and git history scrubbing.

## Secrets and Env Var Reference

Where credentials live and how to use them. This eliminates "secrets archaeology" at session start.

**Local developer machine:**
- `~/.config/memoryhub/api-key` -- MemoryHub API key for SDK/MCP client auth
- `~/.secrets` -- shell-sourceable file with `GEMINI_API_KEY`, `GOOGLE_API_KEY`, etc.

**Cluster Secrets (mcp-rhoai context):**

| Secret | Namespace | Keys | Used by |
|--------|-----------|------|---------|
| `memoryhub-pg-credentials` | `memoryhub-db` | `POSTGRES_PASSWORD` | DB access across all services |
| `gemini-api-key` | `memory-hub-mcp` | `api-key` | MCP server extraction LLM auth |
| `gemini-api-key` | `memoryhub-eval` | `api-key` | EvalHub adapter answer/judge LLM auth |
| `evalhub-db-credentials` | `memoryhub-eval` | `db-url` | EvalHub PostgreSQL connection |

**MCP server env vars (deployment `memory-hub-mcp` in `memory-hub-mcp` namespace):**
- Connection: `MCP_TRANSPORT`, `MCP_HTTP_HOST`, `MCP_HTTP_PORT`, `MCP_HTTP_PATH`
- Auth: `AUTH_JWKS_URI`, `AUTH_ISSUER`, `AUTH_AUDIENCE`, `AUTH_API_KEY_VALIDATE_URL`, `AUTH_INTERNAL_SERVICE_KEY`, `MEMORYHUB_USERS_FILE`
- Infrastructure: `MEMORYHUB_VALKEY_URL`, `MEMORYHUB_S3_ENDPOINT`, `MEMORYHUB_S3_ACCESS_KEY`, `MEMORYHUB_S3_SECRET_KEY`, `MEMORYHUB_S3_BUCKET`
- Dreaming extraction: `MEMORYHUB_CONV_EXTRACTION_MODEL`, `MEMORYHUB_CONV_EXTRACTION_MODEL_URL`, `MEMORYHUB_CONV_EXTRACTION_API_KEY` (from secret)

**Dreaming extraction LLM config:**
The MCP server calls an OpenAI-compatible `/chat/completions` endpoint for fact extraction. The URL must NOT include `/v1/` (the code appends `/chat/completions` directly). For Gemini, use `https://generativelanguage.googleapis.com/v1beta/openai` as the URL. The API key goes in a Bearer token header. Model names must be current (check `https://generativelanguage.googleapis.com/v1beta/models?key=<key>` for available models; dated preview names get deprecated).

**EvalHub adapter env vars (injected by `deploy-evalhub.sh` provider registration):**
- `MEMORYHUB_URL` -- internal MCP service: `http://memory-hub-mcp.memory-hub-mcp.svc:8080/mcp/`
- `MEMORYHUB_API_KEY` -- from `~/.config/memoryhub/api-key` at registration time
- `MEMORYHUB_DB_HOST` -- internal DB service: `memoryhub-pg.memoryhub-db.svc.cluster.local`
- `MEMORYHUB_DB_PORT` -- `5432` (internal, not the port-forward 25432)
- `MEMORYHUB_DB_USER` -- `memoryhub`
- `MEMORYHUB_DB_PASS` -- from `memoryhub-pg-credentials` secret at registration time

**Rebuilding after code changes (3 surfaces):**
1. **MCP server** -- `bash memory-hub-mcp/deploy/build-context.sh && oc start-build memory-hub-mcp --from-dir=memory-hub-mcp/.build-context --follow --context mcp-rhoai -n memory-hub-mcp` then update deployment image digest
2. **EvalHub adapter** -- create build context dir with `benchmarks/{amb-harness,evalhub-adapter}/` + `sdk/`, then `oc start-build memoryhub-evalhub-adapter --from-dir=<ctx> --follow --context mcp-rhoai -n memoryhub-eval`
3. **Local harness** -- `cd benchmarks/amb-harness && uv run omb ...` (uses editable SDK)

## Deployment Reproducibility (IaC)

Every change must be deployable from code without manual steps. When implementing a feature, verify that all of the following are captured in version-controlled code:

**Database schema** — Services that own a database MUST use Alembic for schema management. `create_all()` is not sufficient because it cannot add columns to existing tables. Every model change requires an Alembic migration committed alongside the code change. Deploy scripts run `alembic upgrade head` before rolling out new code.

**Kubernetes resources** — Any K8s resource the service depends on (Secrets, ConfigMaps, CRDs, cluster-scoped resources) must either be created by the deploy script or documented as an explicit prerequisite with a creation command. If a deploy.sh generates a Secret (like RSA keys), every new Secret the service needs should follow the same pattern. Never leave a resource that only exists because someone ran a one-off `oc create` command.

**API completeness** — When adding a column to a model that is managed through an admin API, the API schemas (request and response) must be updated in the same PR. If the only way to set a field is direct DB manipulation, the field is not shippable.

**Cross-namespace Secrets** — Services that need credentials from another namespace (e.g., the auth service needs DB credentials from `memoryhub-db`) must have those Secrets copied by `deploy-full.sh` using the `copy_secret` helper. The target Secret is created idempotently (skip if exists). Never assume a Secret from a previous install survived — namespace deletion removes everything.

**SCC grants** — MinIO and Valkey require `anyuid` SCC on their ServiceAccounts. The deploy script must grant this after applying the kustomize manifests. Without it, pods fail with SCC validation errors on fresh namespaces.

**The golden test** — There are two variants, both must pass with zero manual intervention:
- **Preserve-DB** (most common): `scripts/uninstall-full.sh --skip-db --yes && scripts/deploy-full.sh`
- **Full fresh**: `scripts/uninstall-full.sh --yes && scripts/deploy-full.sh`

The preserve-DB variant is the default smoke test after infrastructure changes. The full-fresh variant tests first-install password generation and DB bootstrap. If either fails, `deploy-full.sh` is incomplete. Run the preserve-DB variant before marking any infrastructure change as done.

**The checklist** — Before marking a feature as deployed, verify:
- [ ] Schema changes have an Alembic migration
- [ ] deploy-full.sh creates all required Secrets (with generate-if-missing pattern)
- [ ] deploy-full.sh applies all required K8s resources (with idempotent guards)
- [ ] deploy-full.sh grants required SCCs for pods that need them
- [ ] Cross-namespace Secrets are copied by deploy-full.sh, not created manually
- [ ] Admin/management APIs expose all user-facing model fields
- [ ] requirements.txt matches pyproject.toml dependencies (container builds use requirements.txt)
- [ ] Golden test (preserve-DB): `scripts/uninstall-full.sh --skip-db --yes && scripts/deploy-full.sh` succeeds
- [ ] Golden test (full fresh): `scripts/uninstall-full.sh --yes && scripts/deploy-full.sh` succeeds on a new cluster

## Deploy Safety

**Never delegate deploy or uninstall scripts to sub-agents.** `deploy-full.sh` and `uninstall-full.sh` can destroy the database and all stored memories. Run them in the main conversation context where the operator sees each command and can intervene. A terminal-worker sub-agent misinterpreted "run the full deployment" as "clean-slate install" and destroyed the production database (2026-05-19; recovered from backup).

When deploying, always use `deploy-full.sh` directly (it preserves the existing DB by default). The golden test variants (`uninstall --skip-db` or full `uninstall`) are for verification, not routine deploys.

After restoring from backup, verify `alembic_version` matches the actual schema before running `upgrade head`. Backup dumps can have stale version markers that cause migrations to fail on duplicate columns.

## Verify Before Propagating

Capability claims about our own codebase, deployed infrastructure, or third-party software get verified against code, docs, or live state before they propagate into issues, plans, or reviews. A 10-minute doc read beats a feature request, and a grep beats a rebuild.

Before writing an issue that assumes "X doesn't exist" or "Y can't do Z," check. Before scoping work around a capability you haven't confirmed, confirm it. Three citations from the dreaming arc retro (2026-07-13): the chunking investigation assumed chunking wasn't active (it was), the PVC fix assumed the operator wouldn't reconcile it away (it did), and the sidecar triage assumed forwarding worked out of the box (it didn't).

When verification reveals a genuine gap that warrants a code change, that change goes through a dedicated PR with explicit human approval, not silently bundled into the current branch.

## MemoryHub-First for Benchmark Blockers

When eval/benchmark work hits a MemoryHub limitation (server, MCP tool
surface, SDK), stop and surface it before building a harness-side
workaround. MemoryHub is the product; the benchmark is the instrument. A
workaround in the harness hides a product gap and makes the benchmarked
system diverge from what customers get.

Litmus: "Would a customer hit this?" Yes -> file the MemoryHub issue
(limitation, impact, proposed fix) and surface it before proceeding. No
(pure benchmark scaffolding: skip_ingestion, corpus reset,
checkpoint/resume) -> harness-side is fine.

Precedents: tenant_id hardcoding (#368, correctly fixed in MemoryHub),
disabled_signals (correctly added to the SDK), SDK-to-MCP send limitation
(surfaced 2026-07-14).

## Testing
- pytest for all Python testing
- 80%+ coverage target
- Test error paths explicitly

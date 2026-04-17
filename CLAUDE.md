# MemoryHub

## Project Overview
MemoryHub is a Kubernetes-native agent memory component for OpenShift AI. See docs/ARCHITECTURE.md for the full architecture and docs/SYSTEMS.md for subsystem inventory.

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

This project deploys to the **mcp-rhoai** cluster context. Other clusters (kagenti-rhoai, fips-rhoai) are used for unrelated work. All are configured as named contexts in `~/.kube/config`:

- `mcp-rhoai` — MemoryHub's cluster (n7pd5, sandbox5167)
- `kagenti-rhoai` — Kagenti deployment cluster (gs4bz)
- `fips-rhoai` — FIPS cluster (l78nk)

> **Note:** The context was previously named `workshop-cluster`. It was renamed to `mcp-rhoai` circa 2026-04-17. Old session notes and retros may reference the old name.

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

## Testing
- pytest for all Python testing
- 80%+ coverage target
- Test error paths explicitly

# Next Session: RBAC Design + Authorino Verification

## Goal

Merge #7 and #13 into a single RBAC/governance design, then verify Authorino on the cluster. This is foundational work that the dashboard UI (#19) will build on — we want real auth, not mocks.

## What's deployed and working

- MCP server with 12 tools on OpenShift (route: `https://mcp-server-memory-hub-mcp.apps.cluster-n7pd5.n7pd5.sandbox5167.opentlc.com/mcp/`)
- PostgreSQL + pgvector in `memoryhub-db` namespace
- Real embeddings via all-MiniLM-L6-v2
- API key auth with users configmap
- Deterministic curation pipeline (secrets scan, PII detection, embedding dedup)
- Contradiction tracking with `contradiction_reports` table + `resolve_contradiction` service function
- Lazy rule seeding, one-command deployment (`make deploy-all`)
- 106 unit tests + 69 MCP tests = 175 total, all passing
- Authorino is installed on the cluster (newly added)

## What was completed last session

- **#20** — `contradiction_reports` table: model, migration 005, service function, MCP tool update, deployed and verified on cluster
- **#23** — Storage-layer design doc updated with contradiction tracking section
- **#9** — Descoped (operator CRD replaced by RHOAI dashboard integration)
- **#25, #26, #27** — Created tracking issues for CLI client, Python SDK, LlamaStack integration (future phase)
- `resolve_contradiction` service function + 3 tests (not yet an MCP tool — needs `/plan-tools` workflow)
- Retro at `retrospectives/2026-04-05_contradiction-reports/RETRO.md`

## Session plan

### 1. Merge #7 and #13

These two issues overlap significantly:
- **#7** (governance: access control + audit trail) — covers the full governance design
- **#13** (governance: agent-level memory access control) — focuses on RBAC for multi-tenant

Close #13 as a duplicate of #7, or merge their acceptance criteria into #7. The design doc is `docs/governance.md` which already has a solid framework for access control tiers — it needs to be extended with implementation details.

### 2. RBAC design work in `docs/governance.md`

The existing doc defines the *policy* (who should access what at each scope). What's missing is the *mechanism*:

- **How does the MCP server enforce scope access?** Currently `auth.py` validates API keys and returns a user identity + scope list. But `search_memory` and `read_memory` don't gate results by ownership. Design the enforcement points.
- **Agent identity model.** Is an agent always acting on behalf of a user? Can an agent have its own identity (e.g., the curator agent)? How does this map to API keys?
- **OpenShift OAuth/OIDC integration.** The current auth is API-key-only. For the dashboard, we'll need browser-based auth. Authorino can bridge this — API keys for agents, OIDC tokens for humans, both validated at the route level.
- **Audit trail schema.** The design doc describes what should be logged but there's no table schema yet. Design the `audit_log` table.
- **`get_similar_memories` visibility gap.** This tool currently returns similar memories regardless of ownership. Needs scope filtering.

### 3. Verify Authorino on the cluster (#22)

Authorino is now installed. Verify:
- `oc api-resources | grep authorino` — what CRD version is available?
- Check if the API version in `docs/RHOAI-DEMO/landing-page-design.md` matches what's deployed
- Test a minimal AuthConfig CR against the MCP server route (API key validation via Authorino instead of application-level auth)
- Update the design doc if the API version or field syntax differs

### 4. Close out

- Update `docs/governance.md` with the design decisions
- Close/merge #7 and #13
- Close #22 if Authorino is verified
- Write retro

## Open backlog (for context, not this session)

- **#19** — RHOAI dashboard UI (next after RBAC)
- **#21** — Evaluate graph viz library
- **#24** — Write getStartedMarkDown for OdhApplication CR
- **#10** — Observability: Grafana dashboards + Prometheus metrics
- **#11** — Org-ingestion pipeline design
- **#5** — MinIO for S3 object storage
- **#25, #26, #27** — CLI, SDK, LlamaStack integration (future phase)

## Key conventions

- MCP tools MUST be created via `/plan-tools` → `/create-tools` → `/exercise-tools`
- Delete existing deployment before redeploying (`make clean-mcp` then `make deploy-mcp`)
- Use `-n namespace` flags, never `oc project`
- Run `make test` before committing
- Deploy and verify on cluster as part of implementation, not as an afterthought

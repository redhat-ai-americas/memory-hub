## Next Session Prompt

We're continuing development on MemoryHub. Here's where things stand.

### What's deployed and working

- MCP server with 12 tools on OpenShift (live at the route in deploy/openshift.yaml)
- PostgreSQL + pgvector in `memoryhub-db` namespace
- Real embeddings via all-MiniLM-L6-v2
- API key auth with users configmap
- Deterministic curation pipeline (secrets scan, PII detection, embedding dedup with similarity feedback)
- Lazy rule seeding — default curation rules auto-seed on first write, no manual steps
- One-command deployment: `make deploy-all` from repo root
- 102 unit tests (SQLite) + 14 integration tests (real pgvector) + 67 MCP tests = 183 total, all passing

### What was completed last session

- #18 — Lazy curation rule seeding
- #14 — Deployment automation (`make deploy-all`, `make deploy-mcp`, `make migrate`)
- #17 — Integration tests against real PostgreSQL + pgvector (found and fixed a cosine score clamping bug)
- #15 — De-scoped (no UBI pgvector image exists, not worth building for demo)
- Consolidated duplicate openshift.yaml manifests
- Consolidated duplicate test fixtures into shared conftest
- Retro at `retrospectives/2026-04-04_infra-automation/RETRO.md`

### Open backlog (roughly prioritized)

- **#13** — RBAC design for multi-tenant memory access (overlaps with #7)
- **#7** — Governance: access control + audit trail (overlaps with #13 — consider merging)
- **#19** — RHOAI dashboard integration: landing page UI (design docs in `docs/RHOAI-DEMO/`)
- **#9** — Operator CRD schema (deferred to next phase)
- **#10** — Observability: Grafana dashboards + Prometheus metrics
- **#11** — Org-ingestion pipeline design
- **#5** — MinIO for S3 object storage

### Key conventions (see CLAUDE.md for full details)

- MCP tools MUST be created via `/plan-tools` → `/create-tools` → `/exercise-tools`, never delegated to sub-agents
- Delete existing OpenShift deployment before redeploying to avoid stale images
- Use `-n namespace` flags, never `oc project`
- Run `make test` before committing (excludes integration tests by default)
- Integration tests: `make test-integration` (requires podman machine running)
- The `.env` file has Llama 4 Scout and Tavily API keys for future agent work

### Suggested starting point

Read the retro, search MemoryHub for prior context, then let's discuss which items to tackle. #13/#7 are the next design work, #19 is the next feature work if we want something visible for the demo.

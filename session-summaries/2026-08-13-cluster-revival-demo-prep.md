# Session Summary — 2026-08-13 · soc-demo · Cluster revival and demo prep

**Plan:** Ad-hoc (no NEXT_SESSION)   **Commits:** none (cluster ops + 1 untracked file fix)
**Deployed:** mcp-rhoai cluster (all services)   **Model:** Opus 4.6

## Plan vs. actual
Planned: fix Admin UI 500 errors, get the cluster healthy for demo. Shipped: full cluster revival, all MCP tools verified, dreaming pipeline fixed and switched to on-cluster model, SOC demo deployed and tested, demo plan written. Scope expanded naturally as each fix revealed the next issue.

## Shipped
- Applied Alembic migration 027 (logical_id column) to mcp-rhoai DB — root cause of Admin UI 500 errors
- Full redeploy via `deploy-full.sh --skip-db --skip-migrations --skip-models` — rebuilt MCP server, auth server, UI, RHOAI tile
- Switched `MEMORYHUB_EMBEDDING_URL` from defunct `all-minilm-l6-v2` (scaled to 0) to running `granite-embedding` service
- Fixed dreaming pipeline: `MEMORYHUB_CONV_EXTRACTION_API_KEY` was missing entirely; created `gemini-api-key` secret in memory-hub-mcp namespace
- Switched dreaming extraction from Gemini API (`gemini-3.5-flash-lite`) to on-cluster `RedHatAI/gpt-oss-20b` via vLLM — eliminates external API dependency
- Exercised all 24 MCP tool actions (register_session, memory write/search/read/update/delete/list/similar/relationships/relate/report/status/reconstruct/set_focus/focus_history/list_projects, thread create/append/get/list/extract/archive/delete, admin_memory)
- SOC demo frontend deployed to cluster (`soc-demo` namespace) — both frontend and sidecar containers running; trigger buttons work from browser
- Fixed sidecar Containerfile: `COPY` + `RUN chmod` fails on UBI non-root builds; switched to `COPY --chmod=755`
- Backed up database: `local/backups/memoryhub-mcp-rhoai-20260813-144745.sql.gz` (69MB)
- Wrote demo plan: `demos/DEMO_PLAN_2026-08-14.md` — three-segment plan for extended team demo

## Verification & confidence
- All MCP tool actions tested live against the cluster (24/24 pass, including dreaming extraction with on-cluster model)
- SOC frontend replay tested end-to-end from cluster (37/37 events, sidecar trigger API verified)
- Admin UI graph endpoint returns 7,262 nodes / 882 edges (was returning 500 before migration)
- Embedding writes and semantic search verified via CLI smoke test
- Confidence: **high** — every fix was verified against the live cluster

## Judgment calls & deviations
- Switched to gpt-oss-20b for dreaming instead of keeping Gemini. Tradeoff: ~17s vs ~2s per extraction window, but no external dependency and data stays on-cluster. User approved.
- Left the Gemini API key secret in place (it's already created). Not harmful and could be useful as fallback.
- Didn't run full `uninstall + deploy-full.sh` (the golden test). Used the targeted approach: migration + selective redeploy with `--skip-db --skip-migrations --skip-models`. User explicitly approved this as the older cluster.

## Backlog delta
Filed: none. Closed: none. Memory: none new.
Deferred: pre-existing auth test failures (115 errors from fixture issues, not session-related). Pre-existing lint error in `memory-hub-mcp/src/tools/manage_project.py:253` (E501, line too long) — not from this session.

## Drift & forward-collisions
- Backward: none — no issues touched
- Forward: none

## For the reviewer
- Sanity-check: the env var changes (embedding URL, extraction model/URL/key) were applied via `oc set env` and `oc patch` directly to deployments. They'll persist across pod restarts but would be overwritten by a fresh `deploy-full.sh` that doesn't set them. The deploy scripts should be updated to include these env vars if this cluster configuration needs to be reproducible.
- Thin verification: core test suite didn't complete (embedding model download timeout during session close). Auth tests have 115 pre-existing errors.
- Wants guidance: should the `deploy-full.sh` or MCP `deploy.sh` scripts be updated to include the dreaming extraction env vars so they survive a full redeploy?

## Risks / watch-fors
- The mcp-rhoai cluster is a sandbox — it will expire eventually. The DB backup at `local/backups/` preserves the data.
- `gpt-oss-20b` model deployment in `gpt-oss-model` namespace has been running 121 days. If it restarts or gets evicted, dreaming extraction will fail silently (the MCP server logs "embedding service unavailable"-style errors but doesn't crash).
- SOC demo sidecar's "LIVE" mode requires `soc-harness-config` secret with a real `soc-forensics-url`. Currently set to placeholder. REPLAY mode works fine without it.

# Next session context

## Where things stand (as of 2026-04-11)

### Repo + CI
- Main includes uncommitted #120 work (two-tier storage). Commit and PR before starting new work.
- No open PRs.
- 70 open issues (68 + #173 suggest_merge consolidation + #174 get_memory_history consolidation), 65 items in Backlog, 35 Done on the project board.
- SDK v0.4.0, CLI v0.3.0.

### Cluster
- Sandbox `cluster-n7pd5.n7pd5.sandbox5167.opentlc.com` healthy.
- MCP pod running. DB pod running in memoryhub-db.
- MinIO manifests created in `deploy/minio/` but NOT yet deployed. Deploy before testing #120 end-to-end.
- Migrations 001-010 applied. No new migration needed for #120 (schema already supports storage_type/content_ref).

### Recent work (this session)
- #120 (two-tier storage with semantic chunking) — implemented but not yet committed/merged
  - S3 adapter: `src/memoryhub_core/storage/s3.py` (async minio wrapper)
  - Chunker: `src/memoryhub_core/storage/chunker.py` (paragraph/sentence splitting, ~256 token chunks)
  - Service layer: `create_memory`, `update_memory`, `delete_memory` all accept optional `s3_adapter`
  - MCP tools: `read_memory` gains `hydrate` parameter, write/update/delete pass S3 adapter through
  - Search: chunk hits include `parent_hint` guiding agent to full content
  - No new MCP tool added — consolidated into existing `read_memory` per Anthropic tool design guidance
  - Design doc `docs/storage-layer.md` updated: all 5 TBDs closed
  - MinIO manifests: `deploy/minio/` (deployment, service, PVC, kustomization)
  - Tests: 266 root tests passing (20 new for S3/chunker, 10 new for service layer)
  - Pre-existing bug fixed: `scope_id` was dropped in `update_memory` (missing from node constructor)
- #173 filed — Consolidate `suggest_merge` into `create_relationship` (Backlog)
- #174 filed — Consolidate `get_memory_history` into `read_memory` (Backlog)
- Tool audit completed — 15 tools total, two consolidation opportunities identified

### Remaining #120 follow-ups
- Deploy MinIO to cluster and test end-to-end
- Call `ensure_bucket()` at MCP server startup (lifespan hook) rather than deferring to first write
- Pin MinIO image tag in `deploy/minio/deployment.yaml`
- Periodic S3 reaper for expired versions (out of scope for initial PR)

## Session goal: #168 — Conversation thread persistence

### What it is
Design and implement conversation thread persistence as a first-class governed subsystem. Extends MemoryHub from extracted observations (memories) to raw conversation threads — with the same governance guarantees (scope isolation, tenant isolation, RBAC, audit trails, retention policies).

### Research done
- `research/conversation-persistence-survey.md` completed 2026-04-10
- Key finding: governed conversation persistence is genuine whitespace. No framework provides thread-level RBAC, auditable conversation-to-memory pipelines, retention policy enforcement with cascade to extracted memories, or cross-agent handoff governance.
- EU AI Act (August 2026 deadline for high-risk systems) makes audit trails from conversation to memory to decision mandatory.

### Design doc needed
- `docs/conversation-persistence.md` — author as part of this issue
- Should cover: data model (Thread entity), MCP tools (start_thread, append_message, read_thread, etc.), governance model, integration with existing subsystems
- Read the research survey and #168 issue first

### Open design questions from #168
1. Thread entity: new table vs. reusing memory_nodes with a special branch_type?
2. Message ordering: sequence numbers vs. timestamps?
3. Extraction pipeline: how do conversations produce memories? Manual, automatic, or hybrid?
4. Retention cascade: when a thread expires, what happens to memories extracted from it?
5. Cross-agent handoff: how does one agent transfer a conversation to another with proper RBAC?
6. Tool consolidation: how many new tools does this need? Follow Anthropic's guidance — fewer, more capable tools.

## Things to know before touching anything

### MemoryHub MCP session
- Read `~/.config/memoryhub/api-key` at session start.
- Deploy is safe mid-session.

### Cluster
```
Cluster:       cluster-n7pd5.n7pd5.sandbox5167.opentlc.com (OpenTLC sandbox)
Namespaces:    memory-hub-mcp, memoryhub-auth, memoryhub-db
```

### Cluster login
```bash
oc whoami --show-server
source .env && oc login "$OC_SERVER" -u "$OC_USER" -p "$OC_PASSWORD" --insecure-skip-tls-verify
```

### Alembic migrations
Migrations live in `alembic/versions/`. Current head is migration 010 (`domains`). Migrations are NOT auto-run on server startup — apply manually via port-forward:
```bash
oc port-forward svc/memoryhub-pg 15432:5432 -n memoryhub-db &
MEMORYHUB_DB_HOST=localhost MEMORYHUB_DB_PORT=15432 MEMORYHUB_DB_NAME=memoryhub \
  MEMORYHUB_DB_USER=memoryhub MEMORYHUB_DB_PASSWORD=memoryhub-dev-password \
  .venv/bin/alembic upgrade head
```

### Merge flow
- Self-review: `gh pr merge <num> --admin --rebase --delete-branch`
- Note: branch protection currently requires 1 approving review; no other approvers on the repo yet, so admin override or temporarily lowering the requirement is needed for solo merges.

### Commits
- `subsystem: Imperative summary`
- `Assisted-by: Claude Code (Opus 4.6)` trailer
- Never `Co-authored-by:` or `Signed-off-by:`

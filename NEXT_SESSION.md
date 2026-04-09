# Next session: Campaign & domain framework — schema foundations (#155, #156)

## Context in one paragraph

The #97 tool-error standardization is complete (all 12 sub-issues landed, umbrella closed). MCP server deployed and verified (15/15 tools live). SDK published to PyPI as `memoryhub` v0.2.0 (typed exception hierarchy). CLI published as `memoryhub-cli` v0.1.1 (first publish — config init wizard with API key check, post-write summary, context-aware contradiction blurb). The `memoryhub-cli` is installed globally via pipx and was successfully used to onboard the `retrieval-hub` project. A design exploration for cross-project knowledge sharing produced `planning/campaign-domain-framework.md` — introduces campaign (temporal scope for bounded initiatives) and domain (crosscutting knowledge dimension). Eight sub-issues filed (#155-#161) under umbrella #154. Board cleaned: 20 stale items moved to Done. Main is green on commit `adf0233`, all CI jobs passing, no open PRs.

## What shipped this session

### #97 close-out
- #138 docs update (PR #151): TOOLS_PLAN.md error cases for all 15 tools, README error handling section, docs/mcp-server.md updated
- #139 umbrella close-out: all acceptance criteria checked, #97 closed
- MCP server deployed with #97 changes (PG password placeholder fixed)

### PyPI publishing
- `memoryhub` SDK v0.2.0 published (tag `sdk/v0.2.0`) — #97 exception hierarchy
- `memoryhub-cli` v0.1.1 published (tag `memoryhub-cli/v0.1.1`) — first publish
- Release workflow extended to handle `memoryhub-cli/v*.*.*` tags
- CI test job added for CLI with paths-filter
- Issues #25, #26, #35 closed as shipped

### CLI UX improvements
- Config init: context-aware contradiction blurb (no more "Focused mode" when user chose adaptive)
- Config init: post-write summary (shape, mode mapping, loading pattern, focus source)
- Config init: API key verification (#153, closed)
- Config init: rule file templates reference `~/.config/memoryhub/api-key` instead of `<your-api-key>`
- Fixed doubled default in prompt (`[4] [4]` → `[4]`)

### Campaign & domain framework
- Design doc: `planning/campaign-domain-framework.md`
- 8 sub-issues filed (#155-#161) under umbrella #154
- Resolved: campaign writes are lower friction (project access = campaign access), emergent domain vocabulary, MVP is Phases 1-2

### Board cleanup
- 20 stale items moved from Backlog to Done (#25, #26, #35, #48, #50-61, #97, #138, #139, #153)

## Where things stand

### Repo + CI
- Main on `adf0233`. All CI jobs green.
- No open PRs.
- 206 MCP server tests, 88 SDK tests, 27 CLI tests.

### Cluster
- Sandbox `cluster-n7pd5.n7pd5.sandbox5167.opentlc.com` healthy.
- MCP server deployed with all #97 changes (15 tools verified via mcp-test-mcp).

### Project board
- 75 items in Backlog (down from 95 after cleanup)
- 8 new campaign/domain issues (#154-#161) in Backlog
- No items In Progress

### PyPI
- `memoryhub` v0.2.0 live
- `memoryhub-cli` v0.1.1 live

## Plan: Campaign & domain MVP (#154)

### Land order

| Step | Issue | Title | Depends on |
|------|-------|-------|------------|
| 1a | #155 | Schema: campaign scope + campaigns/membership tables | — |
| 1b | #156 | Schema: domains array on memory table | — |
| 2 | #157 | RBAC: campaign membership resolution | #155 |
| 3 | #159 | write/update with campaign scope + domains | #155, #156, #157 |
| 4 | #158 | search with campaign + domain filter | #155, #156, #157 |
| 5 | #161 | Domain-aware retrieval boosting | #158 |
| 6 | #160 | CLI config init campaign enrollment | #155 |

Steps 1a and 1b are independent schema migrations — start here.

### This session's target: #155 + #156 (schema foundations)

**#155 — Campaign scope + tables:**
1. Alembic migration adding `campaign` to the scope enum
2. `campaigns` table: id (UUID), name, description, status (active/completed/archived), default_ttl, created_at, updated_at
3. `campaign_memberships` table: campaign_id (FK), project_id, enrolled_at, enrolled_by
4. SQLAlchemy models for both tables
5. Pydantic schemas

**#156 — Domains array:**
1. Alembic migration adding `domains` text array column to `memory_nodes` (nullable, default empty)
2. GIN index on domains for containment queries (`@>`)
3. Update MemoryNode SQLAlchemy model
4. Update Pydantic schema to include `domains: list[str] | None`

### After schema lands

If time permits, continue to #157 (RBAC) and #159 (write/update). The RBAC change is in `memoryhub_core` service layer — `authorize_read` and `authorize_write` need campaign membership checks. The write/update changes are in MCP tool layer — accepting `campaign` scope and `domains` parameter.

### Stretch: #158 (search) and #160 (CLI)

Search integration is the payoff — campaign memories appearing in search results for enrolled projects. CLI enrollment is lower priority (users can edit `.memoryhub.yaml` by hand until the wizard catches up).

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
Migrations live in `alembic/versions/`. Current head is migration 007 (`deleted_at` column). New migrations should be sequential (008, 009). Run locally with:
```bash
cd /Users/wjackson/Developer/memory-hub
MEMORYHUB_DB_HOST=localhost MEMORYHUB_DB_PORT=5432 MEMORYHUB_DB_NAME=memoryhub MEMORYHUB_DB_USER=memoryhub MEMORYHUB_DB_PASSWORD=<from-cluster> alembic upgrade head
```

For cluster deployment, migrations run automatically on MCP server startup via the `alembic upgrade head` in the entrypoint.

### Merge flow
- Self-review: `gh pr merge <num> --admin --rebase --delete-branch`
- Always linear history

### Commits
- `subsystem: Imperative summary`
- `Assisted-by: Claude Code (Opus 4.6)` trailer
- Never `Co-authored-by:` or `Signed-off-by:`

### Issue sanity check
Before referencing any issue:
```bash
scripts/issue-sanity-check.sh <issue-number>
```

## Background reading

- [`planning/campaign-domain-framework.md`](planning/campaign-domain-framework.md) — the full design
- [`docs/governance.md`](docs/governance.md) — current scope model and RBAC
- [`docs/curator-agent.md`](docs/curator-agent.md) — current curation pipeline (Phase 3 extends this)
- `alembic/versions/` — existing migrations for schema context
- `src/memoryhub/models/` — SQLAlchemy models
- `src/memoryhub/schemas/` — Pydantic schemas

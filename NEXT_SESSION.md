# Next session: SDK + CLI campaign/domain parameter catch-up (#164)

## Context in one paragraph

Campaign & domain framework is fully shipped server-side — all MCP tools accept `project_id` for campaign enrollment verification and `domains` for crosscutting knowledge tags. The read-path wiring (#162) landed this session, closing the last gap where per-ID tools returned 403 on campaign-scoped direct lookups. However, the Python SDK (`memoryhub` on PyPI) has typed wrapper methods that don't expose `project_id` or `domains`, so SDK consumers can't use campaign features. The CLI config init already prompts for campaign enrollment but may not wire `project_id` through to tool calls. Filed as #164. Main is green on commit `3e3f78c`, all CI passing, MCP server deployed with 15 tools verified.

## What shipped this session

### #162 — Wire campaign_ids into read-path tools (merged)
- 8 tools modified: read_memory, get_memory_history, get_similar_memories, report_contradiction, create_relationship, suggest_merge, get_relationships, delete_memory
- Each now accepts optional `project_id`; when target memory has scope="campaign", requires it and resolves campaign_ids via `get_campaigns_for_project` before authz check
- get_relationships uses eager resolution with silent omit for post-fetch RBAC
- 24 new tests in `test_campaign_read_path.py`
- MCP server redeployed, 15/15 tools verified via mcp-test-mcp

### Database migrations catch-up
- DB was at migration 008 (sandbox had drifted); applied 009 (campaigns) + 010 (domains) via port-forward + alembic upgrade head
- Confirmed: campaigns table, campaign_memberships table, domains column all present
- MemoryHub search_memory working end-to-end (domains column error resolved)

### #47 — Already closed
- Was closed on 2026-04-07, before this session started

## Where things stand

### Repo + CI
- Main on `3e3f78c`. All CI jobs green.
- No open PRs.
- 246 MCP server tests, 88 SDK tests (across 3 Python versions), 32 CLI tests.

### Cluster
- Sandbox `cluster-n7pd5.n7pd5.sandbox5167.opentlc.com` healthy.
- MCP server deployed with full campaign/domain support (15 tools verified).
- Migrations 001-010 applied.

### Project board
- 85 items in Backlog (including new #164)
- No items In Progress

### PyPI
- `memoryhub` v0.3.0 live (missing campaign/domain params)
- `memoryhub-cli` v0.2.0 live (missing project_id passthrough)

## Plan: #164

### SDK methods needing `project_id` added

All in `sdk/src/memoryhub/client.py`:

| Method | MCP tool | Also needs `domains`? |
|--------|----------|----------------------|
| `read()` | read_memory | no |
| `get_history()` | get_memory_history | no |
| `get_similar()` | get_similar_memories | no |
| `get_relationships()` | get_relationships | no |
| `create_relationship()` | create_relationship | no |
| `suggest_merge()` | suggest_merge | no |
| `report_contradiction()` | report_contradiction | no |
| `delete()` | delete_memory | no |
| `write()` | write_memory | yes (`domains`, `project_id`) |
| `update()` | update_memory | yes (`domains`, `project_id`) |
| `search()` | search_memory | yes (`domains`, `project_id`) |

### SDK search() check

Verify whether `search()` already passes `project_id` and `domains` from the v0.3.0 release. If not, add them.

### CLI passthrough

- CLI config init already prompts for campaign enrollment (#160)
- Check if the CLI passes `project_id` from `.memoryhub.yaml` config when calling tools
- If not, wire it through for all affected commands

### Versioning

- SDK: bump to v0.4.0 (additive parameter changes = minor)
- CLI: bump to v0.3.0 if changes needed

### Sync methods

The SDK also has `read_sync()`, `delete_sync()`, and other `_sync` wrappers — these delegate to the async versions so they should inherit the new params, but verify.

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

### MCP tool work
Per project memory: do MCP tool work in the main conversation context, not delegated to sub-agents. But #164 is SDK/CLI work, not MCP tool changes — sub-agents are fine.

## Background reading

- [`planning/campaign-domain-framework.md`](planning/campaign-domain-framework.md) — the full campaign/domain design
- [`sdk/src/memoryhub/client.py`](sdk/src/memoryhub/client.py) — SDK typed client (the file to modify)
- [`memoryhub-cli/`](memoryhub-cli/) — CLI source
- [`docs/mcp-server.md`](docs/mcp-server.md) — tool surface with campaign/domain parameters (the server-side contract)

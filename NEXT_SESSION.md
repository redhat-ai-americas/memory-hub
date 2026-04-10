# Next session: Campaign read-path wiring + similar-memories bug fix (#162, #47)

## Context in one paragraph

The campaign & domain framework MVP is complete — all 7 sub-issues (#155-#161) under umbrella #154 shipped and deployed. Campaign is a new scope between project and organizational with enrollment-based RBAC. Domains are crosscutting knowledge tags with RRF-integrated retrieval boosting. MCP server deployed with migrations 009+010 (campaigns/memberships tables, domains TEXT[] column), 15/15 tools verified. SDK v0.3.0 and CLI v0.2.0 published to PyPI. Docs updated. One known gap: per-ID tools (read_memory, get_memory_history, etc.) don't resolve campaign_ids, so campaign-scoped memories return 403 on direct lookup. Filed as #162. Separately, #47 (get_similar_memories returns empty due to broken post-fetch RBAC filter) is a correctness bug that touches the same authz area. Main is green on commit `1a0419f`, all CI jobs passing, no open PRs.

## What shipped last session

### Campaign & domain framework (#154 umbrella — closed)
- #155 + #156: Schema foundations — migrations 009 (campaigns + memberships tables) and 010 (domains TEXT[] with GIN index), SQLAlchemy models, Pydantic schemas
- #157: RBAC campaign membership resolution — authorize_read/write handle campaign scope, build_authorized_scopes includes campaign, get_campaigns_for_project service helper
- #159: write_memory/update_memory accept campaign scope and domains parameter, project_id for enrollment verification
- #158: search_memory includes campaign memories for enrolled projects, post-retrieval domain boosting (15% per match, capped 30%)
- #161: Domain-aware retrieval boosting via RRF integration — domain overlap ranks as third signal in focused search, configurable domain_boost_weight (default 0.3)
- #160: CLI config init campaign enrollment prompt, campaigns field in .memoryhub.yaml, campaign block in generated rule file

### Releases
- `memoryhub` SDK v0.3.0 (tag `sdk/v0.3.0`) — campaigns field on MemoryLoadingConfig
- `memoryhub-cli` v0.2.0 (tag `memoryhub-cli/v0.2.0`) — campaign enrollment in config init
- MCP server deployed with all campaign/domain changes

### Docs + retro
- ARCHITECTURE.md, governance.md, mcp-server.md, SYSTEMS.md updated for campaign/domain
- Retro written: `retrospectives/2026-04-09_campaign-domain-framework/`

## Where things stand

### Repo + CI
- Main on `1a0419f`. All CI jobs green.
- No open PRs.
- 236 MCP server tests, 88 SDK tests (across 3 Python versions), 32 CLI tests.

### Cluster
- Sandbox `cluster-n7pd5.n7pd5.sandbox5167.opentlc.com` healthy.
- MCP server deployed with campaigns/domains (15 tools verified via mcp-test-mcp).
- Migrations 001-010 applied.

### Project board
- 84 items in Backlog
- No items In Progress

### PyPI
- `memoryhub` v0.3.0 live
- `memoryhub-cli` v0.2.0 live

## Plan: #162 + #47

### #162 — Wire campaign_ids into read-path tools

9 tools call authorize_read or authorize_write without campaign_ids, which means campaign-scoped memories always return 403 on direct ID lookup:

- read_memory
- get_memory_history
- get_similar_memories
- get_relationships
- create_relationship
- suggest_merge
- report_contradiction
- delete_memory
- update_memory (has project_id for write, but not for the initial authorize_read check)

**Pattern:** Add optional `project_id` parameter to each tool. When the memory being accessed has scope="campaign", require project_id and resolve campaign_ids via `get_campaigns_for_project` before the authz check. Same pattern already used in write_memory, update_memory (write path), and search_memory.

This is mechanical — same change in 9 places. Good candidate for parallel sub-agents with worktree isolation.

### #47 — get_similar_memories returns empty results

The post-fetch RBAC filter in get_similar_memories is broken — it always returns empty. This is in the same tools being touched for #162, so fix it in the same pass.

### After #162 + #47

If time permits, consider:
- #95: PostgreSQL integration test target (addresses recurring retro gap)
- #64: Project-scope membership enforcement (the "TBD" in authz.py)

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
Migrations live in `alembic/versions/`. Current head is migration 010 (`domains`). New migrations should be sequential (011, ...). Migrations run automatically on MCP server startup.

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
Per project memory: do MCP tool work in the main conversation context, not delegated to sub-agents. The fips-agents scaffold workflow is for NEW tools; edits to existing tools are done directly.

## Background reading

- [`planning/campaign-domain-framework.md`](planning/campaign-domain-framework.md) — the full design
- [`docs/governance.md`](docs/governance.md) — current scope model and RBAC (now includes campaign)
- [`docs/mcp-server.md`](docs/mcp-server.md) — tool surface with campaign/domain parameters
- `memory-hub-mcp/src/core/authz.py` — authorize_read/write with campaign_ids
- `memory-hub-mcp/src/tools/write_memory.py` — reference pattern for campaign_ids resolution
- `retrospectives/2026-04-09_campaign-domain-framework/RETRO.md` — session retro with gaps

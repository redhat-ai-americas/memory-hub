# Next Session: Tenant Isolation Enforcement (#46)

## Goal

Close the silent multi-tenant data isolation gap. Today, the auth service issues tenant-scoped JWTs and `core/authz.py` reads `tenant_id` from claims, but no query filters by it and no governed table has the column. Single-tenant deployments work fine; a multi-tenant deployment would leak data across tenants when scopes overlap.

By end of session: every governed table has a `tenant_id` column populated from claims on write and filtered on read. Cross-tenant isolation tests pass. Existing single-tenant deployments continue to work via a `"default"` backfill.

## Why this is the next priority

- **Security gap, not a feature gap.** The auth service requires `tenant_id` on every client creation, which gives operators the appearance of tenant isolation. It doesn't exist downstream. That's a documentation/reality mismatch worth closing before anyone deploys multi-tenant on the assumption it works.
- **Independent of kagenti.** The fix doesn't need token exchange, SPIFFE, or Keycloak. The JWTs already carry `tenant_id`. The work is "use what's already there."
- **Unblocks #45 (admin agent).** Content moderation across all owners requires tenant scoping or it'd cross tenant boundaries.
- **Compatible with the bigger auth unification later.** Doing tenant filtering now in `core/authz.py` puts it in the right place for an eventual unified auth module — not in `core/auth.py`'s `requires_scopes` decorator (which can't express tenant boundaries any more than it can express ownership).

## Design references

- `docs/governance.md` — the existing design covers this:
  - **Line 247**: "`tenant_id` — multi-tenant isolation key. Agents in tenant A cannot access tenant B's memories, even with valid tokens. The MCP server filters all queries by tenant."
  - **Lines 158-160**: prototyped `authorize_read` tenant check
  - **Line 484**: target SQL with `AND tenant_id = :tenant_id`
- `memoryhub-auth/src/models.py` — `tenant_id` already on `oauth_clients` and `refresh_tokens`
- `memoryhub-auth/src/tokens.py:25` — JWTs already include `tenant_id` as a claim
- `memory-hub-mcp/src/core/authz.py:76,94,107` — `tenant_id` extracted from claims, defaulted to `"default"`, then unused

## What's already deployed and working

- MCP server build 13 with 13 tools (including `delete_memory`), JWT verification active, `core/authz.py` reading but ignoring `tenant_id`
- Auth service issuing JWTs with `tenant_id` claim
- Dashboard build 32 with delete UI working
- Migration 007 applied to dev DB (deleted_at column)
- All current data is in tenant `"default"` (the fallback) — backfill target is therefore trivially safe

## Session scope

### 1. Alembic migration 008 — add `tenant_id` to four tables

Add `tenant_id String(255)` column to:
- `memory_nodes` — index `(tenant_id, scope)` (this is the most-queried table)
- `memory_relationships` — index `(tenant_id)`
- `contradiction_reports` — index `(tenant_id)`
- `curator_rules` — index `(tenant_id)`

Migration runs in three steps: add nullable column, backfill all existing rows to `"default"`, alter to NOT NULL.

### 2. Service layer — populate from claims on write

Update every write path to set `tenant_id = claims["tenant_id"]`:
- `memoryhub.services.memory.create_memory()` — accept claims, set on the new `MemoryNode`
- `memoryhub.services.memory.update_memory()` — propagate from old version (don't trust claims here; the old version's tenant is authoritative)
- `memoryhub.services.memory.delete_memory()` — no change needed (deletes by ID, but verify the tenant matches before deleting — this is part of authz)
- `memoryhub.services.graph.create_relationship()` — set on the new `MemoryRelationship`; **also enforce that source and target are in the same tenant** (cross-tenant edges are a hard error)
- `memoryhub.services.memory.report_contradiction()` — set on the new `ContradictionReport` from the target memory's tenant
- `memoryhub.services.curation.rules.set_curation_rule()` — set on the new `CuratorRule` from claims (system-layer rules created during seeding stay in `"default"`)

### 3. Authz layer — enforce tenant on every check

`core/authz.py`:
- Add `tenant_id` parameter to `authorize_read(claims, memory)` — first check is `memory.tenant_id == claims["tenant_id"]`, return False otherwise
- Add `tenant_id` to `authorize_write(claims, scope, owner_id, tenant_id=None)` — same check
- Add `tenant_id` to the dict returned by `build_authorized_scopes()` so SQL filters include it
- The `"default"` fallback in claims extraction stays — that's how single-tenant deployments work

### 4. Read paths — add `tenant_id` filter to every query

This is the biggest piece. Every query that touches a governed table needs the filter:

**`memoryhub.services.memory`**:
- `read_memory()` — add `MemoryNode.tenant_id == claims["tenant_id"]` to the WHERE
- `search_memories()` — add to the base filter list (where `deleted_at IS NULL` already lives)
- `get_memory_history()` — add to the chain walk
- `_bulk_branch_flags()` and `_compute_branch_flags()` — add to children query
- `delete_memory()` — verify tenant before walking the chain

**`memoryhub.services.graph`**:
- `get_relationships()` — filter both by edge tenant and by both endpoint tenants
- All graph traversals — add tenant filter

**`memoryhub.services.curation.similarity`**:
- `find_similar_memories()` — add tenant filter to the similarity SQL

**`memoryhub.services.curation.rules`**:
- `find_applicable_rules()` — match either the caller's tenant OR a system rule (system rules in `"default"` apply globally; tenant-specific rules apply only to their tenant). **Open question**: do we want tenant-specific rules to override system rules, or only add to them? Document the decision.

### 5. BFF — tenant-scope all queries

`memoryhub-ui/backend/src/routes.py` — every `select(MemoryNode)` and friends needs the `tenant_id` filter from the operator's identity. The BFF currently has no auth (it's behind oauth-proxy), so we need to:
- Decide where the BFF gets `tenant_id` from. Options: (a) the oauth-proxy passes it as a header, (b) the BFF reads the same JWT the user authenticated with, (c) the operator is always implicitly `"default"` tenant for now and we file a follow-up for real BFF auth.
- For this session: option (c) keeps scope tight. The dashboard runs as the `"default"` tenant operator. The fact that all current data is in `"default"` makes this safe. File a follow-up issue for real BFF tenant identity.

### 6. Tests

Add cross-tenant isolation tests:
- Write a memory as tenant A, attempt to read as tenant B → not found
- Write a memory as tenant A, attempt to search as tenant B → empty results
- Create a relationship between tenant A memories, attempt `get_relationships` as tenant B → empty
- Write a curation rule as tenant A, verify it does not apply to tenant B writes
- Report a contradiction as tenant A, verify tenant B's `contradiction_stats` doesn't see it
- Cross-tenant relationship creation attempt → hard error

### 7. Deploy and verify

- Run migration 008 on the dev DB
- Rebuild and deploy MCP server (remember: `oc set image` to pin the new digest; static-registration loader bug from last session is documented in `memory-hub-mcp/CLAUDE.md`)
- Rebuild and deploy dashboard
- Smoke test: existing memories still readable (backfill worked); writes still go through; deletion still works
- Add `mcp-test-mcp list_tools` count check to deploy script (action item from last session's retro)

## Out of scope this session

- **Token exchange / SPIFFE / kagenti integration** — that's #34 and #29. We're using the JWTs we already issue.
- **Cross-tenant sharing or federation** — explicitly excluded in #46
- **Tenant management UI in the dashboard** — not needed for enforcement
- **BFF authentication** — file as a follow-up; for now the BFF is implicitly `"default"` tenant
- **Auth module unification** (`core/auth.py` + `core/authz.py`) — bigger refactor, defer
- **Migrating the 13 tools to fips-agents `--with-auth` decorator** — discussed and deferred until the unification

## What comes after

- **#45** — Admin agent for content moderation (now unblocked)
- **BFF tenant auth** — follow-up issue from this session
- **#34** — OAuth 2.1 token exchange (still needed for kagenti, but no longer blocked on tenant filtering)
- **#43** — Backend route tests (recurring; if there's time at the end of next session, knock these out for the new tenant code)
- **#36** — Frontend component tests (recurring 3rd time; needs a decision: commit or close)
- **Auth module unification** — eventual, once kagenti integration becomes real

## Process notes from last session's retro

Following these discipline rules per the retro:

1. **Use the fips-agents workflow.** Tenant-scoping touches existing tools rather than adding new ones, so this session is mostly service-layer + tests, not new tool scaffolding. If a new tool IS needed, scaffold it via fips-agents.
2. **Diff design vs implementation at the end.** When the migration + service changes are done, re-read `governance.md` lines 140-200 and 460-495 and verify every documented requirement is met. File a follow-up issue for any slice that didn't make it.
3. **Add the deploy-time tool-count check.** The static-registration silent failure cost ~20 minutes last session; one line in `deploy.sh` would catch the next instance.
4. **`/exercise-tools` is not optional** for any new tool. Last session it caught two real bugs that nothing else would have caught.

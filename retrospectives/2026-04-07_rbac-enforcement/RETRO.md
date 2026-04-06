# Retrospective: RBAC Enforcement

**Date:** 2026-04-07
**Effort:** Enforce authorization on every MCP tool so the deployed server rejects unauthorized access
**Issues:** #7
**Commits:** e2425be, b8f69b7, 3add6e3, 0c8308a, 22491f0

## What We Set Out To Do

From NEXT_SESSION.md (6 steps):
1. Create `core/authz.py` with `authorize_read`, `authorize_write`, `get_claims_from_context`
2. Wire authorization into all 12 MCP tools
3. Activate JWTVerifier in OpenShift deployment
4. Bridge `register_session` with JWT identity
5. Write unit tests + integration tests against live server
6. Update `register_session` as compatibility shim

Goal: unauthenticated requests rejected, JWT claims drive access decisions, SDK verified end-to-end.

## What Changed

| Change | Type | Rationale |
|--------|------|-----------|
| Added `build_authorized_scopes()` for SQL-level search filtering | Good pivot | Post-fetch filtering for search is wasteful and a data leak risk. SQL-level filtering is cleaner and was not in the original plan but emerged naturally from the design. |
| Session scope normalization (access-tier → operational) | Good pivot | Session users have `["user", "project"]` but authz functions need `["memory:read:user", "memory:write:user"]`. Normalization layer keeps authorize functions uniform. |
| `get_access_token()` returns None — JWT header extraction needed | Discovery | FastMCP JWTVerifier validates tokens at transport but doesn't populate `get_access_token()` for tool-level access. Added `_extract_jwt_from_headers()` fallback that decodes JWT from the Authorization header directly. This was the most important finding of the session. |
| SDK integration tests built, not deferred | Changed plan | Originally deferred, but we built the full 8-test harness and used it to discover and verify the JWT extraction fix. The tests drove the fix. |
| OpenShift build caching caused repeated stale deployments | Discovery | BuildConfig lacked `noCache: true`, and Deployment lacked ImageChange trigger. Builds succeeded but pods ran old images. Required `oc rollout restart` after every build. |
| `set_curation_rule` admin check is structural only | Scope deferral | Plan called for `memory:admin` scope enforcement. Implemented the claims extraction but actual admin-only gating deferred since user-layer rules are already self-scoped. |

## What Went Well

- **Plan-first approach eliminated rework.** Full plan mode → approved plan → parallel sub-agents for implementation. Zero architectural backtracking.
- **Autouse fixture preserved all existing tests.** Adding a default session fixture in conftest.py was the key insight — existing tests didn't need individual modification to continue passing with the new auth enforcement.
- **Parallel sub-agent execution was effective.** Three groups of tools modified simultaneously (read/write/update, search/register/deps, remaining 5). Test fix sub-agent cleaned up all 25 failures in one pass.
- **Integration tests caught a real bug.** The cross-user isolation test revealed that `get_access_token()` returns None, which led to discovering the JWT header extraction gap. Without the test harness, this would have shipped broken.
- **Iterative fix-deploy-test cycle worked.** Discovered the issue, added `_extract_jwt_from_headers()`, deployed, re-ran integration tests — all 8 passed including cross-user isolation.

## Gaps Identified

| Gap | Severity | Resolution |
|-----|----------|------------|
| OpenShift BuildConfig needs `noCache: true` and Deployment needs ImageChange trigger | Fixed partially | Set `noCache: true` on BuildConfig. Still need to add ImageChange trigger or document `oc rollout restart` as a post-build step. |
| `mcp-server` vs `memory-hub-mcp` dual deployment in namespace | Follow-up | Two deployments exist. `mcp-server` is primary (from openshift.yaml). `memory-hub-mcp` was from an earlier deploy script. Need to remove the stale one. |
| Tenant isolation is structural only (no tenant_id on memory model) | Accept | `authorize_read` has a TODO comment for tenant checks. Requires a DB migration. |
| Test data accumulates in production DB | Accept | Integration tests write `[test]`-prefixed memories to the live deployment. No cleanup mechanism. Low priority since it's a dev cluster. |
| `write_memory` returns error dicts instead of raising ToolError | Follow-up | SDK's `_call` expects `result.is_error` for MCP errors, but some tools return `{"error": True}` as normal responses. This causes `ValidationError` instead of `ToolError` in the SDK. Works but the error type is wrong. |

## Action Items

- [x] Write SDK integration tests — 8 tests, all passing
- [x] Fix JWT identity extraction — `_extract_jwt_from_headers()` fallback
- [ ] Add ImageChange trigger to mcp-server Deployment (or document rollout restart)
- [ ] Clean up stale `memory-hub-mcp` deployment in namespace
- [ ] Standardize tool error responses (ToolError vs error dicts) for cleaner SDK integration

## Patterns

**Continue:**
- Plan mode → approved plan → parallel sub-agents. Fourth session using this pattern, consistently avoids rework.
- Autouse fixtures for backward-compatible test changes.
- Integration tests as the verification layer — they caught the real JWT bug that unit tests couldn't.

**Start:**
- Always verify deployed code after build: `oc exec ... -- wc -l` or `grep` on the critical file before running tests.
- Set `noCache: true` on BuildConfigs and `oc rollout restart` after builds until ImageChange triggers are configured.
- Chain deployment commands in a single bash call with verification gates.

**Stop:**
- Trusting that OpenShift picks up new images automatically. The Deployment doesn't have an ImageChange trigger — always restart explicitly.
- Writing the retro before the session is actually done. The most important findings (JWT gap, deployment caching) came after the first retro was written.

# Retrospective: OAuth 2.1 Auth Service

**Date:** 2026-04-05
**Effort:** Build and deploy OAuth 2.1 authorization service — foundation for JWT-based auth
**Issues:** Prerequisite for #7 (RBAC enforcement)
**Commits:** 98adae0..d52a7ea (3 commits, 33 files, ~1980 lines)

## What We Set Out To Do

From NEXT_SESSION.md:
1. Decide: same repo or separate repo for the auth service
2. Build the auth service — `client_credentials` grant only
3. Deploy to OpenShift and verify (POST /token returns JWT, JWKS works)
4. Smoke test: MCP server validates JWT from auth service

## What Changed

| Change | Type | Rationale |
|--------|------|-----------|
| Added `refresh_token` grant with DB-backed token rotation | Good pivot | User requested DB-backed refresh tokens. Small incremental cost, big value — revocable and auditable, which governance.md requires. |
| Seed script refactored to read from JSON file instead of hardcoded secrets | Good pivot | ggshield pre-commit hook caught hardcoded dev API keys. Moved to external JSON file (gitignored) with example template. |
| FastMCP JWTVerifier doesn't reject unauthenticated requests | Discovery | JWTVerifier validates tokens when present but is not a gatekeeper. Full enforcement needs RemoteAuthProvider or service-layer checks. Important finding for #7. |
| deploy.sh needed runtime fixes (secret names, DB password key mapping) | Expected | Cross-namespace secret references differ from what openshift.yaml templated. Normal deploy-time discovery. |

## What Went Well

- **Plan-then-build worked.** Presented architecture plan, got approval, then built. Zero rework on the core design. The review sub-agent caught 4 real bugs (server_default, session management, RFC error format, missing client auth on refresh) before any manual testing.
- **Test suite was solid from the start.** 51 tests covering happy paths, error cases, token rotation, and RFC compliance. All passed on first run after fixes.
- **Deployment was smooth.** Auth service deployed and returned valid JWTs on first try. Migration, seed, build, deploy — each step worked.
- **Clean commit history.** Three logical commits: prep (migration), feature (auth service), wiring (MCP integration). Each independently reviewable.
- **Monorepo decision was quick and correct.** Same-repo was the obvious choice during rapid development. No time wasted on the debate.

## Gaps Identified

| Gap | Severity | Resolution |
|-----|----------|------------|
| FastMCP JWTVerifier doesn't enforce auth — unauthenticated tool calls still succeed | Accept | By design for this session. Full enforcement is #7 scope (RemoteAuthProvider or service-layer authorize_read/authorize_write). |
| mcp-test-mcp can't send Bearer tokens | Accept | Testing tool limitation. Raw curl with correct MCP headers is cumbersome. Not blocking. |
| openshift.yaml has placeholder empty RSA keys and cross-namespace secret copying in deploy.sh | Accept | deploy.sh handles key generation. Could be cleaner with a Kustomize overlay, but works. |
| No CI for memoryhub-auth yet | Follow-up | Root test.yml only runs core + MCP tests. Auth service tests need to be added. |
| NEXT_SESSION.md not updated for next session | Follow-up | Should document what comes next (SDK client, RBAC enforcement, additional grant types). |

## Action Items

- [ ] Add memoryhub-auth tests to CI pipeline (test.yml)
- [ ] Update NEXT_SESSION.md for next session scope
- [ ] Investigate FastMCP RemoteAuthProvider for full auth enforcement (#7)

## Patterns

Scanning 6 prior retros:

**Start:**
- **Testing deploy artifacts before committing.** The deploy.sh needed runtime fixes (secret name mismatches). A dry-run step against the cluster before commit would catch these earlier.

**Stop:**
- Nothing new to stop. Previous "stop" items (scope creep, skipping doc consistency) were well-managed this session — we stayed focused on auth only.

**Continue:**
- **Review-after-write pattern.** Sub-agent review caught 4 bugs (server_default, session management, RFC errors, missing client auth). This pattern has caught real issues in every session it's been used.
- **Plan before code.** Architecture discussion → approval → implementation. Zero wasted work.
- **Pre-commit security checks.** ggshield caught the hardcoded dev keys, which led to a better design (external JSON file).

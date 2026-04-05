# Retrospective: RBAC & Governance Design

**Date:** 2026-04-05
**Goal:** Merge #7/#13 into a unified RBAC design, verify Authorino, design auth architecture
**Issues:** #7 (governance design), #13 (closed as duplicate), #22 (Authorino verification)

## What was planned

1. Merge overlapping governance issues #7 and #13
2. Design RBAC enforcement mechanism in docs/governance.md
3. Verify Authorino AuthConfig API version on cluster
4. Close out with commits and retro

## What actually happened

All planned items completed, plus a significant architectural pivot:

- **#13 closed as duplicate of #7** after merging unique acceptance criteria (OpenShift OAuth/OIDC, agent identity model, `get_similar_memories` visibility gap)
- **Governance doc expanded** with implementation design: enforcement architecture (gap analysis + target state), agent identity model, audit trail schema, visibility rules
- **Authorino verified**: cluster has v1beta2 (not v1beta3 as assumed). Fixed landing-page-design.md
- **Auth architecture pivoted** from Authorino-as-primary to OAuth 2.1 AS as a separate service, with Authorino as defense-in-depth. This was driven by the user's insight that MemoryHub needs to serve diverse clients (Claude Code, LlamaStack, Cursor, Pi, Codex, etc.) — infrastructure-level auth alone can't cover them all
- **FastMCP auth framework researched**: JWTVerifier, TokenVerifier, OAuthProvider, per-tool auth checks. The MCP server becomes a resource server validating JWTs
- **memoryhub-integration.md rules fixed**: removed stale env var guidance for API key

## Key decisions made

1. **OAuth 2.1 AS is a separate service**, not embedded in the MCP server
2. **Three grant types**: client_credentials (agents/SDKs), authorization_code+PKCE (browser), token exchange/RFC 8693 (platform agents on K8s)
3. **Operational scopes** as a two-dimensional model: `memory:read:user`, `memory:write:organizational`, etc.
4. **TenantID in JWT** for multi-tenant isolation
5. **Python SDK** to be published as `memoryhub` on PyPI (name available, register soon)
6. **`register_session` becomes a compatibility shim**, not the primary auth path
7. **Expandable trust configuration** starting with local cluster tokens

## What went well

- Review-after-write pattern caught 10 issues in the initial governance design (stale scope model, inconsistent scope checks, duplicate DDL, missing forensic fields)
- Authorino cluster verification was quick and caught the v1beta3 assumption early
- The auth discussion naturally evolved from "verify Authorino" to a much better architecture. The user's question about supporting diverse agent ecosystems was the pivotal moment.

## What could improve

- The governance.md went through three rounds of edits (write → review → fix → update for new scope model). Starting with the full scope model would have saved a round. Lesson: when there's an open design question (scope model), resolve it before writing dependent code/design.
- The `authorize_read`/`authorize_write` pseudocode was written twice — once with old scopes, once with new. Design decisions should be front-loaded.

## Artifacts

- `docs/governance.md` — expanded with ~380 lines of implementation design
- `docs/RHOAI-DEMO/landing-page-design.md` — AuthConfig fixed to v1beta2
- `.claude/rules/memoryhub-integration.md` — API key hardcoded
- `.gitignore` — security patterns added

## Open items for next session

- Register `memoryhub` on PyPI (placeholder package)
- Design the OAuth 2.1 auth service (separate repo? same repo?)
- Begin `memoryhub` Python SDK design
- Implementation planning: which pieces to build first?
- Issue #7 remains open — acceptance criteria partially met (design done, implementation not started)

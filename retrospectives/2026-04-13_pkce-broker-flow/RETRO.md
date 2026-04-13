# Retrospective: PKCE Broker Flow

**Date:** 2026-04-13
**Effort:** OAuth 2.1 authorization_code + PKCE grant via OpenShift OAuth broker
**Issues:** #74 (tracker), #75, #76, #77, #78, #79, #80; IaC follow-up unplanned
**Commits:** 49ee8a6..daf1f25 (13 commits, +1864/-25 lines, 29 files)

## What We Set Out To Do

Implement the OpenShift authentication broker so browser-based MCP clients (LibreChat, MCP Inspector) can authenticate via PKCE + OpenShift login. Six implementation issues (#75–#80) plus an e2e Playwright test (#81). Design doc fully specified at 396 lines.

## What Changed

| Change | Type | Rationale |
|--------|------|-----------|
| #81 Playwright e2e deferred | Scope deferral | Requires headless browser driving real OpenShift login; better as a separate PR after the broker code is deployed and stable |
| IaC remediation (Alembic, deploy.sh, admin API, CLAUDE.md) | Missed requirement | `create_all()` can't add columns to existing tables, secrets weren't scripted, admin API didn't expose new fields. Discovered during deployment, not planning. |
| Security hardening commit | Good pivot | Review sub-agent caught verify=False TLS, TOCTOU race on code redemption, missing RFC 7636 length check. Fixed immediately. |
| httpx missing from requirements.txt | Missed | pyproject.toml had the dep but Containerfile installs from requirements.txt. Container crashed at startup. |

## What Went Well

- **Design doc drove implementation** — openshift-broker.md was thorough enough that all six issues were implement-what-it-says work with minimal ambiguity
- **Phase 1 parallelization** — three worktree agents for #75/#79/#80, cherry-picked with zero conflicts, saved ~10 minutes of sequential work
- **Review sub-agent** caught two real security issues (TLS verification disabled, TOCTOU race on code replay) that would have shipped to production
- **Test coverage** — 69 → 112 tests; every negative case from the design doc's test surface section is covered
- **IaC recovery was fast** — the gap discovery to full remediation (Alembic + deploy.sh + admin API + CLAUDE.md) took one phase of work, not a separate session

## Gaps Identified

| Gap | Severity | Resolution |
|-----|----------|------------|
| `create_all()` can't alter existing tables — not caught in planning | Fixed | Alembic migration 001 (df2f013); CLAUDE.md convention added |
| requirements.txt / pyproject.toml drift | Fixed | httpx added (8521421); checklist in CLAUDE.md |
| `openshift_allowed_group` config declared but unenforced | Follow-up | #179 filed |
| #81 e2e Playwright test not done | Follow-up | Next session |
| No memoryhub-auth CLAUDE.md existed | Fixed | Created (13d529f) |

## Action Items

- [x] Alembic setup + initial migration — df2f013
- [x] deploy.sh handles all secrets, OAuthClient CR, migrations — daf1f25
- [x] Admin API exposes redirect_uris and public — 950e300
- [x] CLAUDE.md IaC conventions — 13d529f
- [x] File issue for openshift_allowed_group — #179
- [ ] #81 Playwright e2e test — next session
- [ ] Merge feat/pkce-broker-flow to main

## Patterns

**Start:** Check that deploy.sh can recreate the full environment from scratch before calling a feature "deployed." The IaC gap would have been caught by a mental dry-run of "what if this cluster disappeared?"

**Stop:** Nothing specific to stop — the session workflow was effective.

**Continue:** Design-doc-first for complex features. Review sub-agent after implementation. Parallel worktree agents for independent Phase 1 work.

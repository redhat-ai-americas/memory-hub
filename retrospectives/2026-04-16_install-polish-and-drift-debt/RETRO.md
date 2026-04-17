# Retrospective: Install Polish & Drift Debt Discovery

**Date:** 2026-04-16
**Effort:** One-command install for evaluators, UI namespace migration, deploy-full.sh infrastructure wiring
**Commits:** 12311e8, d67ec5e

## What We Set Out To Do

Make `make install` a true one-command cluster install for evaluators: prereq checks, full-stack deploy (DB + migrations + MCP + auth + UI + RHOAI tile), `make uninstall` counterpart, and fix the UI namespace drift from `memory-hub-mcp` to `memoryhub-ui`.

## What Changed

| Change | Type | Rationale |
|--------|------|-----------|
| Ran the migration live on the workshop cluster as the smoke test | Good pivot | User said "can we just do that now and see if it works" — revealed real problems that a dry-run wouldn't have found |
| Discovered 5 categories of missing infrastructure in deploy-full.sh | Missed (systemic) | MinIO/Valkey deployment, SCC grants, cross-namespace Secrets, auth admin key, UI proxy/admin Secrets — all manually created on the original cluster, never captured in IaC |
| Added CLAUDE.md golden test rule (`make uninstall --skip-db && make install`) | Good pivot | Emerged directly from the migration failure; codifies the enforcement mechanism |

## What Went Well

- **Uninstall script worked first try.** Clean deletion of all namespaces, RHOAI tile, ConfigMap entry, legacy UI drift. 4 seconds to completion. The backup-before-modify pattern from the Red Hat managed investigation was reused here.
- **Pod failure diagnosis was systematic.** Each `CreateContainerConfigError` was diagnosed via `oc describe pod` → read the specific error → create the missing resource → restart → next error. Five iterations, each taking 2-3 minutes.
- **Every manual fix was immediately captured in deploy-full.sh.** The `d67ec5e` commit wires in all five categories with idempotent helpers (`copy_secret`, `ensure_random_secret`). Future installs won't hit these.
- **UI namespace migration succeeded.** UI now runs in `memoryhub-ui` (correct), not `memory-hub-mcp` (drift). The openshift.yaml is namespace-agnostic; the deploy script uses an env-var-overridable default.
- **The drift debt discovery was high-value.** Five categories of undocumented infrastructure, accumulated over 13 days of development, would have bitten any new contributor or cluster migration. Finding it now — before the Red Hat managed presentation — is much better than finding it during a live demo.

## Gaps Identified

| Gap | Severity | Resolution |
|-----|----------|------------|
| Golden test not run clean end-to-end with the fixed deploy-full.sh | Medium | Next session: `make uninstall --skip-db && make install` from scratch |
| Terminal-worker sub-agent timed out silently (~20 min blank screen) on first migration attempt | Low | Recovered by running commands directly. Root cause unclear — possibly the auth build's long output exceeded the agent's buffer. Lesson: use direct Bash for multi-minute cluster operations rather than terminal-worker agents |
| `run-migrations.sh` still requires the auto-read path added to deploy-full.sh — if run standalone, it still demands `MEMORYHUB_DB_PASSWORD` env var | Low | Accept — standalone use is for developers who know the setup. deploy-full.sh handles the common case. |
| Pre-existing lint errors (71 ruff) still unfixed | Low | Pre-existing across multiple sessions. Not blocking but increasingly visible. |

## Action Items

- [ ] Run the golden test (`make uninstall --skip-db && make install`) on a clean namespace set next session to verify deploy-full.sh is fully self-contained
- [ ] File an issue for the pre-existing ruff lint cleanup (71 errors across root + MCP)

## Patterns

**Start:**
- Run the golden test after any infrastructure change. The CLAUDE.md checklist now requires it but this was the first session where it was needed — make it habitual.
- Use direct Bash for multi-minute cluster operations (builds, rollouts). Terminal-worker agents add latency and can time out silently.

**Stop:**
- Creating infrastructure manually without immediately adding it to deploy-full.sh. The five categories of drift debt all started as "quick `oc create` to unblock the next step" and were never formalized. The `copy_secret` / `ensure_random_secret` helpers make formalization easy now — use them at the moment of creation, not retroactively.

**Continue:**
- Backup-before-modify for cluster state changes (used in both the Red Hat managed experiment and the migration)
- Idempotent infrastructure helpers (skip-if-exists pattern) — makes re-runs safe
- Committing infrastructure fixes in the same session they're discovered rather than deferring

# Session Summary -- 2026-07-21 -- deploy -- Install hardening across fresh clusters

**Plan:** Ad-hoc install validation + hardening   **Commits:** b6ea5b3..909c1eb (fix/make-args-passthrough)
**Deployed:** 5 fresh test clusters (install-test-1 through 5)   **Model:** Opus 4.6

## Plan vs. actual
Planned: Test `make install` on fresh clusters, fix docs from prior session. Shipped: 7 deploy-blocking bugs fixed, README updated, workshop-setup scripts hardened, seed script added, multi-cluster credential issue filed. Scope expanded from "test and document" to "test, fix everything that breaks, and iterate until a fresh clone installs cleanly."

## Shipped
- `b6ea5b3` fix: Make install/uninstall forward flags via `ARGS=` (the `--` syntax silently dropped flags)
- `628e3a8` deploy: Replace hardcoded user IDs (wjackson, rdwj-agent-*) with OS username substitution
- `9dd7408` fix: Export CURRENT_USER + add mh-dev- prefix to generated API keys
- `dce8124` fix: Add bcrypt to root pyproject.toml (seed-oauth-clients.py needs it)
- `3fdaea3` fix: Auto-generate seed-clients.json from users ConfigMap before auth seeding
- `9a5ad9f` fix: Generate users-configmap.yaml before auth step (ordering dependency)
- `48e4682` fix: Use sqlalchemy[asyncio] extra (greenlet needed for async engine)
- `fd952a4` fix: Create memoryhub-auth .venv before deploy (alembic not found)
- `909c1eb` fix: Always overwrite API key file during install (stale key from other cluster)
- workshop-setup: 3 commits (duplicate OperatorGroup, --context flag, phased operands)
- Earlier session (merged as #449): README post-install guide, seed-sample-data.py, claude mcp add fix

## Verification & confidence
- Cluster 2: manual intervention needed (OperatorGroup bug); full MCP roundtrip after
- Cluster 3: clean workshop setup, clean install, MCP roundtrip verified
- Cluster 4: install completed, MCP roundtrip verified (internet drops interrupted agents)
- Cluster 5: user-driven manual install from the branch; hit and fixed bcrypt/greenlet/auth-venv/seed-clients/ordering bugs live
- Confidence: high for the fixes landed; medium for "no more bugs" since cluster 5 install finished with a stale-key smoke test failure (fixed by 909c1eb but not re-verified end-to-end after that commit)

## Judgment calls & deviations
- Used always-overwrite for API key file instead of building multi-cluster config -- simpler, unblocks now, filed #451 for the real solution
- Python SDK for seed script instead of raw curl -- cleaner, SDK is already a documented dep
- Removed Gemini API keys from production cluster (mcp-rhoai) at user's request

## Backlog delta
Filed #451 (multi-cluster API key management -- needs design doc, kept in Backlog)

## Drift & forward-collisions
- Backward: none
- Forward: #451 partially addressed by the always-overwrite fix; the issue tracks the full ssh_config-style solution

## For the reviewer
- Sanity-check: the ordering of deploy steps (users-configmap generation now happens in deploy_auth, duplicating logic from memory-hub-mcp/deploy/deploy.sh) -- is this the right long-term home?
- Thin verification: cluster 5 install was user-driven and hit real bugs; the final state (post-909c1eb) was not re-run end-to-end on a completely fresh cluster
- Wants guidance: none

## Risks / watch-fors
- deploy-full.sh now generates users-configmap.yaml in two places (deploy_auth and deploy_mcp) -- first-writer wins, but the duplication is a maintenance risk
- The port 15432 conflict between root migrations and auth migrations is a timing issue that showed up on cluster 5 -- non-blocking but worth cleaning up (use different ports or ensure cleanup between steps)
- Local pytest suite hangs (observed on two sessions now) -- may indicate a venv or import issue worth investigating

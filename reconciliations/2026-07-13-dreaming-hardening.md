# Reconciliation -- 2026-07-13 - dreaming (hardening)

**Range:** session 2026-07-13 (1 session: EvalHub hardening + cluster capacity)
**Plan:** NEXT_SESSION-dreaming.md items 0-6

## Backlog reconciled

| # | Was | Action | Why |
|---|-----|--------|-----|
| #364 | Sidecar doesn't forward results | Closed | Fixed: `from_adapter()` + duplicate COMPLETED removal. PR #363 |
| #365 | SQLite in-memory loses state | Re-scope proposed | File-backed `/tmp` workaround. PVC not possible (operator). Acceptable for #360 |
| #366 | Switch smoke to Gemini Flash Lite | Closed | Fixed: gemini-3.1-flash-lite + Secret. PR #363 |
| #367 | Add BuildConfig to deploy script | Closed | Fixed: manifests + idempotent creation. PR #363 |
| #360 | Ablation matrix on EvalHub | Blockers cleared | #364/#366/#367 done, #365 worked around. Now unblocked |
| #342 | Reranker upgrade | Kept | GPU nodes have capacity. No new L40S needed yet |

## Forward-collisions banked

- #360 blockers all resolved. Session built the exact plumbing #360 needs. Comment proposed on #360 noting unblock.

## Critique

On track. Four follow-up issues from #359 all resolved in one session. The EvalHub pipeline is end-to-end functional. Recurring friction: provider ID instability (UUID changes on pod restart) will affect matrix configs.

## Guidance for next

Run #360 (ablation matrix) -- it's the payoff for the last four sessions of toggle/EvalHub work. Secondary: #342 (reranker) is independently unblocked by existing GPU capacity.

# Session Summary: 2026-07-14 -- Matrix A Execution

## What landed

### #365: EvalHub PVC persistence (PR #384)
Switched EvalHub from in-memory SQLite to PostgreSQL (shared memoryhub-pg
instance, dedicated `evalhub` database). Provider registrations now survive
pod restarts. The PVC approach from the session plan didn't apply -- the
EvalHub CRD's `pvcManaged`/`pvcName` fields are on the lmevaljob CR (job
outputs), not the evalhubs CR (server database). PostgreSQL was the
correct path, verified by pod deletion + restart test.

### #342: Reranker upgrade (PR #385)
Deployed bge-reranker-v2-m3 on L40S GPU via TEI 1.6, replacing
ms-marco-MiniLM-L12-v2 (CPU, 512-token max). New model handles 8192
tokens at float16. Added `deploy/reranker/` kustomize manifests and
`MEMORYHUB_RERANKER_URL` to the MCP server deployment. Golden test
(preserve-DB) passed after fixing a pre-existing deploy-full.sh ordering
bug (auth infra must run before MCP deployment, not after).

### #360: Matrix A (PR #386)
Ran the full 4-config diagnostic ablation on 589 PersonaMem queries:

| Configuration | Correct | Accuracy |
|---|---|---|
| vector-only | 274 | 46.5% |
| vector + keyword | 274 | 46.5% |
| vector + reranker | 274 | 46.5% |
| vector + keyword + reranker | 274 | 46.5% |

All four produced exactly 274/589. H2 (pool exhaustion) conclusively
confirmed. Keyword and reranker cannot differentiate at 195 docs.

## Key findings

1. **46.5% falsifies the ~70% prediction.** The clean-corpus vector-only
   baseline is 24pp below the 70.8% #332 baseline. The #369 attribution
   (that the clean corpus would restore 70%) is wrong.

2. **H6 (lossy content delivery) is now mandatory.** The 21pp gap between
   BM25-local (67.7%) and MCP-vector (46.5%) cannot be ranking when
   the candidate set is identical. Something in the MCP path is delivering
   less content to the answerer.

3. **Signal work is moot at 195 docs.** All signal combinations produce
   identical results. Differentiation requires #343 (chunking to grow
   per-user pool) or fixing the content delivery path.

## Issues encountered

- `disabled_signals` not published in PyPI SDK (only in local dev) --
  required `uv add --editable ../../sdk` in the harness
- No `amb-benchmark` tenant user in the MCP users.json -- first run
  returned empty context (0% accuracy). Added amb-benchmark user to
  the configmap.
- deploy-full.sh ordering: MCP pod raced with auth secret creation.
  Fixed by moving `prepare_auth_infra` before `deploy_mcp`.

## PRs created

- #384: EvalHub PostgreSQL persistence (#365)
- #385: Reranker upgrade to bge-reranker-v2-m3 (#342)
- #386: Matrix A results (#360)

## What's next

1. H6 context-delivery audit (highest priority)
2. Reproduce #332 baseline to understand the 70.8% discrepancy
3. #343 chunking fix (independent, grows per-user pool for signal
   differentiation)

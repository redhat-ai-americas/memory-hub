# Reconciliation -- 2026-07-28 -- personal-edition

**Range:** summaries 2026-07-27..2026-07-28 (7 sessions)   **Plan:** NEXT_SESSION-local.md / planning/personal-edition.md

## Backlog reconciled

| # | Was | Action | Why |
|---|-----|--------|-----|
| #308 | Local/offline embedding fallback (all-MiniLM, sentence-transformers) | Re-scope | Personal edition built EmbeddingService ABC + OnnxEmbeddingService (Granite, ONNX). Remaining: wire as cluster fallback. Commented. |
| #375 | Full local test suite hangs | Keep | Integration tests still need local PostgreSQL; hang is unrelated to personal-edition work. |
| #458 | CLI create-agent omits api_key | Keep | Cluster-edition bug, unrelated. |
| #459 | CLI rotate-api-key subcommand | Keep | Cluster-edition auth, unrelated. |
| #460 | README quickstart | Closed | Shipped in 260c6ec, closed in P5S1. |
| #461 | Parity matrix | Closed | Shipped in 260c6ec, closed in P5S1. |
| #462 | Clean-venv verification | Closed | Verified in dc40694, closed in P5S1. |

## Forward-collisions banked

- #308 -- embedding abstraction already built at `memoryhub-local/embeddings/` -- comment landed
- #310 -- stdio MCP server is framework-agnostic, partially advances non-Claude-Code onboarding -- comment landed

## Deferred items resolved

- Stale all-MiniLM model comment (arch session) -- cleaned up during P1 implementation, verified no references remain
- Version bump 0.2.0 (P4S1) -- deferred to PyPI publish
- Extraction prompt sync (P4S1) -- valid watch-for, not yet an issue

## Critique

On track: epic shipped completely, all 5 phases done, 45 commits squash-merged to main via #463. No scope creep, no recurring friction. Single gap: two-command install requires PyPI publishing.

## Guidance for next

PyPI publishing is the highest-leverage next step. After that, #308 re-scope (cluster embedding fallback) would let the cluster edition benefit from the abstraction built here.

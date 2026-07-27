# Session Summary -- 2026-07-27 - personal-edition - Architecture grounding

**Plan:** New epic, no prior NEXT_SESSION   **Commits:** 4130f45 (`feat/personal-edition`)
**Deployed:** none   **Model:** Opus 4.6

## Plan vs. actual
Planned: discuss backlog for K8s-general and local install, then start architecture work. Shipped: grounded architecture document for personal edition with competitive research, codebase audit, and package layout decisions. Slipped: none.
Scope: stayed in scope -- architecture only, no implementation.

## Shipped
- `4130f45` -- Grounded personal-edition architecture doc with RecallBackend protocol (3 methods covering 10 PG-specific call sites), package architecture (new `memoryhub-local` package), SQLite implementation mapping, local MCP server design, parity testing strategy, and competitive positioning table

## Verification & confidence
- Document reviewed by sub-agent: 5 citation spot-checks all passed (memory.py:1118, similarity.py:135, memory.py:110, conftest.py FREEZE NOTICE, sdk pyproject.toml v0.14.0). Two consistency issues found and fixed.
- Confidence: high -- architecture is grounded in actual codebase analysis, not aspirational

## Judgment calls & deviations
- Decided `memoryhub-local` as new published package instead of publishing `memoryhub-core` to PyPI. Reason: memoryhub-core's full surface (models, services, admin, multi-tenant auth) is not designed as a public API; narrow public surface is better.
- Decided `memoryhub config init` is NOT required for basic local install. MCP server's FastMCP instructions handle agent onboarding. `config init` becomes power-user customization.
- K8s-general epic is independent of personal-edition -- work proceeds separately.

## Backlog delta
Filed: none. Closed: none. Memory: none new.
Deferred: stale model comment in `models/memory.py:109` (references all-MiniLM-L6-v2 instead of Granite) -- fix during P1.

## Drift & forward-collisions
- Backward: none
- Forward: none

## For the reviewer
- Sanity-check: the `memoryhub-local` package boundary -- extracting portable service code into a separate namespace means maintaining two copies of service logic. The alternative (publishing memoryhub-core) was rejected for API stability reasons, but the maintenance cost is real.
- Thin verification: the RecallBackend protocol is designed from call-site analysis but not yet implemented. P1 will validate whether 3 methods (vector_recall, keyword_recall, similarity_check) + graph_neighbors is sufficient or needs expansion.
- Wants guidance: none

## Risks / watch-fors
- Code duplication between memoryhub-core and memoryhub-local service layers. P1 should establish the extraction pattern early and determine whether shared code can be symlinked/vendored or must be truly copied.
- The 1 skipped test (`test_extraction_runner`) has been skipped across recent sessions -- not a regression from this session but worth investigating.

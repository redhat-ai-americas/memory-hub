# Session Summary — 2026-09-10 · retrieval docs · Retrieval pipeline overview, markdown backend design, research paper plan

**Plan:** ad-hoc (conversational session, no pre-planned epic)   **Commits:** none yet (prepare-and-ask)
**Deployed:** none   **Model:** Claude Opus 4.6 (1M context)

## Plan vs. actual
Planned: no pre-set plan; Wes asked about retrieval strategy and the session evolved from there. Shipped: three docs across docs/, planning/, and research/. Scope: stayed tight — docs and design exploration only, no code changes.

## Shipped
- `docs/design/retrieval-pipeline.md` — new overview of the five-signal hybrid retrieval pipeline (vector, keyword, cross-encoder, focus, metadata via RRF)
- Updated `docs/README.md` and root `README.md` to link the new retrieval overview doc
- `planning/markdown-storage-backend.md` — design exploration for a markdown+YAML-frontmatter storage backend for the personal edition, with scale hypothesis (three walls at ~5K, ~10K, ~10-50K memories)
- `research/flat-file-storage-paper/README.md` — research paper plan: "Characterizing the Performance Envelope of Flat-File Storage for Agent Memory Systems" covering experimental design for retrieval equivalence, rebuild cost model, write amplification, git tax, and format comparison
- `.gitignore` — added `local/` directory to gitignore (scratch files)

## Verification & confidence
- Retrieval pipeline doc cross-checked against the explored codebase (services/memory.py, storage/sqlite.py, recall.py protocol, embeddings, reranker). All signal names, default weights, model identities, and RRF constant verified against code.
- Markdown backend design grounded in the actual RecallBackend protocol and MemoryNode schema from the personal edition codebase.
- Scale estimates in the markdown backend doc are hypothesized from general benchmarks, not measured. This is explicitly called out and is the motivation for the research paper plan.
- Confidence: high for retrieval-pipeline.md (documents existing code), medium for markdown-backend.md (design exploration with unvalidated estimates).

## Judgment calls & deviations
- Put retrieval-pipeline.md in docs/design/ (shipped architecture) rather than planning/ — the doc describes the current system, not a proposed change.
- Put markdown-storage-backend.md in planning/ rather than research/ — it's a design exploration for a potential feature, not a research investigation.
- Put the paper plan in research/flat-file-storage-paper/ — it's a research program, not a feature plan.

## Backlog delta
Filed: none. Closed: none. Deferred: none.

## Drift & forward-collisions
- Backward — none. This session was additive docs; no existing issues affected.
- Forward — none identified.

## For the reviewer
- Sanity-check: the scale estimates in markdown-storage-backend.md (5K/10K/50K walls) are educated guesses. If this moves toward implementation or the paper, they need empirical validation.
- Thin verification: the retrieval-pipeline.md doc was not reviewed against the cluster edition's search path (only the personal edition's SQLiteBackend and the cluster edition's memory.py were explored). The doc claims equivalence; worth a spot-check.
- Wants guidance: none.

## Risks / watch-fors
- The retrieval-pipeline.md doc and the existing two-vector-retrieval.md now cover overlapping territory (RRF, signals, weights). If either is updated, the other may need a consistency pass.

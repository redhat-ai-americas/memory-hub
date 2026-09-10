# Session Summary -- 2026-08-21 -- public-benchmarks -- Reproduction run and upstream PR submission

**Plan:** NEXT_SESSION-public-benchmarks.md   **Commits:** dc73114..57b064f (agent-memory-benchmark fork), none on memory-hub
**Deployed:** none   **Model:** Opus 4.6

## Plan vs. actual
Planned: verify credits, smoke test, full 589-query reproduction run, submit upstream PR.
Shipped: all four steps completed. Score landed at 83.7%, submitted as PR #34 to vectorize-io/agent-memory-benchmark.
Slipped: none. One DNS blip at query 265 handled by checkpoint resume.

## Shipped
- Full PersonaMem 32k reproduction: 83.7% (493/589) with gemini-3.1-pro-preview (`outputs/personamem/memoryhub/rag/32k.json.gz`, 14MB compressed)
- Upstream issue vectorize-io/agent-memory-benchmark#33 (provider introduction)
- Upstream PR vectorize-io/agent-memory-benchmark#34 (adapter + results + manifest, from clean `memoryhub-provider` branch cherry-picked off upstream/main)
- Removed GOOGLE_API_KEY fallback from fork's cli.py, hindsight.py, ogham.py (`dc73114`)
- Added lint script `scripts/lint-no-google-api-key.sh` in fork
- CLAUDE.md note: use GEMINI_API_KEY exclusively for this project
- Memory: `feedback_publish_what_we_get` -- commit to publishing benchmark results rather than gate-keeping on a target score

## Verification & confidence
- 589/589 queries completed and checkpointed (118 batches of 5)
- Smoke test 3/3 correct before full run
- Results file verified: 493 correct, 0.8370 accuracy
- Compressed output matches upstream format (14MB, comparable to Hindsight's 12MB)
- PR branch created from upstream/main with selective cherry-pick; diff verified to contain only MemoryHub-specific files
- Confidence: high -- results are real, pipeline ran end-to-end, checkpoint system handled a mid-run DNS failure

## Judgment calls & deviations
- Score 83.7% vs original 84.9%: 1.2 point delta, attributed to the 2x context token gap (160k avg vs 26k original). Per the "publish what we get" decision, submitted as-is rather than investigating further.
- Context truncation in submitted results: truncated context field to 80k chars per query (matching Hindsight's ~72k) to get compressed size under GitHub's 100MB limit. Full results preserved locally.
- GOOGLE_API_KEY removal: applied across the fork (not just our adapter) because cli.py was setting GOOGLE_API_KEY globally, causing the SDK to pick the wrong account. Fork-only change, not in the upstream PR.

## Backlog delta
Filed: vectorize-io/agent-memory-benchmark#33 (external, provider intro)
Memory: `feedback_publish_what_we_get`
Deferred: context token gap investigation (2x vs original) -- noted in PR, not blocking

## Drift & forward-collisions
- Backward: none on memory-hub repo. This session's work was entirely in the AMB fork.
- Forward: Phase 2 (AMB Leaderboard PR) is now submitted as vectorize-io/agent-memory-benchmark#34. NEXT_SESSION-public-benchmarks.md Phase 2 "Submit PR" is done pending maintainer review.

## For the reviewer
- Sanity-check: the 83.7% vs 84.9% delta. The 2x context token gap (160k avg tokens) is the likely cause. Worth investigating if we do a score improvement sprint (Phase 5), but not blocking the submission.
- Thin verification: the GOOGLE_API_KEY removal was tested only by running the smoke test + full run against the memoryhub provider. Other providers (hindsight, ogham) were not tested with the change.
- Wants guidance: none.

## Risks / watch-fors
- Upstream PR review has no SLA. Plan says "ping after 2 weeks if stalled." Other open PRs (#24, #25, #29) have been waiting weeks to months.
- The 160k avg context tokens is notably high and may draw questions from reviewers. The root cause (K=70 retrieval depth with large verbatim memories) is a MemoryHub architectural characteristic, not a bug.

# Retrospective: Two-Tier Storage with Semantic Chunking

**Date:** 2026-04-11
**Effort:** Implement #120 — route oversized memory content to MinIO with semantic chunk children for searchability
**Issues:** #120, #173 (suggest_merge consolidation), #174 (get_memory_history consolidation)
**Commits:** `a0ed756`, `d851daf`, `4605f74`, `e3840b8`, `75930b8`

## What We Set Out To Do

Implement the two-tier storage design from `docs/storage-layer.md`: S3 adapter, threshold-based routing, read-time hydration, version chain semantics, and tests. The issue listed 5 open design questions to resolve first.

Also planned: #62 (Pattern E push filter) if time allowed, plus setting up #168 for next session.

## What Changed

| Change | Type | Rationale |
|--------|------|-----------|
| Semantic chunking instead of prefix-only embedding | Good pivot | User proposed chunk-embed with graph linkage. Better retrieval quality — every section is independently searchable, not just the opening. |
| No new MCP tool — `hydrate` on `read_memory` instead | Good pivot | Anthropic tool design article showed consolidation is better. Kept tool count at 15. |
| Tool audit produced #173 and #174 | Emergent | Reading the Anthropic article triggered a full audit. `suggest_merge` and `get_memory_history` identified as consolidation candidates. |
| #62 was already shipped | N/A | Discovered at session start — closed April 8 with all 7/7 ergonomics candidates. |
| Threshold lowered from 4096 to 1024 bytes | Bug fix | Smoke test revealed embedder rejects >1100 chars of English text. 4096 left a gap where content was too large for the embedder but too small for S3. |
| Prefix lowered from 1500 to 1000 chars | Bug fix | Same root cause — 1500 chars exceeded embedder's actual limit (~1100 chars). |
| `scope_id` added to `update_memory` | Bug fix | Pre-existing bug caught by review sub-agent. Project/role-scoped memories lost their scope_id on every version bump. |

## What Went Well

- **Design discussion was efficient.** Resolved 5 design questions, added chunking, decided tool consolidation, and planned the full implementation in one round before touching code.
- **The `_create_chunk_children` helper** shared between create and update eliminated duplicate code. Extracted during review, not afterthought.
- **Review sub-agent caught two real bugs** — the `scope_id` drop (pre-existing, critical) and the missing `try/except` around chunk creation (embedder failure would lose already-committed parent).
- **End-to-end smoke test was worth the effort.** Found two configuration bugs (threshold and prefix) that unit tests couldn't have caught because they don't hit the real embedder.
- **Tool audit was high-value for low effort.** Reading one article and reviewing tool descriptions produced two concrete consolidation issues.

## Gaps Identified

| Gap | Severity | Resolution |
|-----|----------|------------|
| Threshold and prefix were wrong on first deploy — required two fix-commit cycles | Process | The root cause was assuming the embedder's limit from docs (~512 tokens) instead of measuring it. **Lesson: always measure production limits empirically before setting config defaults.** |
| MCP container uses pip-installed `memoryhub_core` — config changes require rebuild, not just env var override | Medium | Worked around with env var override for this session. Container build should invalidate pip cache for memoryhub_core. |
| 41 of 265 MCP tool tests fail with greenlet import error | Pre-existing | Not related to #120. The MCP venv is missing the `greenlet` package. |
| MinIO secret has plaintext dev credentials in git | Low | Fine for sandbox. Production would need a Kustomize overlay. |
| #119 (error message translation for 413) not implemented | Low | The 413 gap is now structurally prevented by the lower threshold, but raw HTTP errors from the embedder still surface for edge cases. |

## Action Items

- [x] `ensure_bucket()` called lazily on first `put_content` (no startup hook needed)
- [x] End-to-end smoke test: write oversized memory, hydrate, delete — all verified
- [x] Threshold lowered to 1024 bytes based on empirical embedder limit
- [x] Prefix lowered to 1000 chars
- [x] MinIO deployed, creds wired, rdwj promoted to cluster-admin
- [ ] File issue for greenlet dependency in MCP venv
- [ ] #119 still open for error message translation

## Patterns

**Start:**
- **Empirically measure production limits before setting config defaults.** We assumed 4 KB from the embedder's documented 512-token limit, but the actual char limit was ~1100. Docs say tokens, production cares about characters. Always binary-search the real limit.
- **Run end-to-end smoke tests against the deployed cluster before closing implementation issues.** Unit tests with mocked S3 and embedding services can't catch configuration mismatches. The smoke test found two bugs that would have been production incidents.

**Continue:**
- **Design discussion before implementation.** The chunking pivot and tool consolidation decision both came from the design conversation, not from code review.
- **Review sub-agents after implementation.** Caught `scope_id` bug and `try/except` gap.
- **Reading external articles as design catalysts.** The Anthropic tool design article directly shaped the implementation (no new tool) and triggered the audit.
- **Aggressive delegation** for independent work (S3 adapter, chunker, tests, deploy manifests) while keeping MCP tool changes in main context per project convention.

**Validated:**
- **The `branch_type` free-form string model is extensible.** Adding "chunk" required zero schema changes — worked exactly as designed.
- **Default search branch omission handles chunks correctly.** No search code changes needed for chunk filtering — the existing parent-in-result-set logic does the right thing.

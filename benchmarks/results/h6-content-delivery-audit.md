# H6 Content-Delivery Audit: Search Returns Truncated Content

Date: 2026-07-14
Auditor: Matrix A session (PRs #384, #385, #386)

## Summary

MemoryHub's search path returns a 1000-character prefix of each memory
instead of the full content. For PersonaMem's documents (avg 27,912
chars), the answerer sees 3.6% of each document. This is the root cause
of the 21pp accuracy gap between BM25-local (67.7%) and MemoryHub MCP
(46.5%).

## Mechanism

Two config values in `src/memoryhub_core/config.py` control the behavior:

```python
s3_threshold_bytes: int = 1024   # line 72
s3_prefix_chars: int = 1000      # line 73
```

**Write path** (`services/memory.py:104-170`):

1. Content exceeding 1024 bytes is classified as "oversized"
2. Full content is uploaded to MinIO (S3)
3. Only the first 1000 chars are stored in the PostgreSQL `content` column
4. Embedding is computed on the 1000-char prefix

**Search path** (`services/memory.py`, `search_memories()`):

1. Queries PostgreSQL for matching nodes
2. Returns the `content` column directly -- the 1000-char prefix
3. Never checks `storage_type` or `content_ref`
4. Never fetches from MinIO

## Evidence

### Database state

Every memory in the `amb-benchmark` tenant is exactly 1000 characters:

```
 owner_id       | num_memories | avg_content_len | max_content_len | min_content_len
----------------+--------------+-----------------+-----------------+-----------------
 amb-5c00a99... |            7 |            1000 |            1000 |            1000
 amb-87fcbc7... |            7 |            1000 |            1000 |            1000
 amb-d4a1f9d... |            6 |            1000 |            1000 |            1000
```

### Raw dataset documents

```
Total docs: 195
Avg doc length: 27,912 chars
Min: 3,923 chars
Max: 60,818 chars
Docs > 1000 chars: 195/195
```

### Side-by-side context comparison (same 5 queries, same user)

| Metric | BM25 local | MCP (MemoryHub) | Ratio |
|--------|-----------|-----------------|-------|
| Context tokens per query | 5,179 | 991 | 5.2x |
| Context chars per query | ~28,000 | ~5,068 | 5.5x |
| Memories returned | 10 | 5 | 2.0x |
| Content per memory | Full (~2,800 chars) | Truncated (1,000 chars) | 2.8x |

The MCP context shows mid-sentence truncation in every memory:

```
[USER] User: Hi there! I've recently been diving deeper into my passion
for music and technology. It's been quite a journey since I started
creating digital music remixes. Every aspect of this
```

The sentence ends abruptly at the 1000-char boundary.

### Accuracy impact

| Configuration | Context tokens | Accuracy |
|--------------|---------------|----------|
| BM25 local (full content) | 5,179 | 67.7% |
| MCP vector-only (truncated) | 997 | 46.5% |
| MCP vector + keyword (truncated) | 997 | 46.5% |
| MCP vector + reranker (truncated) | 997 | 46.5% |
| MCP all signals (truncated) | 997 | 46.5% |

All four MCP signal configurations produce identical results (274/589
correct). Signal tuning cannot compensate for missing content.

## Impact assessment

This affects any memory written through MemoryHub whose content exceeds
1024 bytes. For typical agent memory workloads (conversation summaries,
session notes, extracted facts), most content will exceed this threshold.

The defect is invisible to the writing agent (the write succeeds and
returns the full content). It only manifests when another agent searches
and receives the truncated prefix.

## Recommended fixes (in order of preference)

### Option A: Hydrate from S3 at search time

Add an S3 fetch step in the search path for nodes where
`storage_type = 's3'`. This is the correct long-term fix: the database
stores a search-optimized prefix for embedding and ranking, while the
full content is fetched on demand for the final response.

Trade-off: adds latency (one S3 GET per result, ~5-20ms each). Can be
parallelized across the result set.

### Option B: Raise the S3 threshold

Set `s3_threshold_bytes` high enough that typical memories stay inline.
Most agent memories are under 100KB; a threshold of 102400 (100KB) would
keep them in PostgreSQL with no S3 round-trip.

Trade-off: larger PostgreSQL rows, but well within what PostgreSQL
handles efficiently. Does not solve the problem for genuinely large
content (multi-page transcripts).

### Option C: Return content_ref in search results

Include the S3 reference in search results so the client can fetch full
content. Requires SDK changes and shifts the fetch responsibility to the
consumer.

Trade-off: breaks the current API contract where `content` is the full
text. Not recommended as primary fix.

## Files involved

- `src/memoryhub_core/config.py:72-73` -- threshold and prefix settings
- `src/memoryhub_core/services/memory.py:151-156` -- write-path truncation
- `src/memoryhub_core/services/memory.py` -- search path (no S3 hydration)
- `src/memoryhub_core/storage/s3.py` -- S3 adapter (has `get_content()`)

# Benchmark System Map

Reference document for the MemoryHub benchmark stack. Describes the
data flow, signal activation state, and corpus provenance. Updated
when signals activate or the deployment changes.

## Stack Diagram

```
EvalHub Server (memoryhub-eval namespace)
  submits JobSpec
    │
    ▼
AMBAdapter
  benchmarks/evalhub-adapter/src/memoryhub_evalhub/adapter.py
  wires env vars, runs preflight, delegates to EvalRunner
    │
    ▼
EvalRunner
  benchmarks/amb-harness/src/memory_bench/runner.py
  iterates queries, calls memory provider, scores answers
    │
    ▼
MemoryHubProvider
  benchmarks/amb-harness/src/memory_bench/memory/memoryhub.py
  ingest via client.write(), retrieve via client.search()
    │  uses memoryhub SDK (MemoryHubClient)
    ▼
MCP Server  (memory-hub-mcp namespace, streamable-HTTP on /mcp/)
  routes to search_memories() or search_memories_with_focus()
    │
    ▼
PostgreSQL + pgvector  (memoryhub-db namespace)
  + Valkey  (memory-hub-mcp namespace)  for focus state cache
  + TEI reranker  (when deployed, currently inactive)
```

The benchmark exercises the **non-focus** `search_memories()` path because
the harness never calls `set_focus`. This path supports vector + keyword
signals. The focused path supports all six signals but requires an
active session with focus declared.

## Signal Activation Matrix

| Signal | Code location | Activation prerequisite | Verify-active check | Active today? |
|--------|--------------|------------------------|--------------------|----|
| **vector** | `memory.py` cosine_distance query | pgvector extension + embedding column populated | `SELECT COUNT(*) FROM memory_nodes WHERE embedding IS NOT NULL AND tenant_id='amb-benchmark'` equals total node count | YES |
| **reranker** | `memory.py:1418` (focused path only) | `MEMORYHUB_RERANKER_URL` env var + TEI service reachable | `curl -sf $MEMORYHUB_RERANKER_URL/info` returns 200 | NO (#342) |
| **keyword** | `memory.py:1019` (non-focus), `memory.py:1507` (focused) | `search_vector` tsvector column (migration 024) + GIN index + `keyword_boost_weight > 0` | `SELECT COUNT(*) FROM memory_nodes WHERE search_vector IS NOT NULL AND tenant_id='amb-benchmark'` | YES (PR #379) |
| **focus** | `memory.py:1454` (focused path only) | `set_focus()` called + Valkey reachable + focus_string non-empty | `HGET memoryhub:sessions:<session_id> focus` | NO (benchmark never calls set_focus) |
| **domain** | `memory.py:1470` (focused path only) | `domains` array populated on nodes + domain tags in query | `SELECT COUNT(*) FROM memory_nodes WHERE domains IS NOT NULL AND array_length(domains, 1) > 0 AND tenant_id='amb-benchmark'` | NO (no domain tags) |
| **graph** | `memory.py:1378` (focused path only) | `memory_relationships` edges exist + `graph_depth > 0` | `SELECT COUNT(*) FROM memory_relationships mr JOIN memory_nodes mn ON mr.source_id = mn.id WHERE mn.tenant_id='amb-benchmark'` | NO (no edges) |

`VALID_SIGNAL_NAMES = frozenset({"reranker", "focus", "keyword", "domain", "graph"})` (memory.py L61).

Activation is **path-dependent**: signals only fire if the search path
invokes them AND the infrastructure prerequisite is met. The benchmark
uses `search_memories()` (non-focus), so reranker/focus/domain/graph are
structurally inactive regardless of deployment.

## Corpus Provenance

### amb-benchmark tenant

195 parent documents, 0 chunk nodes (post-cleanup per #369).

The original corpus had 6,419 chunk nodes (`branch_type='chunk'`) which
contaminated retrieval results with a 33:1 chunk-to-parent ratio. Chunks
were deleted as part of the #369 baseline discrepancy investigation.

Ingested via SDK `client.write()` from the PersonaMem 32k dataset. No
`semantic_chunk()` call (raw documents only in current corpus).

### Verification SQL

```sql
SELECT
  COUNT(*) AS total,
  COUNT(*) FILTER (WHERE branch_type = 'chunk') AS chunks,
  COUNT(*) FILTER (WHERE branch_type IS NULL OR branch_type != 'chunk') AS parents
FROM memory_nodes
WHERE tenant_id = 'amb-benchmark';
-- Expected: total=195, chunks=0, parents=195
```

Run this before each matrix run. The `benchmarks/preflight.py` module
automates this check along with signal activation verification.

## Preflight

Before any benchmark run, the preflight module (`benchmarks/preflight.py`)
probes the live deployment and emits a manifest JSON documenting signal
activation state and corpus provenance. Benchmark configs declare an
`expected_manifest` block; the adapter refuses to run if the deployment
doesn't match.

```bash
# Standalone (requires DB port-forward):
oc port-forward -n memoryhub-db svc/postgresql 25432:5432 --context mcp-rhoai &
python benchmarks/preflight.py

# With config enforcement:
python benchmarks/preflight.py --config benchmarks/evalhub-adapter/config/matrix/baseline.yaml
```

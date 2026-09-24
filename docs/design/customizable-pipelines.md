# Customisable Retrieval and Ingestion Pipelines

Status: Research recommendation for WRIG-1481

## Executive recommendation

MemoryHub should move from parameter-only customisation to **contracted,
server-registered pipeline stages**, but should not expose an unrestricted
plugin loader or a general-purpose DAG as the first implementation.

The recommended shape is:

1. A typed stage contract defines the input and output of each stage.
2. A pipeline definition selects named stages from a server-side registry.
3. Retrieval uses a small directed graph: independent recall stages may run in
   parallel, then feed an explicit fusion stage, reranking, and post-processing.
4. Ingestion uses an ordered chain with optional enrichment branches.
5. Governance, tenant isolation, provenance, and versioning are mandatory
   service-layer stages. A pipeline definition cannot disable or replace them.
6. YAML selects an approved pipeline and its bounded parameters. It does not
   import Python modules, execute expressions, or contain credentials.

This gives users meaningful composition—such as adding an external recall
source or a domain-specific enrichment stage—while keeping MemoryHub's
security and audit guarantees in the service layer.

## Evidence from the current implementation

MemoryHub already has the beginnings of this model:

| Area | Current extension point | Current limitation |
| --- | --- | --- |
| Write-time curation | Tenant rules, custom regex patterns, thresholds, `force` for similarity gating | Regex → similarity → decision order is fixed; new stage types require code |
| Retrieval | Signal weights, `disabled_signals`, optional reranker, graph and keyword signals | `search_memories_with_focus` owns the stage order and implementation choices |
| SDK extraction | `Extractor` ABC and a list of custom extractors | Extract, enrich, dedup, and route phases are hardcoded |
| Project configuration | `.memoryhub.yaml` with typed `retrieval_defaults` | Configuration changes call parameters, not pipeline composition |

The server's current retrieval stages are query embedding, vector recall,
keyword recall, focus/domain/graph signals, RRF fusion, reranking, and
chunk-to-parent expansion. The current curation path performs regex scanning,
embedding similarity, and a gating decision. These are natural boundaries for
contracts, but they should not all become independently user-configurable
immediately.

## Architecture pattern

### Use a typed component registry with a constrained graph

The closest fit is a combination of three patterns:

- **Strategy** for replacing one implementation, such as the reranker.
- **Pipeline/Chain** for the normal ordered ingestion path.
- **Dataflow graph** only where parallel branches are intrinsic, especially
  multiple retrieval sources that must later be fused.

Decorator is useful internally for cross-cutting behavior such as timing and
tracing, but it should not be the user-facing configuration model. A general
plugin architecture that imports arbitrary code is unsafe for a multi-tenant
server and makes compatibility, FIPS validation, and deployment reproducibility
harder.

Haystack is a useful comparison: components expose named inputs and outputs,
connections are type-checked before execution, and pipelines can run
independent branches concurrently. Its model supports the contracts and
validation ideas recommended here, but MemoryHub should keep a smaller,
domain-specific surface. LlamaIndex's query-pipeline documentation similarly
shows sequential chains and DAGs, while warning that its older declarative
pipeline abstraction is in feature freeze; that is a reason not to make a
general DAG the primary product abstraction.

### Pipeline contexts

Stages should receive a context object rather than a growing list of function
arguments. The context contains request data, authorized scope information,
intermediate values, and an execution trace. It must be immutable from the
caller’s perspective; stages return a new value or an explicitly named update.

Illustrative Python types:

```python
@dataclass(frozen=True)
class RetrievalContext:
    query: str
    tenant_id: str
    authorized_scopes: AuthorizedScopes
    focus: str | None = None
    request_id: str = ""


@dataclass
class RecallSet:
    candidates: list[Candidate]
    source: str
    metadata: dict[str, object]


class RecallStage(Protocol):
    name: str
    async def run(self, ctx: RetrievalContext) -> RecallSet: ...


class FusionStage(Protocol):
    name: str
    async def run(
        self, ctx: RetrievalContext, inputs: list[RecallSet]
    ) -> RankedCandidates: ...
```

The production implementation should use Pydantic models or equivalent typed
schemas at the configuration boundary. The snippet is an interface sketch,
not a public API commitment.

## Stage granularity

### Retrieval: five composition boundaries

1. **Query preparation** — normalize the query and prepare optional focus,
   domain, and filter inputs. Embedding generation remains an implementation
   detail of a registered recall stage in the first release.
2. **Recall** — retrieve candidates from one source. Built-in examples are
   pgvector, PostgreSQL keyword search, graph expansion, and a future external
   search adapter. Recall stages may run in parallel.
3. **Fusion** — combine ranked candidate sets. RRF is the default strategy;
   weighted score fusion can be a later strategy.
4. **Reranking** — optionally score the fused candidate pool with a registered
   reranker.
5. **Post-processing** — apply result-unit selection, chunk-to-parent
   expansion, policy filters, and response shaping.

Do not expose `embed_query`, vector normalization, SQL filter construction, or
individual database statements as separate configuration stages. They are too
fine-grained and contain security-sensitive implementation details.

### Ingestion: six composition boundaries

1. **Source intake** — accept an agent write, thread message, document, or a
   registered external connector.
2. **Normalization and chunking** — convert source data to the canonical input
   and split large content.
3. **Enrichment** — extract entities, classify topics, detect language, or add
   other metadata.
4. **Deduplication and reconciliation** — decide whether the input creates,
   updates, or links to an existing memory.
5. **Governance and curation** — enforce policy, scan secrets/PII, authorize
   the write, and record the decision.
6. **Persistence and provenance** — write the memory and source links in the
   governed transaction.

Users may configure source, chunking, enrichment, and reconciliation strategies
within approved limits. Governance and persistence remain mandatory and are
owned by the MemoryHub service.

## Configuration proposal

Use a versioned, declarative configuration. Keep the first schema intentionally
small and allow only registered stage names:

```yaml
pipeline_version: 1

retrieval_pipeline:
  template: hybrid-memory-v1
  recalls:
    - type: pgvector
      config: {k: 24, metric: cosine}
    - type: keyword
      config: {k: 24, language: english}
    - type: external_recall
      ref: arxiv-search
      config: {k: 12, timeout_ms: 400}
  fusion:
    type: rrf
    config: {weights: {pgvector: 1.0, keyword: 0.15, external_recall: 0.25}}
  rerank:
    type: configured-reranker
    config: {top_k: 32}
  post_process:
    - type: chunk_to_parent
      config: {expand: true}
```

```yaml
pipeline_version: 1

ingestion_pipeline:
  template: governed-memory-ingestion-v1
  source: agent_write
  stages:
    - type: normalize
    - type: semantic_chunk
      config: {max_tokens: 512}
    - type: entity_enrichment
      config: {enabled: true}
    - type: deduplicate
      config: {threshold: 0.90}
    - type: governed_persist
```

Configuration precedence should be:

1. Service defaults.
2. Tenant or project pipeline selection.
3. Per-request overrides for explicitly permitted scalar parameters, such as
   `max_results` or a bounded weight.

Per-request configuration must not be able to introduce a new stage, change a
stage reference, bypass authorization, or disable mandatory governance.

The existing `.memoryhub.yaml` should continue to work. Existing retrieval
parameters map to the default `hybrid-memory-v1` template, so migration is
additive rather than a flag day.

## Extension-point taxonomy

### First wave: safe and high-value

- Additional recall sources behind a registered adapter.
- Reranker strategy and model reference.
- Result post-filters and result-unit shaping.
- Ingestion enrichment stages that only add metadata.
- Chunking strategy and bounded limits.

### Later, with stronger controls

- Reconciliation strategies.
- External HTTP stages with retries, timeouts, authentication references,
  circuit breakers, and an explicit fail-open/fail-closed policy.
- Custom fusion strategies, subject to deterministic output and auditability.

### Keep core and non-configurable

- Tenant and authorization filters.
- Secret/PII policy enforcement.
- Provenance and source-message links.
- Version history and append/update semantics.
- Audit events for writes, governance decisions, and pipeline versions.
- PostgreSQL/pgvector storage access and transaction boundaries.

Custom recall stages must receive only the already-authorized query context and
must return candidates that are filtered again before they can appear in the
response. A remote source must never be trusted to enforce MemoryHub scope
rules.

## Contracts and validation

Every registered stage should declare:

- a stable stage type and implementation version;
- input and output schema names;
- whether it is deterministic or best-effort;
- timeout and resource limits;
- whether it may run in parallel;
- failure behavior (`fail`, `skip`, or `fallback`);
- required credentials by reference, never inline;
- observability fields safe to emit in logs.

Pipeline validation should happen when a configuration is loaded or changed,
not on the first user request. Validation should check:

- stage names exist in the allow-list;
- required inputs are available;
- input and output schemas are compatible;
- the graph has no unsupported cycle;
- mandatory governance and provenance stages are present;
- limits are within deployment policy;
- external references resolve to an approved connector;
- the configuration version is supported.

At runtime, record a pipeline execution trace containing the pipeline ID and
version, stage names and versions, durations, candidate counts, fallback
decisions, and the final result IDs. Do not record secrets or raw external
credentials. This makes custom behavior diagnosable without weakening the
existing audit model.

## Failure and performance policy

The default should be safe degradation:

- A failed optional recall source is skipped and its absence is reported in
  trace metadata.
- A failed reranker falls back to the previous rank order, as today.
- A failed governance stage fails closed and does not persist a write.
- A failed persistence/provenance transaction rolls back the write.
- Every external stage has a timeout, bounded result count, and concurrency
  limit.

The service should expose per-stage latency and candidate-count metrics. A
pipeline is not ready for production until it has unit tests for each stage,
composition tests for the default templates, authorization tests for custom
recall sources, and benchmark comparisons against the existing default path.

## Versioning and compatibility

Use three version fields:

- `pipeline_version`: configuration schema version;
- template version: the named composition, such as `hybrid-memory-v1`;
- stage implementation version: the behavior of one registered component.

Unknown future fields should be rejected in the first schema so typos cannot
silently change behavior. Deprecated stage names should produce a warning and
have a documented migration path. The default template must remain available
for at least one deprecation window, and invalid custom configuration should
fall back to the known-good default only when the caller has explicitly chosen
that policy; silently changing a requested compliance pipeline to a default
would be unsafe.

## Prototype recommendation

Prototype retrieval first, with one concrete use case: add a registered
external recall stage to the existing hybrid search path.

The prototype should:

1. Define `RecallSet`, `RankedCandidates`, and a `RecallStage` contract.
2. Wrap the current pgvector and keyword recalls as built-in stages.
3. Run built-in and external recall concurrently.
4. Reuse the existing RRF implementation as the fusion stage.
5. Apply the existing rerank and chunk-to-parent behavior as post-fusion stages.
6. Enforce the existing SQL authorization filter before and after external
   candidate merging.
7. Add a test-only external stage that returns deterministic candidates; no
   production network dependency is needed for the prototype.
8. Compare latency, recall, result ordering, fallback behavior, and audit trace
   output with the current `search_memories_with_focus` path.

This proves composition without prematurely changing the public MCP tool
surface. Once the contract is stable, the same registry can support ingestion
enrichment and chunking. A full arbitrary DAG, dynamic Python plugins, and
tenant-authored executable code should remain out of scope for the first
release.

## Implementation priority

1. **Design and contracts** — stage interfaces, context models, registry,
   validation errors, and execution trace.
2. **Retrieval prototype** — parallel recall plus existing RRF/rerank behavior.
3. **Configuration and migration** — versioned templates and `.memoryhub.yaml`
   compatibility.
4. **Ingestion composition** — source, chunking, enrichment, and reconciliation
   stages, while keeping governance and persistence in the core path.
5. **External connectors** — approved adapters with credential references,
   budgets, retries, and circuit breakers.

The recommendation is therefore **yes, invest in pluggable pipelines**, but
start with a typed, allow-listed, template-based system. Parameter-based
configuration remains the compatibility layer and the right mechanism for
small tuning changes; stage composition is reserved for genuine architectural
variation.

## References

- [MemoryHub two-vector retrieval design](two-vector-retrieval.md)
- [MemoryHub server architecture](../ARCHITECTURE.md)
- [MemoryHub governance design](governance.md)
- [Haystack pipelines](https://docs.haystack.deepset.ai/docs/pipelines)
- [Haystack custom components](https://docs.haystack.deepset.ai/docs/custom-components)
- [LlamaIndex query pipelines](https://docs.llamaindex.ai/en/stable/module_guides/querying/pipeline/)
- [LangChain LCEL](https://python.langchain.com/docs/concepts/lcel/)
- [Apache Airflow DAGs](https://airflow.apache.org/docs/apache-airflow/stable/core-concepts/dags.html)
- [Logstash pipeline configuration](https://www.elastic.co/guide/en/logstash/current/configuration.html)

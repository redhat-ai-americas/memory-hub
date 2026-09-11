# OMP-Informed Improvements

Improvements to MemoryHub identified during the Open Memory Protocol prior art
survey and standards sketching session (2026-09-09). These are grounded in
cross-ecosystem analysis of 16 agent harnesses, 10 enterprise memory services,
12 emerging standards, the PTC specification, and the PTC/GAL reference
implementation.

**OMP PRs:**
- [PR #3: Prior art survey](https://github.com/The-AI-Disclosures-Project/Open-Memory-Protocol/pull/3)
- [PR #4: Standards sketch](https://github.com/The-AI-Disclosures-Project/Open-Memory-Protocol/pull/4)

## Priority order

| # | Improvement | Subsystem | Priority |
|---|-------------|-----------|----------|
| 1 | Upstream trust level tracking | curator | near-term |
| 2 | MOF export format | mcp-server, client | near-term |
| 3 | Context assembly pipeline | mcp-server | near-term |
| 4 | Deterministic dreaming gates | curator | near-term |
| 5 | PTC taint ingestion hook | mcp-server | future |
| 6 | Per-scope consent signals | mcp-server, client | future |
| 7 | Formalize contradiction signaling | mcp-server | future |
| 8 | generating_model field | memory-tree | future |
| 9 | Memory source admission design | mcp-server | future |

Items 1-4 are independent and high-value. Item 5 depends on item 1.
Items 6-9 are independent of each other.

---

## 1. Upstream trust level tracking through dreaming {#upstream-trust-level}

**Problem:** MemoryHub's dreaming pipeline extracts memories from conversations
and tags them `source: dreaming`. If the conversation contained tainted content
(a tool output from a web scrape, an untrusted MCP server response, content
from an unauthenticated channel), the extracted memory carries no record of
that upstream trust level. The taint is laundered through extraction: the
memory looks agent-derived, and the provenance chain is broken.

This is the most important security gap identified in the OMP analysis. The
principle: when a memory is derived from content that arrived through a channel,
the memory must carry the channel's trust level, not the extractor's. An
extraction pipeline is a transform, not an endorsement. The trust of the
output cannot exceed the trust of the input.

**Improvement:** Add an `upstream_trust_level` field to MemoryNode with values
`trusted`, `untrusted`, or `mixed` (when extracted from a conversation
containing both trusted and untrusted content). The dreaming pipeline
determines this from the conversation's source metadata at extraction time.

**Touches:**
- `src/memoryhub_core/models/memory.py` (new column)
- `src/memoryhub_core/models/schemas.py` (new field on create/read schemas)
- `sdk/src/memoryhub/extraction/` (extraction pipeline carries trust level)
- Alembic migration (new column with `'trusted'` default for existing rows)

**Dependencies:** None. This is the foundation that items 3 and 5 build on.

---

## 2. MOF export format {#mof-export}

**Problem:** MemoryHub stores memories in a proprietary schema. If OMP
converges on a standard memory object format, the first memory system that
can export and import in that format wins the portability argument. MemoryHub
already has most of the required MOF fields (the data model audit showed the
mapping is close), but no standard export format exists.

**Improvement:** Add MOF export to the MCP server and SDK. Two output formats:

- MOF markdown with YAML frontmatter (for file-based interoperability with
  coding agents)
- MOF JSON (for API-based interoperability with enterprise services)

The field mapping from MemoryNode to MOF:

| MOF field | MemoryHub field | Notes |
|-----------|----------------|-------|
| id | id | Direct |
| logical_id | logical_id | Direct |
| content | content | Direct |
| scope | scope | Vocabulary mapping needed |
| scope_qualifier | scope_id | Direct |
| owner | owner_id | Direct |
| origin_type | source | Vocabulary mapping (agent/dreaming/import to user-stated/agent-inferred/system-generated/imported) |
| created_at | created_at | Direct |
| memory_type | content_type | Vocabulary mapping (experiential/knowledge/behavioral to fact/preference/instruction/etc.) |
| weight | weight | Direct |
| tags | domains | Direct |
| version | version | Direct |
| status | status | Vocabulary mapping |
| expires_at | expires_at | Direct |
| relevant_until | relevant_until | Direct |
| confidence | (metadata) | Extract from metadata or extraction confidence |
| actor_id | actor_id | Direct |
| driver_id | driver_id | Direct |

Exchange bundles: a manifest (source system, export time, schema version) plus
an array of MOF objects. Conflict resolution on import: skip, overwrite, or
merge-by-timestamp.

**Touches:**
- `memory-hub-mcp/src/tools/` (new export format option or new tool)
- `sdk/src/memoryhub/` (new export method)
- New module for MOF serialization (shared between server and SDK)

**Dependencies:** None.

---

## 3. Context assembly pipeline ordering {#context-assembly-pipeline}

**Problem:** MemoryHub's current injection path (SessionStart hook and
search_memory tool) does not follow a principled ordering of security checks.
Scope enforcement, deduplication, budget management, and provenance checking
happen at various points but are not composed as a pipeline with ordering
invariants. The OMP security considerations document sketched a 9-step
pipeline modeled on PTC's airlock, where cheap deterministic checks filter
before expensive ones.

**Improvement:** Refactor the injection path into explicit ordered stages:

1. Authenticate source (is this memory from an admitted provider?)
2. Validate schema (does the memory conform to expected format?)
3. Enforce scope (does the current principal have access?)
4. Check freshness (is the memory expired or stale via `relevant_until`?)
5. Deduplicate (has this content already been selected via `content_hash`?)
6. Apply budget (does the memory fit the remaining context budget?)
7. Screen content (optional injection classifier, refuse-or-pass only)
8. Stamp provenance (record what was injected and why)
9. Emit to context

The ordering matters: scope enforcement before deduplication prevents probing
scope boundaries via duplicates. Budget enforcement before screening prevents
context exhaustion from consuming screening resources. Screening can only
refuse or pass, never upgrade trust.

This is a refactor of existing logic into a pipeline, not new functionality.
The individual checks mostly exist; the improvement is composing them in an
explicit, ordered sequence.

**Touches:**
- `memory-hub-mcp/src/tools/search_memory.py` (retrieval pipeline)
- The SessionStart hook's memory injection logic
- Possibly a new `pipeline.py` module for the assembly stages

**Dependencies:** Benefits from item 1 (upstream trust level) for step 7, but
can be implemented without it.

---

## 4. Deterministic gates before dreaming consolidation {#dreaming-gates}

**Problem:** MemoryHub's dreaming pipeline runs LLM-based extraction and
reconciliation on conversation content. The LLM consolidation step is
expensive and runs on all candidates. OpenClaw's three-phase dreaming uses
deterministic gates (minimum score >= 0.75, minimum recall count >= 3, minimum
unique queries >= 3) that candidates must pass before the model runs
consolidation. This reduces LLM costs and improves memory quality by ensuring
only well-evidenced candidates reach consolidation.

**Improvement:** Add configurable threshold gates before the LLM consolidation
step in the dreaming pipeline:

- `min_recall_count`: minimum number of times a candidate was retrieved in
  search results before it qualifies for promotion
- `min_unique_queries`: minimum number of distinct queries that surfaced the
  candidate
- `min_score`: minimum relevance score threshold

Candidates that do not meet all thresholds are deferred to the next dreaming
cycle, not discarded. This is a quality filter, not a discard mechanism.

**Touches:**
- `sdk/src/memoryhub/extraction/` (extraction pipeline, reconciliation logic)
- Dreaming configuration (new threshold settings)
- Possibly `src/memoryhub_core/models/` if recall/query counts need tracking

**Dependencies:** None. May require schema changes if recall counts are not
currently tracked at the candidate level.

---

## 5. PTC taint ingestion hook {#ptc-taint-hook}

**Problem:** The PTC reference implementation has
`TurnContext.ingest_memory_taint(taint_flag, source)` ready for a memory
system to call, but nothing wires it up. MemoryHub could be the first memory
system that reports taint at read time, completing the bridge: MemoryHub
preserves taint provenance at rest, reports it when a memory is recalled, and
PTC enforces the no-write-up floor on the resulting turn.

**Improvement:** When a memory with `upstream_trust_level: untrusted` is
returned from search_memory or read_memory, include taint metadata in the
response. For PTC-integrated harnesses, this metadata feeds into the
TurnContext. For non-PTC harnesses, it serves as advisory information.

The response would include:
```json
{
  "taint": {
    "tainted": true,
    "sources": ["connector:slack.channel_read"]
  }
}
```

**Touches:**
- `memory-hub-mcp/src/tools/search_memory.py` (response enrichment)
- `memory-hub-mcp/src/tools/read_memory.py` (response enrichment)
- `sdk/src/memoryhub/models.py` (taint metadata on Memory response)

**Dependencies:** Requires item 1 (upstream trust level tracking).

---

## 6. Per-scope consent signals {#consent-signals}

**Problem:** Users should be able to turn memory on or off at different scope
levels (personal, project). MemoryHub supports disabling memory via
configuration, but there is no per-scope toggle accessible through the MCP
tools. The MAP sketch defines `memory_enabled` as a protocol-level signal.

**Improvement:** Add a queryable, settable `memory_enabled` state per scope
through the MCP tool interface. When disabled at a scope, writes at that scope
are rejected with an informative error. Reads still work (disabling is not
deletion). The state is stored per user/tenant.

New MCP tool operations:
- `memory_preferences(action="get")` returns current consent state per scope
- `memory_preferences(action="set", scope="project", enabled=false)` toggles

**Touches:**
- `memory-hub-mcp/src/tools/` (new tool or new action on memory tool)
- `src/memoryhub_core/` (consent state storage, write-path enforcement)
- `sdk/src/memoryhub/` (SDK support for consent operations)

**Dependencies:** None.

---

## 7. Formalize contradiction signaling {#contradiction-signaling}

**Problem:** MemoryHub's ContradictionReport is unique among surveyed systems.
The MAP sketch includes contradiction signaling as a standard operation. The
current implementation works but could be aligned with the emerging standard.

**Improvement:** Review the `report_contradiction` MCP tool interface against
the MAP sketch's contradiction signaling operation. Ensure the tool name,
input schema, and response format align with what OMP may standardize. Update
documentation to present contradiction signaling as a standard memory
operation, not a MemoryHub-specific feature.

This is primarily a documentation and schema alignment task.

**Touches:**
- `memory-hub-mcp/src/tools/` (schema review)
- Documentation

**Dependencies:** None.

---

## 8. generating_model field {#generating-model}

**Problem:** When the dreaming pipeline extracts a memory, the model used for
extraction is recorded in extraction run metadata but not as a first-class
field on MemoryNode. For confidence calibration, downstream consumers may want
to weight memories differently based on the model that produced them.

**Improvement:** Add a `generating_model` field to MemoryNode. The extraction
pipeline populates it with the model identifier used for extraction. User-
stated memories leave it null.

**Touches:**
- `src/memoryhub_core/models/memory.py` (new column)
- `src/memoryhub_core/models/schemas.py` (new field)
- `sdk/src/memoryhub/extraction/` (populate on extraction)
- Alembic migration

**Dependencies:** None.

---

## 9. Memory source admission design {#source-admission}

**Problem:** General-purpose agents that attach to messaging platforms and
other external sources create indirect injection paths. An attacker sends
content through a legitimate channel that the memory system treats as a
source. If new memory sources can be auto-discovered without human ceremony,
the attack surface grows silently.

MemoryHub does not currently ingest from channels beyond direct agent
conversations, but if it grows to support channel connectors (Slack, email,
document repositories), each source needs an admission gate.

**Improvement:** Design a pattern for admitting new memory sources with human
ceremony rather than auto-discovery. Modeled on PTC's two-key tool admission:
a code-level declaration of the source plus a human ceremony to activate it.
A source whose schema or content profile changes should drift-quarantine
rather than silently admit new content.

This is a design-only item for now. No implementation needed unless MemoryHub
adds channel connectors.

**Touches:**
- Design document only (this section)
- Future: `src/memoryhub_core/` if channel connectors are added

**Dependencies:** None.

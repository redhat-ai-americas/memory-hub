# Context Assembly Pipeline

When MemoryHub injects memories into an agent's context, the path from "memory exists in the database" to "memory appears in the system prompt" crosses several concerns: authentication, scope enforcement, deduplication, budget management, and provenance tracking. Today these checks happen at various points in the search and injection code, but they are not composed as a pipeline with ordering invariants. This document describes the refactoring of that path into an explicit, ordered pipeline and introduces the `generating_model` field that the pipeline consumes.

## Why ordering matters

The current logic performs the right checks, but their ordering is not enforced. This creates two subtle problems.

**Scope before deduplication.** If deduplication runs before scope enforcement, an attacker can probe scope boundaries by submitting duplicate content and observing which duplicates get filtered. Running scope enforcement first means that out-of-scope memories never reach the deduplication stage, so the deduplication result reveals nothing about what exists in other scopes.

**Budget before screening.** The optional content screening stage (an injection classifier that decides refuse-or-pass) consumes compute. If budget enforcement runs after screening, a flood of low-priority memories can exhaust screening resources before budget cuts them. Running budget enforcement first means only memories that will actually be injected get screened.

These are not hypothetical concerns. They are properties that should hold by construction, not by accident.

## Pipeline stages

The pipeline is a linear sequence of nine stages. Each stage receives a candidate set of memories and either passes, filters, or annotates them. No stage reorders the set; ordering is determined by search relevance scoring before the pipeline runs.

1. **Authenticate source.** Verify that the memory comes from an admitted provider. Memories with unknown or revoked provider credentials are dropped.
2. **Validate schema.** Confirm the memory conforms to the expected MemoryNode format. Malformed records are dropped with a warning.
3. **Enforce scope.** Check that the current principal has access to each memory's scope. User-scoped memories are visible only to their owner. Project, role, organizational, and enterprise scopes follow the existing scope hierarchy (see `memory-tree.md`).
4. **Check freshness.** Drop memories whose `relevant_until` timestamp has passed. Memories without `relevant_until` are treated as indefinitely fresh.
5. **Deduplicate.** Remove memories whose `content_hash` matches one already selected in this assembly pass. The first occurrence (by relevance rank) wins.
6. **Apply budget.** Walk the candidate set in relevance order, accumulating token estimates. When the remaining context budget is exhausted, drop the rest.
7. **Screen content.** Optional stage. Run an injection classifier that makes a binary refuse-or-pass decision. This catches content that passed earlier stages but should not appear in context for safety reasons. Disabled by default; enabled via deployment configuration.
8. **Stamp provenance.** Record which memories were injected, which were filtered (and at which stage), and the pipeline run metadata. This feeds the forensics capability described in `memory-tree.md`.
9. **Emit to context.** Format the surviving memories (full content or stubs, based on weight) and return them for injection.

Each stage is a function with a common signature: it takes the candidate set and pipeline context, returns the filtered candidate set. Stages are composed by the pipeline runner, which handles logging and short-circuit on empty candidate sets.

## The `generating_model` field

When the dreaming pipeline extracts a memory from a conversation, the model used for extraction is recorded in run metadata but not on the MemoryNode itself. This is a gap. Downstream consumers may want to weight memories differently based on the model that produced them: a memory extracted by a frontier model carries different confidence than one extracted by a smaller, faster model.

The fix is a new `generating_model` column on MemoryNode (String(255), nullable). The extraction pipeline populates it with the model identifier at write time. User-stated memories (created via `write_memory`) leave it null, since no model generated them.

The pipeline consumes this field in two ways. First, the provenance stamp (stage 8) includes `generating_model` in its record, so forensic queries can answer "which model produced the memories that influenced this agent session?" Second, future weight calibration logic can use `generating_model` as a signal, though the initial implementation does not alter weights based on it.

**Schema change:** Alembic migration 029 adds the column. The SDK client exposes it as a read-only field on memory responses. The extraction pipeline in `memoryhub_core` sets it during the dreaming write path.

## File layout

- `memory-hub-mcp/src/tools/_context_pipeline.py` (new): Pipeline runner and individual stage functions.
- `memory-hub-mcp/src/tools/search_memory.py`: Calls the pipeline instead of inline checks.
- `src/memoryhub_core/models/memory.py`: Adds `generating_model` column.
- `src/memoryhub_core/schemas/`: Updates request/response schemas to include `generating_model`.
- `alembic/versions/029_add_generating_model.py`: Migration.
- `sdk/src/memoryhub/`: Exposes `generating_model` on client response types.
- Extraction pipeline module: Sets `generating_model` at memory creation time.

## What this is not

This is a refactoring of existing logic into a composable pipeline, not new access control or new filtering behavior. Every check described above already exists somewhere in the codebase. The value is in making the ordering explicit, testable, and auditable.

The `generating_model` field is additive. It does not change how existing memories behave. Memories written before the migration will have `generating_model = null`, which is the correct value for memories that predate extraction tracking.

## Issues

- #561: Context assembly pipeline
- #566: `generating_model` field on MemoryNode

# Trust Provenance for Extracted Memories

The dreaming pipeline extracts memories from conversations and tags them `source: dreaming`. This is useful for attribution, but it hides a problem: if the conversation contained untrusted content (a tool output from a web scrape, a response from an untrusted MCP server, content from an unauthenticated channel), the extracted memory carries no record of that upstream trust level. The taint is laundered through extraction. The memory looks agent-derived, and the provenance chain is broken.

An extraction pipeline is a transform, not an endorsement. The trust of the output cannot exceed the trust of the input.

## Problem

Consider a conversation where an agent calls a web-scraping tool and gets back a claim: "Library X deprecated function Y in version 3.0." The dreaming pipeline extracts this as a memory with `source: dreaming`. A later agent retrieves this memory and acts on it. Nothing in the memory indicates that the original source was an unverified web page. The agent treats it with the same confidence as a memory the user explicitly stated.

This matters because:

1. **Retrieval consumers cannot distinguish trust levels.** A memory extracted from a user's direct statement and a memory extracted from an untrusted tool output look identical.
2. **The provenance chain breaks at extraction.** The conversation metadata that would indicate "this came from a web scrape" is not carried through to the extracted memory.
3. **Taint propagation is silent.** Mixed conversations (some trusted user input, some untrusted tool output) produce memories with no indication that the source material was mixed.

## Solution

### 1. New field on MemoryNode

Add `upstream_trust_level` to `MemoryNode` with three possible values:

| Value | Meaning |
|-------|---------|
| `trusted` | All source material came from authenticated, trusted channels (direct user input, verified API responses) |
| `untrusted` | At least one source was from an unauthenticated or unverified channel (web scrapes, untrusted MCP servers, unverified tool output) |
| `mixed` | The conversation contained both trusted and untrusted content, and the extraction could not isolate which parts informed this specific memory |

The field is a `StrEnum` in the schema layer. Default for existing rows is `trusted` (backward-compatible; existing memories were created before this distinction existed, and changing their status retroactively would be misleading without evidence).

### 2. Trust determination during extraction

The dreaming extraction pipeline already receives conversation metadata. The extraction step inspects each message's source metadata to determine trust:

- Messages from the authenticated user: `trusted`
- Messages from MCP tools with verified provenance (the MCP server is in the deployment's trust configuration): `trusted`
- Messages from MCP tools without verified provenance: `untrusted`
- Tool outputs from web-fetching tools, browser automation, or similar: `untrusted`
- System messages and assistant responses that reference only trusted inputs: `trusted`

If any message in the extraction window is `untrusted`, the resulting memory is tagged `untrusted` unless the extraction can isolate the memory's content to only trusted sources. If isolation is not possible (the common case for conversations that mix trusted and untrusted content), the memory is tagged `mixed`.

The extraction code in `sdk/src/memoryhub/extraction/` carries the trust level through as a field on the extraction result, and the MCP server persists it on the `MemoryNode`.

### 3. Surface on read models

`upstream_trust_level` is exposed on:

- `MemoryNodeRead` (server-side schema in `src/memoryhub_core/models/schemas.py`)
- `Memory` response model in the SDK (`sdk/src/memoryhub/models.py`)

No filtering or suppression. The field is always present on read responses.

### 4. Taint metadata at read time

When `search_memory` or `read_memory` returns a memory with `upstream_trust_level` of `untrusted` or `mixed`, the response includes taint metadata:

```json
{
  "memory_id": "uuid",
  "content": "Library X deprecated function Y in version 3.0",
  "upstream_trust_level": "untrusted",
  "taint": {
    "tainted": true,
    "sources": ["dreaming"]
  }
}
```

The `sources` array lists the `source` field value of the memory (e.g., `dreaming`, `agent`, `import`). This is advisory. MemoryHub does not enforce behavior based on taint. Consuming agents can use it to adjust confidence, request verification, or surface the taint to the user. The `taint` object is omitted entirely when `upstream_trust_level` is `trusted`, keeping the response lean for the common case.

The taint metadata helper lives in `memory-hub-mcp/src/tools/search_memory.py` and is applied during response assembly.

## Files Touched

| File | Change |
|------|--------|
| `src/memoryhub_core/models/memory.py` | Add `upstream_trust_level` column (String, default `'trusted'`) |
| `src/memoryhub_core/models/schemas.py` | Add `UpstreamTrustLevel` StrEnum, add field to `MemoryNodeRead` |
| `sdk/src/memoryhub/extraction/` | Carry trust level through extraction pipeline |
| `sdk/src/memoryhub/models.py` | Add `upstream_trust_level` and `taint` fields to `Memory` |
| `memory-hub-mcp/src/tools/search_memory.py` | Taint metadata helper, inject into responses |
| Alembic migration 028 | `ALTER TABLE memory_nodes ADD COLUMN upstream_trust_level VARCHAR(10) NOT NULL DEFAULT 'trusted'` |

## Migration

Alembic migration 028 adds the column with a server default of `'trusted'`. This is a non-destructive, backward-compatible change. Existing rows get the default. No data backfill is needed because existing memories were created without trust tracking, and retroactively marking them would require re-examining conversations that are no longer available.

```sql
ALTER TABLE memory_nodes
ADD COLUMN upstream_trust_level VARCHAR(10) NOT NULL DEFAULT 'trusted';
```

The column uses `VARCHAR(10)` rather than a PostgreSQL enum type, consistent with the project's existing pattern for status-like columns (see `scope`, `source` columns).

## Trust Determination Rules

The extraction pipeline applies these rules in order:

1. If the conversation has no tool-call messages, all content is `trusted`.
2. If all tool-call messages come from MCP servers listed in the deployment's trust configuration, all content is `trusted`.
3. If any tool-call message comes from an unlisted MCP server or a web-fetching tool, and the extracted memory's content can be traced entirely to non-tool messages, the memory is `trusted`.
4. If tracing is not possible (step 3 fails), the memory is `mixed` when the conversation has both trusted and untrusted messages, or `untrusted` when all tool messages are untrusted.

Step 3 is best-effort. The extraction pipeline does not have perfect attribution of which conversation turns informed which extracted facts. When in doubt, the pipeline errs toward `mixed` rather than `trusted`. False positives (marking a clean memory as `mixed`) are preferable to false negatives (marking a tainted memory as `trusted`).

## Issues

- #559: Add `upstream_trust_level` field to MemoryNode
- #563: Surface taint metadata on read responses

## Open Questions

- **Trust configuration format.** The "deployment's trust configuration" referenced in the trust determination rules does not exist yet. This could be a ConfigMap listing trusted MCP server identifiers, or it could derive from the auth service's issuer trust list. The simplest starting point is a JSON list of trusted tool names in an environment variable.
- **Granularity of taint.** The current design tags the entire memory. An alternative is per-sentence or per-claim taint tracking, but that adds complexity without a clear consumer. Start with memory-level taint and revisit if agents need finer granularity.
- **Taint propagation across updates.** If a user manually edits a memory that was tagged `untrusted`, should the trust level change to `trusted`? The user is presumably verifying the content by editing it. This needs a policy decision.

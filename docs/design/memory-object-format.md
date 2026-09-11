# Memory Object Format (MOF)

## Summary

MemoryHub stores memories in a proprietary schema optimized for retrieval, governance, and graph operations. There is no standard way to export memories for use by other systems, migrate between MemoryHub deployments, or back up memory stores in a human-readable format. As agent memory systems proliferate, portability becomes a differentiator. This document explores what a portable export format could look like.

---

## Problem

Three concrete scenarios motivate a portable format:

1. **Cross-system migration.** A team moves from one memory-aware platform to another. Without a portable format, memories are locked to the source system's schema and API.
2. **Deployment-to-deployment transfer.** An organization runs multiple MemoryHub instances (dev, staging, prod, or regional shards). Transferring memories between them currently requires direct database operations.
3. **Human-readable backup.** Compliance and debugging both benefit from exports that a person can read without tooling. JSON dumps of internal tables do not meet this bar.

A portable format also positions MemoryHub to participate in any future interoperability standards rather than retrofitting compatibility after the fact.

---

## Proposal: Two Output Formats

MOF defines a single logical schema with two serializations:

**MOF Markdown** (YAML frontmatter + content body): Optimized for file-based workflows, coding agents that consume markdown, and human review. Each memory is one `.md` file.

```markdown
---
id: "550e8400-e29b-41d4-a716-446655440000"
logical_id: "python-version-preference"
scope: "user"
scope_qualifier: "wjackson"
owner: "wjackson"
origin_type: "user-stated"
memory_type: "preference"
weight: 0.9
tags: ["python", "tooling"]
version: 3
status: "active"
created_at: "2026-08-15T14:30:00Z"
confidence: 0.95
actor_id: "claude-code-session-42"
---

Always use Python 3.12+ for new projects. Pin dependencies with uv.
```

**MOF JSON**: Same fields, optimized for API-based interop and bulk pipelines. Content becomes a top-level `content` key rather than a document body. A bundle is an array of these objects.

---

## Field Mapping: MemoryNode to MOF

| MOF field | MemoryHub field | Notes |
|---|---|---|
| `id` | `id` | Direct mapping |
| `logical_id` | `logical_id` | Direct mapping |
| `content` | `content` | Direct mapping |
| `scope` | `scope` | Vocabulary mapping needed (see below) |
| `scope_qualifier` | `scope_id` | Direct mapping |
| `owner` | `owner_id` | Direct mapping |
| `origin_type` | `source` | Vocabulary mapping: `agent` to `agent-inferred`, `dreaming` to `system-generated`, `import` to `imported`, others to `user-stated` |
| `created_at` | `created_at` | Direct mapping |
| `memory_type` | `content_type` | Vocabulary mapping: internal types to a portable set (`fact`, `preference`, `decision`, `procedure`, `context`) |
| `weight` | `weight` | Direct mapping |
| `tags` | `domains` | Direct mapping |
| `version` | `version` | Direct mapping |
| `status` | `status` | Vocabulary mapping: internal status values to `active`, `archived`, `superseded`, `expired` |
| `expires_at` | `expires_at` | Direct mapping |
| `relevant_until` | `relevant_until` | Direct mapping |
| `confidence` | `metadata` | Extracted from the metadata JSON blob |
| `actor_id` | `actor_id` | Direct mapping |
| `driver_id` | `driver_id` | Direct mapping |

The vocabulary mappings are intentionally lossy in one direction. Internal schema values carry MemoryHub-specific semantics; MOF values are generic enough that other systems can interpret them without knowledge of MemoryHub internals. Import back into MemoryHub would reverse-map using a configurable vocabulary table.

---

## Exchange Bundles

A bundle is the unit of export and import. It contains a manifest and an array of MOF objects.

**Manifest fields:**

| Field | Purpose |
|---|---|
| `source_system` | Identifier of the exporting system (e.g., `memoryhub/v2.4.0`) |
| `export_time` | ISO 8601 timestamp |
| `schema_version` | MOF schema version (e.g., `1.0.0`) |
| `memory_count` | Number of MOF objects in the bundle |
| `scope_filter` | What scope(s) were included in this export |
| `checksum` | SHA-256 of the concatenated MOF objects, for integrity verification |

**Conflict resolution on import:** When a MOF object's `logical_id` matches an existing memory, the importer applies one of three strategies (caller-selected):

- **Skip**: Keep the existing memory, discard the import.
- **Overwrite**: Replace the existing memory with the imported version.
- **Merge-by-timestamp**: Keep whichever version has the later `created_at`. If equal, keep the existing memory.

For the markdown serialization, a bundle is a directory: `manifest.yaml` at the root, one `.md` file per memory. For JSON, a bundle is a single file with the manifest as a top-level key and the memories as an array.

---

## Open Questions

**Embeddings.** Should MOF include embedding vectors? They are large (1536+ floats per memory), model-specific, and not portable between systems using different embedding models. Leaning toward excluding them and letting the importing system re-embed.

**Relationships and graph edges.** MemoryHub's memory tree (parent/child, branches, rationale links) is a key differentiator. Should MOF represent graph structure? Options: a separate `relationships` array in the bundle, `parent_id`/`branch_type` fields on each MOF object, or omit graph structure entirely and treat MOF as a flat export. Graph structure adds significant complexity for importers that do not support it.

**S3-backed content.** Memories whose content exceeds the inline threshold are stored in MinIO with a reference in the database. For export, should MOF inline the full content (potentially large) or include an S3 reference that only works within the source deployment? Inlining is more portable but produces larger bundles. A hybrid approach (inline up to N bytes, external reference with a fetch URL above that) adds complexity.

**Tenant isolation in bundles.** Should a bundle be scoped to a single tenant, or can it span tenants? Single-tenant is simpler and avoids cross-tenant data leakage risks. Multi-tenant bundles would serve platform migration use cases but require careful access control on both export and import.

---

## Status

Design ideation only. No implementation is planned until we have concrete demand from cross-system migration, multi-deployment transfer, or alignment with an emerging portability standard. The field mapping and vocabulary translations are the load-bearing decisions; the serialization format is straightforward once those are settled.

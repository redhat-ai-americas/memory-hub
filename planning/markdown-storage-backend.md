# Markdown Storage Backend (Personal Edition)

Status: design exploration, not scheduled for implementation.

## Summary

An alternative storage backend for the personal edition that stores memories as markdown files with YAML frontmatter instead of SQLite rows. The primary value proposition is git-trackability and human editability. A sidecar SQLite index provides the search infrastructure (FTS5, embeddings, graph traversal) that flat files cannot.

## The format

Each memory is a single file. The frontmatter carries the structured fields; the markdown body carries the content.

```markdown
---
id: 7a3b1c2d-4e5f-6789-abcd-ef0123456789
logical_id: 7a3b1c2d-4e5f-6789-abcd-ef0123456789
version: 1
scope: user
weight: 0.85
content_type: behavioral
domains: [authentication, OpenShift]
owner_id: wjackson
source: agent
created_at: 2026-09-10T14:32:00Z
updated_at: 2026-09-10T14:32:00Z
---

When deploying to OpenShift, always use `--platform linux/amd64` for container
builds on Mac to avoid architecture mismatches. The cluster nodes are x86_64.
```

### File layout

```
~/.local/share/memoryhub/memories/
├── 7a3b1c2d.md                    # current version (named by logical_id prefix)
├── 8b4c2d3e.md
├── .versions/
│   ├── 7a3b1c2d/
│   │   ├── v1.md                  # previous versions
│   │   └── v2.md
│   └── 8b4c2d3e/
│       └── v1.md
├── .relationships/
│   └── relationships.yaml         # graph edges
└── .memoryhub/
    └── index.sqlite               # sidecar search index (derived, not source of truth)
```

The 8-character prefix of `logical_id` is the filename. Collisions (expected around 65K files at birthday-paradox odds) fall back to the full UUID. Current versions live at the top level; previous versions are archived under `.versions/{prefix}/v{n}.md`. The `.versions/` and `.memoryhub/` directories are gitignored in most workflows (version history is captured by git itself).

### Fields omitted from frontmatter

These fields exist in the SQLite schema but do not appear in the frontmatter:

- `embedding` -- 384 floats serialized as JSON is ~3KB of noise in every file. Stored only in the sidecar index.
- `stub` -- derived from the first 200 characters of content. Regenerated on index rebuild.
- `content_hash` -- derived from content via SHA-256. Recomputed on index rebuild.
- `tenant_id` -- always "local" in the personal edition.
- `status` -- deletion is represented by moving the file to `.versions/` (or `git rm`), not by a flag.
- `deleted_at` -- same as above.

### Relationships file

Graph edges are stored in a single YAML file rather than per-memory, since edges reference two memories and don't belong to either:

```yaml
- id: rel-001
  source_id: 7a3b1c2d
  target_id: 8b4c2d3e
  type: related_to
  created_at: 2026-09-10T14:35:00Z
  created_by: wjackson
```

The sidecar index parses this into a table for recursive-CTE graph traversal.

## The sidecar index

A SQLite database at `.memoryhub/index.sqlite` that is entirely derived from the markdown files. It can be deleted and rebuilt from scratch without data loss. It contains:

1. **A metadata table** mirroring every frontmatter field, plus the computed `stub`, `content_hash`, and `is_current` flag. This is the query surface for ORM-style filters.
2. **An embeddings table** storing the 384-dim vector as a JSON blob, keyed by memory ID.
3. **An FTS5 virtual table** over stub and content, identical to the current SQLiteBackend's `memory_nodes_fts`.
4. **A relationships table** parsed from `.relationships/relationships.yaml`.

### Startup: cold rebuild

On startup, the backend checks whether the index exists and whether its file-count matches the memory directory. If the index is missing or stale, it does a full rebuild:

1. Scan the memory directory for `*.md` files.
2. Parse each file's YAML frontmatter and markdown body.
3. Insert metadata into the metadata table.
4. Generate embeddings via the ONNX service and insert into the embeddings table.
5. Insert stub + content into the FTS5 table.
6. Parse the relationships file and insert edges.

Step 4 (embedding generation) is the bottleneck. The ONNX model runs locally at roughly 50-100 embeddings/second on a modern laptop CPU. A 1,000-memory rebuild takes 10-20 seconds; a 5,000-memory rebuild takes 50-100 seconds.

### Incremental updates

On writes, the backend:
1. Writes the markdown file to disk (atomic via write-to-temp + rename).
2. Updates the sidecar index in a single transaction (metadata, embedding, FTS5 entry).

This keeps the sidecar in sync without a full rebuild. If the sidecar falls out of sync (crash during write, external file edits), the next startup rebuild corrects it.

### Detecting external edits

When the user edits a memory file in their text editor or via git, the sidecar is stale. Options for detecting this:

- **Startup hash check**: compute content hashes on startup, compare to sidecar. Re-embed only changed files. Cost: O(n) file reads, but embedding is only for changed files.
- **Filesystem watch**: `watchdog` or `inotify` for real-time sync. Adds a background thread and a dependency.
- **Manual rebuild command**: `memoryhub rebuild-index`. Simplest, least magic.

The startup hash check is the right default. It's automatic, deterministic, and the cost is dominated by file I/O (fast) rather than embedding (slow, but only for changes).

## RecallBackend implementation

A `MarkdownBackend` class implementing the four-method `RecallBackend` protocol. The implementation is nearly identical to `SQLiteBackend` -- the difference is that it queries the sidecar index instead of the primary database, and writes go to markdown files before updating the sidecar.

```
RecallBackend protocol (memoryhub-local/src/memoryhub_local/storage/recall.py)
    ├── SQLiteBackend   -- queries primary SQLite DB directly
    ├── PostgresBackend -- queries PostgreSQL via pgvector + tsvector
    └── MarkdownBackend -- queries sidecar index; source of truth is the filesystem
```

The service layer (`services/memory.py`) does not change. It calls the backend protocol for recall operations and uses portable SQLAlchemy ORM for CRUD. The CRUD path would need a thin adapter: instead of inserting an ORM object into the primary database, it serializes to a markdown file and updates the sidecar. This adapter sits between the service layer and the storage layer, not inside the RecallBackend protocol (which is recall-only).

## What changes vs. what stays the same

| Component | Changes? | Notes |
|-----------|----------|-------|
| RecallBackend protocol | No | Four methods, same signatures |
| Recall implementation | New class | `MarkdownBackend`, queries sidecar |
| CRUD (create/update/delete) | New adapter | Serialize to/from markdown files |
| Service layer | No | Uses ORM + RecallBackend protocol |
| Embedding service | No | Same ONNX model, same vectors |
| Extraction/dreaming pipeline | No | Produces memories; storage format is transparent |
| MCP tool surface | No | Same tools, same parameters |

## Scale hypothesis

The question: at what memory count does this backend stop being a reasonable choice?

### Per-component scaling

**File I/O (startup scan)**

Scanning a directory and reading file headers. On APFS/ext4 with warm filesystem cache, `os.scandir()` + frontmatter parse runs at roughly 5,000-10,000 files/second. Cold cache (first boot, or after git clone) is 2-5x slower due to inode reads.

| Memory count | Warm scan time | Cold scan time |
|--------------|---------------|----------------|
| 500 | <0.1s | ~0.2s |
| 2,000 | ~0.3s | ~0.8s |
| 5,000 | ~0.7s | ~2s |
| 10,000 | ~1.5s | ~4s |
| 50,000 | ~8s | ~20s |

**Embedding generation (full rebuild)**

The ONNX Granite model processes ~50-100 texts/second on CPU (batch size 16, 384-dim output). Full rebuild requires embedding every memory. Incremental rebuild (startup hash check) only re-embeds changed files.

| Memory count | Full rebuild | Incremental (10 changed) |
|--------------|-------------|--------------------------|
| 500 | 5-10s | <1s |
| 2,000 | 20-40s | <1s |
| 5,000 | 50-100s | <1s |
| 10,000 | 100-200s | <1s |

Full rebuild is a one-time cost (first boot after index deletion). Normal operation uses incremental updates. The pain point is the first startup after cloning a large memory repository.

**Brute-force cosine (per query)**

Loading all embeddings into memory and computing cosine distance. Each embedding is 384 floats = ~3KB. The distance computation is pure Python (no numpy in the current personal edition).

| Memory count | Memory footprint | Query latency (Python) | Query latency (numpy) |
|--------------|-----------------|----------------------|---------------------|
| 500 | ~1.5 MB | ~5ms | <1ms |
| 2,000 | ~6 MB | ~20ms | ~2ms |
| 5,000 | ~15 MB | ~50ms | ~5ms |
| 10,000 | ~30 MB | ~100ms | ~10ms |
| 50,000 | ~150 MB | ~500ms | ~50ms |

The current SQLiteBackend has the same brute-force cost. The markdown backend does not make this worse or better. At 10K+ memories, numpy (or sqlite-vec for ANN) becomes worthwhile regardless of storage format.

**FTS5 (per query)**

FTS5 query performance is sublinear in corpus size. Rebuilding the FTS5 table on full rebuild is the costly operation.

| Memory count | FTS5 rebuild | Query latency |
|--------------|-------------|---------------|
| 500 | <0.5s | <1ms |
| 2,000 | ~1s | <1ms |
| 5,000 | ~3s | ~1ms |
| 10,000 | ~6s | ~2ms |
| 50,000 | ~30s | ~5ms |

**Git performance**

`git status` and `git add` scan the working tree. Performance degrades with file count, especially on macOS where APFS metadata operations are slower than ext4.

| Memory count | `git status` | Repo size (content only) |
|--------------|-------------|--------------------------|
| 500 | instant | ~1 MB |
| 2,000 | ~0.5s | ~4 MB |
| 5,000 | ~1s | ~10 MB |
| 10,000 | ~2s | ~20 MB |
| 50,000 | ~8s | ~100 MB |

Git handles 50K small files, but the developer experience degrades noticeably above 10K. Worktrees, sparse checkout, or directory sharding (e.g., `memories/7a/3b1c2d.md`) can push this higher.

### The scale wall

The backend hits three walls at different points:

**Wall 1 (~5,000 memories): cold-start rebuild becomes painful.** A full index rebuild takes 50-100 seconds, dominated by embedding generation. This matters after cloning the repo or deleting the index. Normal incremental operation is fine. Mitigation: commit the sidecar index alongside the memories (trades git cleanliness for startup speed), or ship pre-computed embeddings in frontmatter (trades file readability for rebuild speed).

**Wall 2 (~10,000 memories): brute-force cosine becomes the query bottleneck.** At 100ms per query in pure Python, interactive search feels sluggish. This wall exists for the SQLiteBackend too. Mitigation: switch to numpy vectorized distance (10x speedup) or sqlite-vec for ANN search. Both are storage-format-independent.

**Wall 3 (~10,000-50,000 memories): the markdown files stop being useful as a human interface.** No one browses 10,000 markdown files in an editor. Git diffs become noisy. The sidecar index is doing all the real work, and the files are a serialization format that adds consistency overhead without a corresponding usability benefit. At this scale, the SQLite backend is strictly better: simpler, faster, and the "human-readable storage" advantage has evaporated.

### Recommendation

The markdown backend is a good fit for users who:
- Have fewer than ~5,000 memories (with the expectation that most personal-edition users will be well below this for years)
- Want to browse, edit, or version-control their memories using standard file tools
- Value portability (copy a directory, sync via git, grep with standard tools)
- Accept a ~10-20 second first-boot penalty for index rebuilding

It is not a replacement for the SQLite backend. It is an alternative for a specific user profile. The SQLite backend should remain the default.

## Open questions

1. **Should the sidecar index be committed to git?** Pro: eliminates cold-start rebuild cost. Con: binary file in git, merge conflicts, repo bloat. Leaning toward no -- the sidecar is derived data and should be gitignored.

2. **Should embeddings be stored in frontmatter?** Pro: eliminates the need for the ONNX model on rebuild (portability). Con: ~3KB of float array per file destroys readability, the core value proposition. Leaning toward no.

3. **Directory sharding.** Flat directory with 5,000+ files degrades `ls` and filesystem performance. Sharding by first two hex chars of logical_id (`memories/7a/3b1c2d.md`) scales to ~65K memories with at most ~256 files per subdirectory. Worth implementing from the start or waiting until someone hits the wall?

4. **Version storage.** Git already tracks file history. Is the `.versions/` directory redundant? It serves the `get_memory_history()` API without requiring git access, but it doubles the file count. An alternative: rely on git for version history and implement `get_memory_history()` via `git log -p -- {filepath}`.

## Related

- [Retrieval pipeline](../docs/design/retrieval-pipeline.md) -- the five-signal hybrid pipeline this backend plugs into
- [RecallBackend protocol](../memoryhub-local/src/memoryhub_local/storage/recall.py) -- the four-method interface a backend must implement
- [SQLiteBackend](../memoryhub-local/src/memoryhub_local/storage/sqlite.py) -- reference implementation
- [Two-vector retrieval](../docs/design/two-vector-retrieval.md) -- focus-vector design and RRF fusion

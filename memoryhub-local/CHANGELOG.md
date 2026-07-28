# Changelog -- memoryhub-local

All notable changes to the `memoryhub-local` package.

## [0.1.0] -- 2026-07-28

Initial release. Personal edition of MemoryHub -- agent memory without infrastructure.

- SQLite backend with WAL mode, brute-force KNN via sqlite-vec, FTS5
- RecallBackend protocol with SQLiteBackend and PostgresBackend implementations
- FastMCP server (stdio) with 4 tools: register_session, memory, thread, admin_memory
- ONNX embeddings (Granite Embedding Small English R2, 384 dim, CPU-only)
- Extraction pipeline with MCP sampling and windowed processing
- On-connect dreaming (automatic extraction on session start)
- Alembic migrations with batch-mode SQLite support
- Versioned memory with full history
- Graph relationships (relate, relationships, similar)
- Contradiction detection (report action)
- Thread operations (create, append, get, list, archive, delete, extract)
- Admin moderation (quarantine, restore, hard_delete)

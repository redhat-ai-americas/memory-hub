# Next Session Plan

## Completed this session
- #119: Translated upstream embedder errors into structured tool responses.
  Added EmbeddingServiceError/EmbeddingContentTooLargeError/EmbeddingServiceUnavailableError
  domain exceptions; wrapped httpx errors in HttpEmbeddingService; added ToolError
  catches in write_memory, update_memory, search_memory, set_session_focus.
  9 tests (5 service-layer, 4 tool-layer).
- #84: Decoupled chunking from S3 availability. Split is_oversized into
  needs_chunking + use_s3 so embedding truncation and chunk creation fire
  for all oversized content regardless of MinIO configuration. 5 tests.
- #84 (deploy): Deployed MinIO to memory-hub-mcp namespace. Added S3 env
  vars to MCP server deployment manifest. Verified end-to-end: write with
  storage_type="s3" + chunks + hydrated read + delete.
- #102: Confirmed already fixed by #63 (bidirectional BFF walker). Can be closed.

## Priority items for next session: Design docs
Review and flesh out the 6 design docs tagged `needs-design`:
#171 (knowledge compilation), #170 (graph-enhanced retrieval),
#169 (context compaction / ACE), #168 (conversation thread persistence),
#166 (projects table governance), #109 (UI design doc).

## Context
- SDK v0.6.0 on PyPI (v0.6.1 unreleased: project_id field in ProjectConfig)
- CLI v0.3.0 (unreleased: --project/--non-interactive flags)
- MCP server v0.5.1, build #27, 14 tools deployed
- MinIO deployed to memory-hub-mcp namespace (single-instance, dev credentials)
- Curation thresholds: exact_duplicate 0.98, near_duplicate gate 0.90,
  flag 0.80
- min_appendix=5 (was 1)

## Cluster state
- Cluster: sandbox5167
- Granite 3.3 8B: granite-model namespace, vLLM
- MCP server: memory-hub-mcp namespace
- MinIO: memory-hub-mcp namespace (co-located with MCP server)
- DB: memoryhub-db namespace, migrations through 012 in sync

# Next Session Plan

## Completed this session (2026-04-23)

### MCP single-tool action-dispatch (#201) — CLOSED
- Design doc: `planning/mcp-single-tool-schema.md`
- Decision: 1 dispatched `memory()` tool + `register_session` = 2 tools (compact profile)
- 19 actions (8 read, 11 write), hybrid param layout (6 top-level + options dict)
- Token savings: ~85% reduction (~1,050 tokens from ~6,800)
- `create_project` consistency fix: accepts `project_id` matching other project actions

### Compacted tool implementation (#202) — CLOSED
- `memory-hub-mcp/src/tools/memory.py`: dispatcher with 19 action handlers
- Delegates to existing tool functions — zero business logic duplication
- 47 tests covering action validation, param forwarding, routing, options isolation
- Exercise-tools: 4/5 ergonomics score, two subjective items discussed and resolved

### Tiered tool profiles (#201/#202)
- `MEMORYHUB_TOOL_PROFILE` env var with three profiles:
  - `compact` (default): register_session + memory (2 tools) — frontier models
  - `full`: register_session + 9 flat-param tools (10 tools) — mid-range models
  - `minimal`: register_session + search/write/read (4 tools) — small models
- Profile-specific FastMCP instructions
- 19 profile tests, deploy script for minimal instance
- Updated main deploy.sh preflight to handle profile-based tool registration

### Granite 8B testing
- Deployed minimal-profile instance alongside primary (memory-hub-mcp-minimal)
- Granite successfully called register_session via MCP tools on first turn
- Context overflow on second turn: search_memory docstring (~2K tokens) + tool round-trip exceeded 16K
- Pivoted to fipsagents framework memory connector (self.memory): zero tool tokens, memories injected as prefix
- Framework connector works: SDK authenticates, retrieves memories, injects ~2K token prefix
- Grounding gap: Granite 8B doesn't reliably use prefix memories as constraints — gives generic answers instead. This is a model instruction-following limitation, not a MemoryHub issue.

### Key architectural insight
Two distinct integration surfaces serve different purposes:
- **Framework connector** (`self.memory`): put/get primitives for ALL models, zero tool tokens
- **MCP tools**: governance/power-user surface (graph ops, curation, projects) for capable models
- Small models should use framework connector only; advanced MCP tools are loaded on demand via skills

## Priority items for next session

### 1. Publish SDK v0.6.0 to PyPI (#205)
Quick release — the code fix (stub result parsing) is already in the repo. SDK v0.5.1 on PyPI can't parse search results that include stubs, causing silent memory loss for agents using the framework connector.

### 2. Kagenti demo prep
Demo memory-hub to the primary kagenti maintainer. Existing deployment is untouched (compact profile not yet active on primary — still running pre-profile code with all 10 tools). The minimal-profile instance runs alongside it.

### 3. Document tiered integration model (#206)
Update `docs/agent-integration-guide.md` with the three-tier model (framework connector / compact MCP / full MCP), profile configuration, and guidance on which path to use per model tier.

### 4. Improve small-model memory grounding
The framework connector delivers memories but Granite 8B ignores them. Options:
- RAG-style extraction: summarize relevant memories into a direct answer prefix
- Structured prefix: format memories as explicit Q&A pairs instead of raw content
- Fine-tuning: train on grounding tasks (longer term)
This is an agent-design problem — file in fipsagents, not memory-hub.

### 5. Upstream: fipsagents empty-query fix
`build_memory_prefix()` default calls `search("")` which MemoryHub rejects. File upstream issue to use a non-empty default query or handle empty-query errors.

### 6. Stretch: skill wrappers evaluation (#203)
Low priority. Only relevant after the integration guide update. Assess whether Claude Code skills reduce context weight for infrequent governance operations.

## Context
- SDK v0.6.0 in repo, v0.5.1 on PyPI (needs release)
- CLI v0.5.0 (--output flag, JSON envelope, exit codes)
- MCP server: 10 tools on primary (pre-profile), 4 tools on minimal instance
- memory() dispatcher implemented but not yet active on primary deployment
- Alembic migrations through 014 applied
- 376+ MCP tests passing (47 dispatcher + 19 profile + 310 existing)
- Tracking issue: #198 (3 of 5 sub-issues closed: #199, #200, #201; #202 also closed)
- New issues: #205 (SDK release), #206 (integration guide)
- Uncommitted research files on main — don't disturb them

## Cluster state
- Cluster: **mcp-rhoai** context
- MCP server primary: memory-hub-mcp namespace (v0.8.0, 10 tools, untouched)
- MCP server minimal: memory-hub-mcp namespace (memory-hub-mcp-minimal, 4 tools, new)
- Granite 8B: granite-model namespace (RedHatAI/granite-3.3-8b-instruct)
- DB: memoryhub-db namespace, migrations through 014
- Auth: memoryhub-auth namespace
- UI: memoryhub-ui namespace
- MinIO + Valkey: memory-hub-mcp namespace
- Granite test agent: ~/Developer/AGENTS/memoryhub-granite-test (local, not deployed)

# Next Session Plan

## Completed this session (2026-04-24)

### Granite 8B agent — memory grounding solved
- `<user_memories>` tag in the user message is the winning pattern for Granite 8B
- System prompt injection (all formats tried: narrative, structured rules, XML tags, developer role) does NOT work — Granite ignores system prompt constraints
- User-turn injection works perfectly: Podman, UBI, FIPS all grounded from memories
- `astep_stream` override is the correct fipsagents injection point (server replaces messages per-request, so `step()` and `build_memory_prefix()` don't work in server mode)
- Temperature 0.3, max_tokens 512, weight >= 0.85 filter with top-5 limit
- Agent at `~/Developer/AGENTS/memoryhub-granite-test`, committed and working locally

### Upstream issues resolved
- #205 SDK v0.6.0 (stub parsing) — closed, published to PyPI
- #206 Tiered integration docs — closed
- fips-agents/agent-template#83 (empty query) — closed, fix committed upstream
- fips-agents patch check doesn't work on agent projects (find_project_root looks for fastmcp dep, not fipsagents) — known limitation

### Key learnings for small-model memory integration
1. **Placement > formatting**: User-turn `<user_memories>` > system prompt > developer message
2. **Temperature matters**: 0.3 works; 0.7 makes small models ignore constraints
3. **Truncate aggressively**: First-sentence truncation of long memories keeps block compact
4. **Framework connector > MCP tools**: Zero tool tokens vs ~4K for even the minimal profile
5. **SDK max_results not forwarded**: `memory.search(query, max_results=5)` returns all results; client-side slicing needed. File as SDK issue.

## Priority items for next session

### 1. Deploy Granite agent with gateway to cluster
The agent works locally. Deploy to mcp-rhoai:
- `fips-agents create gateway memoryhub-granite-gateway --local`
- Configure gateway BACKEND_URL → agent service
- Deploy both via Helm
- Test via gateway route
- Demo alongside the primary MCP server

### 2. Kagenti demo
Demo memory-hub to kagenti primary maintainer. Demo points:
- Memory tree with branches (rationale, provenance)
- Scope-based governance
- Tiered integration: framework connector (Granite) vs MCP tools (Claude)
- Live Granite agent grounding on memories

### 3. SDK max_results forwarding bug
`MemoryHubClient.search(query, max_results=5)` returns all 72 results instead of 5. The kwarg isn't being passed through to the MCP tool call. File and fix.

### 4. Upstream: user_memories pattern for fipsagents
The `<user_memories>` injection pattern should be available to all fipsagents agents, not just our custom override. Consider:
- Adding a `memory_injection` config option to agent.yaml (prefix vs user_turn)
- For user_turn mode, the framework injects `<user_memories>` into the user message automatically via astep_stream
- This is the framework-level fix for the small-model grounding gap

### 5. Stretch: compact profile for Claude Code
Test the compact profile (2 tools: register_session + memory dispatcher) as the primary MCP server for Claude Code. Measure actual token savings. Update `.claude/rules/memoryhub-integration.md`.

## Context
- SDK v0.6.0 published to PyPI
- CLI v0.5.0
- MCP server: 10 tools on primary (pre-profile), 4 tools on minimal instance
- memory() dispatcher implemented but not active on primary deployment
- Alembic migrations through 014
- 376+ MCP tests passing
- Tracking issue: #198 (4 of 5 closed)
- Granite test agent: ~/Developer/AGENTS/memoryhub-granite-test (working locally)

## Cluster state
- Cluster: **mcp-rhoai** context
- MCP server primary: memory-hub-mcp namespace (v0.8.0, 10 tools, untouched)
- MCP server minimal: memory-hub-mcp namespace (memory-hub-mcp-minimal, 4 tools)
- Granite 8B: granite-model namespace (RedHatAI/granite-3.3-8b-instruct)
- DB: memoryhub-db namespace, migrations through 014
- Auth: memoryhub-auth namespace
- UI: memoryhub-ui namespace
- MinIO + Valkey: memory-hub-mcp namespace

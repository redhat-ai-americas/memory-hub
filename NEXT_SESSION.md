# Next Session Plan

## Completed since last session

### Issues closed
- #201 — MCP single-tool action-dispatch design (planning/mcp-single-tool-schema.md)
- #202 — Compacted memory() tool implementation (19 actions, tiered profiles)
- #205 — SDK v0.6.0 stub result parsing fix
- #206 — Tiered tool profiles and framework connector documentation
- fips-agents/agent-template#83 — build_memory_prefix() empty-query fix (upstream)

### Implementation shipped
- `memory()` dispatcher: 19 actions, hybrid param layout, 47 tests
- Tiered tool profiles: compact/full/minimal via MEMORYHUB_TOOL_PROFILE env var
- Minimal-profile MCP instance deployed (memory-hub-mcp-minimal, 4 tools)
- Granite 8B test agent scaffolded at ~/Developer/AGENTS/memoryhub-granite-test

### Key findings
- Framework memory connector (fipsagents `self.memory`) is the right integration for small models: zero tool tokens, ~2K token prefix
- Granite 8B can call MCP tools (register_session worked) but context overflows on multi-turn tool calling
- Granite 8B doesn't reliably ground answers in prefix-injected memories — gives generic answers instead of using stored preferences

## Priority items for next session

### 1. Finish Granite test agent — fix grounding gap

The agent scaffolding is done. The blocking issue is that Granite ignores memory-prefix content. The agent at `~/Developer/AGENTS/memoryhub-granite-test` has:
- Framework connector wired (`.memoryhub.yaml` → SDK → MCP server)
- Custom `build_memory_prefix()` override (fipsagents default still calls `search("")`)
- SDK v0.6.0 installed (stub parsing works)
- Template artifacts cleaned (no code_executor/web_search/citation_required)
- System prompt simplified, grounding instruction in prefix header

What to try next:
- **RAG-style injection**: Instead of dumping raw memories, have the agent code summarize relevant memories into a direct "Based on your stored preferences..." preamble that the model treats as facts, not suggestions.
- **Structured prefix**: Format memories as explicit constraint blocks: `REQUIREMENT: Use Podman, not Docker` rather than free-text paragraphs.
- **Prompt engineering**: Test whether Granite responds better to memories framed as `[USER RULE]` or `[POLICY]` tags vs narrative text.
- **Smaller prefix**: Limit to top-3 most relevant memories instead of 10. Less context = more attention per memory for a small model.

Once grounding works, run a proper exercise session:
1. Start agent locally: `cd ~/Developer/AGENTS/memoryhub-granite-test && OPENAI_API_KEY=not-required make run-local`
2. Test via curl: `curl localhost:8080/v1/chat/completions -d '{"model":"test","messages":[{"role":"user","content":"What container runtime should I use?"}]}'`
3. Verify response references Podman/UBI (from memories), not generic Docker/Alpine advice
4. Test memory write: ask agent to remember something, verify it persists

### 2. Deploy agent with gateway to cluster

Once the agent works locally, deploy to mcp-rhoai:
- `fips-agents create gateway memoryhub-granite-gateway --local` (if not already done)
- Configure gateway BACKEND_URL to point at the agent service
- Deploy both via Helm to the cluster
- Test via gateway route

### 3. Kagenti demo prep

Demo to kagenti primary maintainer. The primary MCP deployment is untouched (pre-profile, 10 tools). Key demo points:
- Memory tree with branches (rationale, provenance)
- Scope-based governance (user/project/organizational/enterprise)
- Tiered integration: framework connector vs MCP tools
- The "remember this" / "what do I need to know" agent experience

### 4. Stretch: evaluate compact profile for Claude Code

The compact profile (2 tools: register_session + memory dispatcher) hasn't been tested as the primary MCP server configuration yet. Before switching the primary deployment:
- Test locally with cmcp to verify all 19 actions work end-to-end
- Measure actual token savings vs the current 10-tool deployment
- Update `.claude/rules/memoryhub-integration.md` for memory() usage patterns
- Consider: should Claude Code use compact profile (action dispatch) or stay on full profile (flat params)?

## Context
- SDK v0.6.0 in repo and installed locally in test agent (check if published to PyPI)
- CLI v0.5.0
- MCP server: 10 tools on primary (pre-profile code), 4 tools on minimal instance
- memory() dispatcher implemented but not active on primary deployment
- Alembic migrations through 014
- 376+ MCP tests passing
- Tracking issue: #198 (4 of 5 closed: #199, #200, #201, #202)
- Uncommitted research files on main — don't disturb them

## Cluster state
- Cluster: **mcp-rhoai** context
- MCP server primary: memory-hub-mcp namespace (v0.8.0, 10 tools, untouched)
- MCP server minimal: memory-hub-mcp namespace (memory-hub-mcp-minimal, 4 tools)
- Granite 8B: granite-model namespace (RedHatAI/granite-3.3-8b-instruct)
- DB: memoryhub-db namespace, migrations through 014
- Auth: memoryhub-auth namespace
- UI: memoryhub-ui namespace
- MinIO + Valkey: memory-hub-mcp namespace
- Granite test agent: ~/Developer/AGENTS/memoryhub-granite-test (local only, framework connector, no MCP tools)

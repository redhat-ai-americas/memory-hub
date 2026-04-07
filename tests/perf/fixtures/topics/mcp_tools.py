"""MCP-tools-topic synthetic memories.

50 memories about FastMCP server design, tool decorators, response shapes,
testing patterns, and the fips-agents scaffold workflow.
"""

FOCUS_STRING = (
    "FastMCP tool design, MCP server tool implementation, tool annotations, "
    "tool decorators, fips-agents scaffold, MCP response shapes, and tool testing"
)

MEMORIES = [
    {
        "content": "MCP servers use FastMCP v3 with streamable-http transport, never SSE. SSE is deprecated and FastMCP 2 patterns don't work with v3's tool registration.",
        "weight": 0.9,
    },
    {
        "content": "memory-hub-mcp does NOT use the dynamic tool loader. src/main.py statically imports each tool module and calls mcp.add_tool() explicitly because v2's UnifiedMCPServer.load_all skips tools in v3.",
        "weight": 0.95,
    },
    {
        "content": "When you add a new MCP tool, you MUST add 'from src.tools.<name> import <name>' to main.py and add it to the mcp.add_tool list. Otherwise the tool deploys but list_tools silently omits it.",
        "weight": 0.95,
    },
    {
        "content": "Always use the src. prefix for imports inside memory-hub-mcp. 'from src.core.app import mcp' is correct; 'from core.app import mcp' creates a dual FastMCP instance and breaks tool registration.",
        "weight": 0.9,
    },
    {
        "content": "Test FastMCP decorated functions via the .fn attribute: 'my_tool.fn(...)'. The decorator wraps the function in a tool object that pytest can't call directly.",
        "weight": 0.9,
    },
    {
        "content": "Always use the fips-agents scaffold workflow when adding MCP tools, even in main conversation context. Scaffolds give Google-style docstrings, test files, and proper annotation defaults.",
        "weight": 0.9,
    },
    {
        "content": "MCP tool annotations: readOnlyHint=true for search/read tools, idempotentHint=true when the operation is safe to retry, openWorldHint=false when the tool only touches the local data store.",
        "weight": 0.85,
    },
    {
        "content": "Tool parameter descriptions are read by the LLM. Be specific: 'natural language search query' is better than 'query'. Include examples of good vs bad inputs in the description.",
        "weight": 0.85,
    },
    {
        "content": "Use Pydantic Field with Annotated for tool parameter validation: Annotated[int, Field(ge=1, le=50)]. The Field constraints surface as JSON schema in the tool registration.",
        "weight": 0.85,
    },
    {
        "content": "Tool responses should include enough context for the agent to make a decision without follow-up calls. Include total_matching, has_more, and message fields when results might be partial.",
        "weight": 0.85,
    },
    {
        "content": "Never raise plain exceptions from tool functions. Use ToolError for agent-facing errors with actionable messages. Stack traces leak server internals and confuse the LLM.",
        "weight": 0.9,
    },
    {
        "content": "Tool docstrings serve dual purpose: human documentation and LLM instruction. Lead with what the tool does, then list parameters and return shape with examples.",
        "weight": 0.85,
    },
    {
        "content": "FastMCP tool functions can take a Context parameter (ctx: Context = None) for logging via ctx.info(). Use it for tool entry/exit logging that the client agent can see.",
        "weight": 0.8,
    },
    {
        "content": "Generate MCP tool scaffolds with: fips-agents generate tool <name> --description '...' --async --with-context. The scaffold creates the tool file and a test file at tests/tools/.",
        "weight": 0.85,
    },
    {
        "content": "Tool tests should cover: importability, signature stability, annotation regression (readOnlyHint etc), and parameter validation. The fips-agents scaffold ships these by default.",
        "weight": 0.85,
    },
    {
        "content": "Streamable-http is the only transport for MCP servers in production. STDIO is for local cmcp testing only. SSE is deprecated and removed from FastMCP v3.",
        "weight": 0.9,
    },
    {
        "content": "search_memory in memory-hub-mcp returns mixed full/stub results based on weight_threshold. Mode 'full_only' disables stubbing entirely; mode 'index' stubs everything.",
        "weight": 0.85,
    },
    {
        "content": "MCP tool response token budgeting: search_memory accepts max_response_tokens to cap response size. Once the cap is hit, remaining results degrade to stubs in similarity order.",
        "weight": 0.85,
    },
    {
        "content": "Branch handling in search_memory: by default, branches whose parent is also in the result set are dropped. Set include_branches=true to nest them under the parent in a 'branches' field.",
        "weight": 0.85,
    },
    {
        "content": "register_session is the auth shim for memory-hub-mcp. Pass api_key='mh-dev-<user>-<year>'. JWT auth replaces this when AUTH_JWKS_URI is configured.",
        "weight": 0.85,
    },
    {
        "content": "MCP tool error messages should be actionable. Bad: 'Invalid input.' Good: 'Invalid scope filter: \"foo\". Valid scopes: enterprise, organizational, project, role, user.'",
        "weight": 0.85,
    },
    {
        "content": "Tool parameter defaults should match the most common use case. search_memory's max_results=10 is the right default for agents that want a small focused result set.",
        "weight": 0.8,
    },
    {
        "content": "Use Annotated[str | None, Field(description='...')] for optional MCP tool parameters. The default of None signals 'omit' to MCP clients; explicit nulls are stripped before the tool runs.",
        "weight": 0.8,
    },
    {
        "content": "fips-agents is a global pipx CLI tool. Run it directly, not from .venv/bin/. Inside venvs it isn't installed; the global path is what the slash commands rely on.",
        "weight": 0.85,
    },
    {
        "content": "MCP tool annotation hints affect agent behavior. readOnlyHint=true tells the LLM the tool is safe to call speculatively. Setting it wrong leads to either over-cautious or destructive agent loops.",
        "weight": 0.85,
    },
    {
        "content": "Always include type annotations on MCP tool parameters. The tool registration depends on type hints to generate the JSON schema; bare 'param=value' fails.",
        "weight": 0.85,
    },
    {
        "content": "MCP tool return types should be dict[str, Any] for structured responses. FastMCP serializes the dict to JSON automatically; returning a Pydantic model also works but isn't necessary.",
        "weight": 0.8,
    },
    {
        "content": "Don't use bare 'dict' or 'list' as type annotations in MCP tool signatures. Use parameterized 'dict[str, str]' and 'list[str]' or the schema generation produces 'object' which is unhelpful for the LLM.",
        "weight": 0.85,
    },
    {
        "content": "FastMCP middleware extends the Middleware base and overrides on_call_tool to wrap requests. Useful for shared auth checks, request logging, or response transformations.",
        "weight": 0.75,
    },
    {
        "content": "Test FastMCP middleware with the same .fn pattern as tools. The decorator wraps the class, and the test must instantiate it directly to call the underlying methods.",
        "weight": 0.75,
    },
    {
        "content": "MCP resource URIs use the resource://<scheme>/<path> pattern. Resources are read-only by design; mutating operations belong in tools, not resources.",
        "weight": 0.75,
    },
    {
        "content": "MCP prompts return either str, PromptMessage, or list[PromptMessage]. Use list[PromptMessage] for multi-turn examples. The agent receives the prompt as conversation history.",
        "weight": 0.75,
    },
    {
        "content": "Use cmcp for local MCP testing: cmcp '.venv/bin/python -m src.main' tools/list. Runs the server in STDIO mode and lists registered tools, useful for debugging registration issues.",
        "weight": 0.8,
    },
    {
        "content": "After deploying MCP server changes that add or remove tools, restart LibreChat. LibreChat caches the tool list per agent and won't pick up new tools until the service reloads.",
        "weight": 0.85,
    },
    {
        "content": "Use mcp-test-mcp to verify deployed MCP servers. It connects to the streamable-http endpoint and lists tools, exercises tool calls, and reports schema mismatches.",
        "weight": 0.8,
    },
    {
        "content": "MCP tool signature changes are breaking changes for clients. Treat the tool surface as a public API and version it explicitly if multiple agent generations need to coexist.",
        "weight": 0.85,
    },
    {
        "content": "Search tools should accept optional scope and owner_id filters but default them sensibly. memory-hub-mcp's search_memory defaults owner_id to the authenticated user; pass empty string to search all.",
        "weight": 0.8,
    },
    {
        "content": "MCP tool error responses use raise ToolError(message). The message is shown to the agent and should explain how to fix the call. Don't include stack traces or sensitive data.",
        "weight": 0.85,
    },
    {
        "content": "Don't delegate MCP tool work to subagents in the memory-hub repo. Sub-agents skip the fips-agents scaffold and produce structurally divergent tools. Always run /plan-tools and /create-tools in main context.",
        "weight": 0.95,
    },
    {
        "content": "MCP tool response shape changes require same-commit consumer audit. Grep memoryhub-ui/backend, sdk/, and memoryhub-cli/ for old field names before committing. Pydantic extra=allow masks the breakage silently.",
        "weight": 0.9,
    },
    {
        "content": "Use the /exercise-tools slash command after generating tools to test ergonomics. It role-plays as the consuming agent and catches misleading docstrings, ambiguous parameters, and unhelpful error messages.",
        "weight": 0.85,
    },
    {
        "content": "MCP tool dependencies must be listed in BOTH pyproject.toml AND requirements.txt. pyproject is for local pip install -e .; requirements.txt is for the container build.",
        "weight": 0.85,
    },
    {
        "content": "FastMCP Context.info is the right way to log inside a tool function. Logs go to the MCP client agent's transcript, not just the server stdout. Useful for explaining tool decisions.",
        "weight": 0.75,
    },
    {
        "content": "MCP tool naming convention: snake_case verbs like 'search_memory', 'write_memory', 'read_memory'. CamelCase or noun-only names confuse the LLM about whether the tool is callable.",
        "weight": 0.85,
    },
    {
        "content": "Run /plan-tools first, then /create-tools, then /exercise-tools, then /deploy-mcp. The workflow is sequential because /create-tools depends on TOOLS_PLAN.md from /plan-tools.",
        "weight": 0.85,
    },
    {
        "content": "MCP tool count target: 5-15 tools per server. More than 15 and the LLM struggles to pick the right tool; fewer than 5 and the server probably should be merged with another.",
        "weight": 0.75,
    },
    {
        "content": "memory-hub-mcp has 12 tools total: register_session, search_memory, read_memory, write_memory, update_memory, delete_memory, get_memory_history, get_similar_memories, get_relationships, create_relationship, suggest_merge, set_curation_rule, report_contradiction.",
        "weight": 0.85,
    },
    {
        "content": "MCP tool parameter validation belongs in Pydantic Field constraints, not in the tool body. Field(ge=0, le=1) for floats, Field(min_length=1) for strings. Surfaces in the JSON schema for free.",
        "weight": 0.8,
    },
    {
        "content": "Don't use custom MCP transport implementations. Stick with FastMCP's built-in streamable-http for HTTP and stdio for local. Custom transports break MCP client compatibility.",
        "weight": 0.85,
    },
    {
        "content": "Test FastMCP tools with pytest-asyncio in auto mode. Set asyncio_mode='auto' in pyproject.toml so async test functions don't need an explicit @pytest.mark.asyncio decorator.",
        "weight": 0.8,
    },
]

assert len(MEMORIES) == 50, f"mcp_tools fixture must have 50 memories, has {len(MEMORIES)}"

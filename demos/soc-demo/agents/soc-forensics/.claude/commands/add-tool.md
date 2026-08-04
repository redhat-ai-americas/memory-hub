# Add Tool

Add a new tool to the agent with the `@tool` decorator. This command walks through designing the tool, generating the code, and verifying it integrates with the tool registry.

**Prerequisite: `/create-agent` must have been run first.** Verify `src/agent.py` exists and contains a BaseAgent subclass before proceeding.

## Process

### Step 1: Understand the Tool

Ask the developer:

1. **What does the tool do?** Get a clear, one-sentence description.
2. **Who calls it?** This determines visibility:
   - `agent_only` — called by agent Python code in `step()`. The LLM never sees it. Good for: validation, formatting, post-processing, internal state management.
   - `llm_only` — surfaced to the LLM as a callable tool. The LLM decides when to use it. Good for: search, retrieval, information gathering, actions the LLM should reason about.
   - `both` — accessible from either plane. Rare — use only when both the agent code and the LLM need to call the same tool.
3. **What are the parameters?** Name, type, and whether each is required or optional.
4. **What does it return?** Return type and format.
5. **Does it perform I/O?** If yes, it should be `async`. If it is pure computation (string formatting, validation, data transformation), it can be synchronous — the tool system runs sync functions in a thread executor automatically.

### Step 2: Check for Conflicts

Before generating the tool, verify:

- No existing tool in `tools/` has the same name. List current tools:
  ```bash
  ls tools/*.py | grep -v __pycache__
  ```
- The tool name does not conflict with any MCP tools configured in `agent.yaml`. Check the `mcp_servers` section — if MCP servers are configured, their tools are discovered at runtime and could collide.
- The tool name is a valid Python identifier (snake_case, no hyphens, no spaces).

### Step 3: Generate the Tool File

Create `tools/<tool_name>.py` with this structure:

```python
"""<One-line description> — <visibility> (plane <1|2|both>).

<Optional longer description explaining when and how this tool is used.>
"""

from fipsagents.baseagent.tools import tool


@tool(
    description="<One-sentence description for the tool schema>",
    visibility="<agent_only|llm_only|both>",
)
async def tool_name(param1: str, param2: int = 10) -> str:
    """<Extended description>.

    Args:
        param1: <What this parameter controls>.
        param2: <What this parameter controls>.

    Returns:
        <What the tool returns and in what format>.
    """
    # Implementation here
    ...
```

Guidelines for the implementation:

- **Real implementation preferred.** Write the actual logic, not a stub. If the tool calls an external API, write the httpx call. If it processes data, write the processing logic.
- **If a real implementation is not possible yet** (e.g., requires an API key or external service not yet available), write a clear stub with a comment explaining what the real implementation should do. Mark the stub with `# TODO: Replace stub with real implementation`.
- **Error handling**: Raise exceptions with informative messages on failure. The tool system catches exceptions and converts them to `ToolResult` with `is_error=True`, so the caller gets a clean error message.
- **No side effects on agent state**: Tools should not modify `self.messages` or other agent state. They receive input, do work, and return output. The agent code in `step()` decides what to do with the result.
- **Type hints are mandatory**: The tool system generates JSON schemas from type hints. Missing type hints produce empty parameter schemas, which confuse the LLM.

### Step 4: Add Dependencies (if needed)

If the tool requires a new Python package:

1. Add it to the `[project.dependencies]` list in `pyproject.toml`.
2. Run `pip install -e .` (or `make install`) to install it in the local venv.

Do not add dependencies speculatively. Only add what the tool actually imports.

### Step 5: Verify Discovery

Confirm the tool is picked up by the registry:

```bash
python -c "
from fipsagents.baseagent.tools import ToolRegistry
r = ToolRegistry()
discovered = r.discover('./tools')
for t in discovered:
    print(f'  {t.name} (visibility={t.visibility})')
"
```

The new tool should appear in the output with the correct name and visibility.

If it does not appear:
- Check that the file is in `tools/` (not a subdirectory)
- Check that the function has the `@tool` decorator
- Check for import errors: `python -c "import tools.<tool_name>"`

### Step 6: Update the Agent (if needed)

If the tool is `agent_only` or `both`, the agent code in `src/agent.py` may need to call it. Review `step()` and determine where the tool call belongs. Agent-code tool calls use:

```python
result = await self.use_tool("tool_name", param1="value", param2=42)
if result.is_error:
    logger.warning("Tool failed: %s", result.error)
else:
    # Use result.result (always a string)
    ...
```

If the tool is `llm_only`, the LLM will discover it automatically — no changes to `src/agent.py` are needed. However, consider updating the system prompt (`prompts/system.md`) to mention the new tool so the LLM knows when to use it.

### Step 7: Run Tests

Run `make test` to verify nothing is broken. If the tool is important enough for dedicated tests, add a test file at `tests/test_<tool_name>.py` that covers:

- Successful execution with valid input
- Error handling with invalid input
- Edge cases relevant to the tool's logic

### Step 8: Summary

Tell the developer:
- Tool name, file location, and visibility
- Whether `src/agent.py` was updated to call it
- Whether `prompts/system.md` was updated to reference it
- Whether any new dependencies were added
- Test results

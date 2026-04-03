---
description: Generate and implement tools from TOOLS_PLAN.md using parallel subagents
---

# Create MCP Tools

You are implementing tools defined in `TOOLS_PLAN.md`. This command uses subagents to parallelize implementation.

## Prerequisites

- `TOOLS_PLAN.md` must exist (created by `/plan-tools`)
- If it doesn't exist, tell the user to run `/plan-tools` first

## Your Task

### Step 1: Read the Plan

Read `TOOLS_PLAN.md` and extract the list of tools to implement.

### Step 2: Generate Tool Scaffolds

**IMPORTANT**: `fips-agents` is a global CLI tool (installed via pipx). Run it directly - do NOT use `.venv/bin/fips-agents`.

For each tool in the plan, run:

```bash
fips-agents generate tool <tool_name> --description "<description>" --async --with-context
```

This creates:
- `src/tools/<tool_name>.py` - Tool implementation scaffold
- `tests/test_<tool_name>.py` - Test file scaffold

### Step 3: Implement Tools in Parallel

**IMPORTANT**: Use the Task tool to launch multiple `claude-worker` subagents in parallel (one per tool).

For each tool, create a subagent with this prompt:

```
Implement the MCP tool according to this specification:

Tool: <tool_name>
Purpose: <from TOOLS_PLAN.md>
Parameters: <from TOOLS_PLAN.md>
Returns: <from TOOLS_PLAN.md>
Error Cases: <from TOOLS_PLAN.md>

Follow the /implement-mcp-item workflow:
1. Read and implement src/tools/<tool_name>.py
2. Update tests/test_<tool_name>.py with comprehensive tests
3. Run pytest tests/test_<tool_name>.py -v
4. Report success or failure with details

Key requirements:
- Use proper type hints (Annotated with Field descriptions)
- Implement robust error handling with helpful messages
- Return meaningful error messages that help agents recover
- Keep implementation simple and focused
```

### Step 4: Aggregate Results

After all subagents complete:
1. Collect results from each subagent
2. Report which tools succeeded and which failed
3. For failures, summarize the issue

### Step 5: Run Full Test Suite

Run all tests to ensure nothing is broken:

```bash
.venv/bin/pytest tests/ -v --ignore=tests/examples/
```

### Step 6: Pre-deployment Permission Fix

Fix any permission issues from subagent-created files:

```bash
find src -name "*.py" -perm 600 -exec chmod 644 {} \;
```

## Example Execution Flow

```
User: /create-tools

Agent: Reading TOOLS_PLAN.md...
Found 4 tools to implement: get_weather, search_locations, get_forecast, get_alerts

Generating scaffolds...
- fips-agents generate tool get_weather --description "Get current weather" --async --with-context
- fips-agents generate tool search_locations --description "Search for locations" --async --with-context
- fips-agents generate tool get_forecast --description "Get weather forecast" --async --with-context
- fips-agents generate tool get_alerts --description "Get weather alerts" --async --with-context

Launching 4 parallel implementation subagents...
[Task tool calls with claude-worker subagent_type]

Results:
- get_weather: SUCCESS (3 tests passed)
- search_locations: SUCCESS (4 tests passed)
- get_forecast: SUCCESS (3 tests passed)
- get_alerts: SUCCESS (2 tests passed)

Full test suite: 12 tests passed

Permission fix applied.

All tools implemented successfully. Run /exercise-tools to test ergonomics.
```

## Important Guidelines

- **Always use TOOLS_PLAN.md as the source of truth**
- **Launch subagents in parallel** for efficiency
- **Do not skip the permission fix** - this prevents deployment issues
- If a tool fails, report the failure clearly but continue with others
- The full test suite must pass before declaring success

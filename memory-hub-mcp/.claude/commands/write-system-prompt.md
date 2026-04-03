---
description: Create an AI agent system prompt based on implemented tools
---

# Write System Prompt

You are generating a comprehensive system prompt for an AI agent that will use this MCP server's tools.

## Your Task

### Step 1: Discover Implemented Tools

Read all tool files in `src/tools/`:
- Ignore `__init__.py` files
- Ignore any files starting with `_`
- Ignore the `examples/` subdirectory if it exists

For each tool file:
1. Extract the tool name, description, parameters, and return type
2. Note any error conditions documented in the code
3. Identify dependencies between tools (if any)

### Step 2: Gather Context

Read any existing context documents:
- `TOOLS_PLAN.md` - for original design intent
- `README.md` - for project overview
- Any proposal or requirements docs in the project root

### Step 3: Generate the System Prompt

Create `SYSTEM_PROMPT.md` at the project root with this structure:

```markdown
# System Prompt: [MCP Server Name] Agent

## Role and Capabilities

[Describe the agent's role based on the tools available]

You are an AI assistant with access to the following specialized tools:

### Available Tools

[For each tool, provide:]
- **tool_name**: [Brief description]
  - Parameters: [list key parameters]
  - Use when: [guidance on when to use this tool]

## Guidelines for Tool Usage

### When to Use Tools

[Guidance on recognizing when tools are needed vs. answering directly]

### Tool Selection

[How to choose between available tools for a given task]

### Parameter Preparation

[How to gather and validate parameters before calling tools]

## Error Handling

### Common Errors and Recovery

[For each common error type:]
- **Error**: [error type]
  - **Cause**: [what causes this error]
  - **Recovery**: [how to recover or help the user]

### Graceful Degradation

[What to do when tools fail or are unavailable]

## Tool Composition Patterns

[Describe common patterns for combining tools effectively]

### Pattern 1: [Pattern Name]
[Description and example]

### Pattern 2: [Pattern Name]
[Description and example]

## Best Practices

### Do

- [Positive guidance]
- [Positive guidance]

### Don't

- [Anti-patterns to avoid]
- [Anti-patterns to avoid]

## Example Interactions

### Example 1: [Scenario]

**User**: [Example user message]

**Agent Reasoning**: [How the agent should think about this]

**Tool Calls**: [What tools to call and in what order]

**Response**: [How to present results to user]

### Example 2: [Scenario]

[Similar structure]
```

### Step 4: Present for Review

After creating `SYSTEM_PROMPT.md`:
1. Summarize what was generated
2. Highlight the key capabilities described
3. Ask if any adjustments are needed

## Tool Discovery Patterns

When reading tool files, look for these patterns:

### FastMCP Tool Decorator
```python
@mcp.tool
async def tool_name(
    param: Annotated[str, Field(description="...")],
    ctx: Context = None,
) -> str:
    """Tool description for the LLM."""
```

Extract:
- Function name = tool name
- Docstring = tool description
- Parameters with their Field descriptions
- Return type annotation

### Error Handling
Look for:
- `raise ValueError(...)` or similar
- Try/except blocks with specific error messages
- Error return patterns

## Important Guidelines

- **Base the prompt on actual implementation** - don't assume tools that don't exist
- **Focus on agent usability** - the prompt should help an agent use tools effectively
- **Include concrete examples** - abstract guidance is less useful than examples
- **Consider composition** - how tools work together is as important as individual tools
- **Document error recovery** - agents need to know how to handle failures
- **Keep it practical** - avoid generic filler; every sentence should add value

## Example Output

After running this command, you should have:
1. A `SYSTEM_PROMPT.md` file tailored to the implemented tools
2. A summary of the agent's capabilities
3. Confirmation that the prompt reflects actual implementation

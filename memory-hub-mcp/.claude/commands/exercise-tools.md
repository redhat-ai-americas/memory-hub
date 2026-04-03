---
description: Test tool ergonomics by role-playing as the consuming agent
---

# Exercise MCP Tools

You are testing the ergonomics of the implemented tools by role-playing as the agent that will consume them.

## Your Task

### Step 1: Understand the Context

1. Read `TOOLS_PLAN.md` to understand the intended use cases
2. Read the implemented tools in `src/tools/`
3. Identify the target agent persona (who will use these tools?)

### Step 2: Role-Play as the Consuming Agent

Assume the role of an AI agent that needs to accomplish tasks using these tools. For each tool:

#### A. Test Basic Usage

Try to use the tool as you would in a real scenario:
- What information do you need to call it?
- Are the parameter names intuitive?
- Does the description tell you what you need to know?

#### B. Test Error Scenarios

Intentionally try to break the tool:
- What happens with invalid inputs?
- Are error messages helpful for recovery?
- Do errors explain what went wrong AND how to fix it?

#### C. Test Tool Composition

Try to combine tools to accomplish a larger task:
- Do tools work well together?
- Is there missing functionality that would help?
- Are there redundant tools that could be consolidated?

### Step 3: Provide Structured Feedback

For each tool, provide feedback in this format:

```markdown
## Tool: <tool_name>

### Ergonomics Score: [1-5]

### What Works Well
- [Positive observations]

### Issues Found
- **Issue**: [Description]
  **Impact**: [How this affects agent usability]
  **Suggestion**: [How to fix]

### Parameter Review
- `param1`: [OK / Rename to X / Needs better description]
- `param2`: [OK / Should be optional / Wrong type]

### Error Message Review
- [Error case]: [Good / Needs improvement: suggestion]

### Recommended Changes
1. [Specific change]
2. [Specific change]
```

### Step 4: Make Improvements

For issues that are clear improvements (not subjective):
1. Make the change
2. Update tests if needed
3. Run tests to verify

For changes that need discussion:
1. Present the issue to the user
2. Ask for their preference
3. Implement their choice

### Step 5: Re-run Full Test Suite

After any changes:

```bash
.venv/bin/pytest tests/ -v --ignore=tests/examples/
```

## Example Exercise Session

```markdown
## Exercise Session: weather-mcp

### Role: AI assistant helping users plan outdoor activities

---

## Tool: get_weather

### Ergonomics Score: 4/5

### What Works Well
- Clear purpose from name and description
- Location parameter is intuitive
- Returns structured data that's easy to parse

### Issues Found
- **Issue**: `units` parameter defaults to "metric" but US users expect Fahrenheit
  **Impact**: Agent needs to always specify units for US users
  **Suggestion**: Add user locale detection or make units required

- **Issue**: Error message "Location not found" doesn't suggest alternatives
  **Impact**: Agent can't help user correct their input
  **Suggestion**: Return "Location 'X' not found. Did you mean: [suggestions]?"

### Parameter Review
- `location`: OK
- `units`: Should this be required? Currently defaults silently

### Error Message Review
- Invalid location: Needs improvement - should suggest alternatives
- API timeout: Good - explains retry is appropriate

### Recommended Changes
1. Enhance "location not found" error to include suggestions
2. Consider adding `include_forecast` parameter to reduce tool calls
```

## Important Guidelines

- **Think like the consuming agent**, not the developer
- **Prioritize actionable feedback** over nitpicks
- **Error messages are critical** - they determine agent recovery ability
- **Tool names and descriptions are API** - changes break existing usage
- **Make conservative changes** - only fix clear issues
- Ask user before making subjective changes (naming, defaults, etc.)

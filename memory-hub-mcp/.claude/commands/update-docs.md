---
description: Update README.md and ARCHITECTURE.md based on implemented components
---

# Update Documentation

You are updating the project documentation to reflect the actual implemented components. This command ensures README.md and ARCHITECTURE.md accurately describe the MCP server.

## Prerequisites Check (MANDATORY)

**Before proceeding, verify that example code has been removed.**

Check if these directories/files exist:
- `src/tools/examples/`
- `src/resources/examples/`
- `src/prompts/examples/`
- `src/middleware/examples/`
- `tests/examples/`

If ANY of these exist, STOP and tell the user:

```
Cannot update documentation while example code is present.

Please run ./remove_examples.sh first to remove the example implementations.
This ensures the documentation reflects your actual tools, not the template examples.

After removing examples, run /update-docs again.
```

**DO NOT proceed if examples still exist.**

## Your Task (After Examples Removed)

### Step 1: Inventory Components

#### Tools (src/tools/)
For each `.py` file (excluding `__init__.py` and `_` prefixed files):
- Tool name
- Description (from docstring)
- Parameters (name, type, description)
- Return type

#### Resources (src/resources/)
For each `.py` file in `src/resources/` and subdirectories:
- Resource URI pattern
- Description
- Return type (MIME type if available)

#### Prompts (src/prompts/)
For each `.py` file (excluding `__init__.py` and `_` prefixed files):
- Prompt name
- Description
- Parameters

#### Middleware (src/middleware/)
For each `.py` file:
- Middleware name
- Purpose
- What lifecycle hooks it implements

### Step 2: Update README.md

Update the README.md to include:

#### Tools Section
```markdown
## Tools

| Tool | Description |
|------|-------------|
| `tool_name` | Brief description |
| `another_tool` | Brief description |

### tool_name

[Detailed description]

**Parameters:**
- `param1` (type, required): Description
- `param2` (type, optional): Description

**Example:**
```json
{
  "param1": "value"
}
```
```

#### Resources Section (if any resources exist)
```markdown
## Resources

| URI Pattern | Description |
|-------------|-------------|
| `data://resource/{id}` | Brief description |
```

#### Prompts Section (if any prompts exist)
```markdown
## Prompts

| Prompt | Description |
|--------|-------------|
| `prompt_name` | Brief description |
```

### Step 3: Update ARCHITECTURE.md

If ARCHITECTURE.md exists, update the components section to reflect:
- Actual tool count and names
- Resource patterns
- Prompt definitions
- Middleware in use
- Any dependencies between components

If ARCHITECTURE.md doesn't exist, create a minimal version:

```markdown
# Architecture

## Component Overview

This MCP server provides [N] tools, [N] resources, [N] prompts, and [N] middleware components.

### Tools

[List actual tools with brief descriptions]

### Resources

[List actual resources with URI patterns]

### Prompts

[List actual prompts]

### Middleware

[List middleware and their purposes]

## Data Flow

[Describe how data flows through the server]

## Dependencies

[List external dependencies and why they're needed]
```

### Step 4: Verify Documentation Accuracy

After updating, verify:
1. Every tool listed in docs has a corresponding file in `src/tools/`
2. Parameter types and descriptions match the implementation
3. No example tools are mentioned (echo, add_numbers, etc.)
4. The tool/resource/prompt counts are accurate

### Step 5: Report Changes

Provide a summary:
```markdown
## Documentation Update Summary

### README.md Changes
- Updated tools section: [N] tools documented
- Updated resources section: [N] resources documented
- Updated prompts section: [N] prompts documented

### ARCHITECTURE.md Changes
- [List what was updated or created]

### Components Documented
- **Tools**: [list tool names]
- **Resources**: [list resource patterns]
- **Prompts**: [list prompt names]
- **Middleware**: [list middleware names]
```

## Important Guidelines

- **NEVER proceed if examples directory exists** - this is a hard requirement
- **Document actual implementation** - don't copy template content
- **Match parameter names exactly** - typos in docs cause confusion
- **Include usage examples** - concrete examples are more useful than descriptions
- **Remove placeholder content** - don't leave template text like "[Description]"
- **Update counts** - if docs say "3 tools" make sure there are actually 3 tools

## What NOT to Document

- `__init__.py` files
- Internal helper functions (prefixed with `_`)
- Test files
- Development utilities

## Error Cases

### Examples Still Present
```
STOP: Example directories found. Run ./remove_examples.sh first.
```

### No Tools Found
```
WARNING: No tools found in src/tools/.
Either tools haven't been implemented yet, or there's a directory structure issue.
Consider running /create-tools first.
```

### Documentation Can't Be Parsed
If README.md or ARCHITECTURE.md have unexpected structure:
```
The existing [file] has an unexpected structure.
I can either:
1. Overwrite with a fresh template (loses existing content)
2. Append the component documentation at the end
3. Show you the proposed changes for manual integration

Which approach would you prefer?
```

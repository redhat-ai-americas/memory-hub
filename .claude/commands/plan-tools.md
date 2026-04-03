---
description: Plan MCP tools by reading Anthropic's guidance and creating TOOLS_PLAN.md
---

# Plan MCP Tools

You are planning tools for an MCP server. This is a **discussion and planning phase only** - do NOT implement any code.

## Your Task

### Step 1: Read Anthropic's Tool Design Guidance

Use WebFetch to read this article:
**https://www.anthropic.com/engineering/writing-tools-for-agents**

Extract key principles for designing effective tools:
- How tools should be named
- How parameters should be designed
- What makes tools ergonomic for agents
- Error handling best practices
- Documentation requirements

### Step 2: Read the Current Proposal

Look for any existing proposal or requirements documents in the project:
- Check for files like `PROPOSAL.md`, `REQUIREMENTS.md`, `ideas/` directory
- Read the project's `README.md` for context on what this MCP server should do
- Check `CLAUDE.md` for any project-specific guidance

### Step 3: Create TOOLS_PLAN.md

Create a `TOOLS_PLAN.md` file at the project root with this structure:

```markdown
# Tools Plan

## Overview
[Brief description of what this MCP server does and who will use it]

## Design Principles Applied
[Key principles from Anthropic's article that apply to these tools]

## Tools

### tool_name_one
- **Purpose**: What this tool does
- **Parameters**:
  - `param1` (type, required/optional): Description
  - `param2` (type, required/optional): Description
- **Returns**: What the tool returns
- **Error Cases**: What errors can occur and how they're reported
- **Example Usage**: How an agent would use this tool

### tool_name_two
[Same structure...]

## Implementation Order
[Recommended order to implement tools, with reasoning]

## Dependencies
[Any external APIs, databases, or services these tools need]
```

### Step 4: Present for Review

After creating `TOOLS_PLAN.md`:
1. Summarize the planned tools
2. Highlight any design decisions that need user input
3. Ask for approval before proceeding to `/create-tools`

## Important Guidelines

- **DO NOT write any implementation code** - this is planning only
- **DO NOT generate tool files** - that's `/create-tools`'s job
- Focus on clear, specific tool specifications
- Consider how tools will be composed by agents
- Think about error messages that help agents recover
- Keep tool count minimal - prefer fewer, more powerful tools

## Example Output

After running this command, you should have:
1. A comprehensive `TOOLS_PLAN.md` file
2. A summary presented to the user
3. Questions about any ambiguous requirements

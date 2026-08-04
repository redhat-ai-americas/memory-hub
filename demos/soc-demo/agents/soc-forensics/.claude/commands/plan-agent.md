# Plan Agent

Design an agent before writing any code. This command produces an AGENT_PLAN.md file that captures what the agent does, what tools it needs, what prompts it uses, and how it behaves. The plan is reviewed and approved before any implementation begins.

**This is planning only. Do not generate code, create files outside of AGENT_PLAN.md, or modify any source files.**

## Process

### Step 1: Understand the Agent's Purpose

Start by asking the developer what this agent should do. Have a conversation to understand:

- What problem does this agent solve?
- Who or what interacts with it? (users, other agents, scheduled triggers, API calls)
- What does a successful run look like?
- What does a failed run look like?

Don't make this feel like a questionnaire. Let the conversation flow naturally. The goal is to understand the agent well enough to design it.

### Step 2: Identify Tools

Based on the agent's purpose, determine what tools it needs. For each tool, capture:

- **Name** and what it does
- **Visibility**: `agent_only` (called by agent code, LLM never sees it), `llm_only` (surfaced to the LLM for tool calling), or `both`
- **Source**: local (defined in `tools/`), MCP (from an external MCP server), or existing (already available in the environment)
- **Parameters and return type** (high level, not code)

Think carefully about which plane each tool belongs to. Tools the LLM should decide when to call go in plane 2 (`llm_only`). Tools the agent code calls as part of its logic go in plane 1 (`agent_only`). Tools that could be called by either go in `both`.

Common patterns:
- Validation tools are usually `agent_only` -- the agent validates LLM output, the LLM doesn't validate itself
- Search and retrieval tools are usually `llm_only` -- the LLM decides when to search
- Formatting and transformation tools are usually `agent_only`
- Action tools (send email, create issue) depend on whether the LLM or the agent code should decide when to act

### Step 3: Design Prompts

Identify what prompts the agent needs. At minimum, every agent has a system prompt (`prompts/system.md`). Many agents need additional prompts for specific tasks.

For each prompt, capture:
- **Name** and when it's used
- **Key instructions** it should contain (not the full text -- that comes during implementation)
- **Variables** it needs substituted
- **Model preferences** if different from the default (temperature, max tokens)

### Step 4: Identify Skills

Does the agent need skills (agentskills.io)? Skills are for capabilities that:
- Are too large to keep in context all the time
- Are only needed in certain situations
- Have their own scripts, references, or assets

Most simple agents don't need skills. Don't add skills unless there's a clear reason.

### Step 5: Define Rules

What behavioral constraints should the agent follow? Rules are persistent guidance injected into context at startup. Examples:
- "Never modify production data without confirmation"
- "Always include source URLs in citations"
- "Rate limit external API calls to 10 per minute"

Rules differ from the system prompt in that they are constraints, not instructions. The system prompt says what to do; rules say what not to do (or what to always do regardless of task).

### Step 6: Consider Memory

Does this agent need persistent memory across runs? If yes, MemoryHub integration via `memoryhub config init` should be part of the implementation plan.

Questions to consider:
- Does the agent need to remember things between conversations?
- Does it share context with other agents?
- What scope level is appropriate? (user, project, role, org, enterprise)

If the answer to all of the first two is no, skip memory.

### Step 7: Plan Configuration

What configuration does the agent need beyond the defaults in `agent.yaml`?
- Additional MCP server connections?
- Custom model or temperature settings?
- Environment-specific values that need env var substitution?
- Secrets (API keys, tokens) that need OpenShift Secrets?

### Step 8: Define Success Criteria

How do we know the agent works? Define:
- 3-5 eval cases that cover the happy path
- 2-3 eval cases that cover failure modes or edge cases
- What "correct" looks like for each case

These become the initial entries in `evals/evals.yaml` during implementation.

### Step 9: Write AGENT_PLAN.md

Compile everything into `AGENT_PLAN.md` at the project root with this structure:

```markdown
# Agent Plan: [Agent Name]

## Purpose
[One paragraph describing what the agent does and why]

## Interaction Model
[How the agent is invoked, what it receives, what it returns]

## Tools

### [tool_name] (visibility: agent_only|llm_only|both)
- Source: local | mcp | existing
- Description: [what it does]
- Parameters: [high level]
- Returns: [high level]

[Repeat for each tool]

## Prompts

### system.md
- Used: Always, as the system prompt
- Key instructions: [summary]
- Variables: [list]

[Additional prompts as needed]

## Skills
[List or "None required"]

## Rules
[List of behavioral constraints, one per line]

## Memory
[MemoryHub requirements or "Not required"]

## Configuration
[Additional config beyond defaults, or "Default agent.yaml is sufficient"]

## Eval Cases

### Happy Path
- [case 1]: [input] → [expected outcome]
- [case 2]: [input] → [expected outcome]

### Edge Cases / Failures
- [case 1]: [input] → [expected behavior]
```

### Step 10: Review

Present the plan to the developer. Ask:

- Does this capture what you want the agent to do?
- Are any tools missing?
- Are the visibility assignments correct?
- Do the eval cases cover the important scenarios?

Do not proceed to implementation until the developer approves the plan. If they want changes, update AGENT_PLAN.md and present again.

When approved, tell the developer to run `/create-agent` to begin implementation.

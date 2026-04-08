---
description: Break down complex tasks into sub-problems, solve them efficiently, then aggregate results
---

# Decompose and Solve

The user has requested: $ARGUMENTS

## Purpose

This command helps save context in the main conversation by delegating work to a specialized subagent. Instead of solving everything in the main context window, we use the **claude-worker** subagent to handle the detailed work.

## Process

### Step 1: Problem Decomposition

Analyze the user's request and break it down into distinct, manageable sub-problems. Consider:
- Can this be parallelized?
- What are the dependencies between sub-problems?
- What information is needed for each sub-problem?
- Are there any sub-problems that would benefit from specialized subagents?

Create a numbered list of sub-problems to solve.

### Step 2: Solve Using Subagent

Use the **claude-worker** subagent to solve the decomposed problems:

Launch the subagent with a prompt like:

```
I have broken down the following request into sub-problems:
[List the sub-problems with context]

Please solve each of these problems in sequence (or in parallel where possible):

1. [Sub-problem 1 with details]
2. [Sub-problem 2 with details]
3. [Sub-problem 3 with details]

For each sub-problem:
- Provide the solution
- Note any issues or blockers
- If a specialized subagent would be better suited, invoke it

When you encounter tasks that match these specialties, use the appropriate subagent:
- Architecture/design decisions → solution-architect or proposal-writer
- Security concerns → security-compliance-scanner
- Code review → senior-code-reviewer
- Testing → test-execution-analyst
- Documentation → documentation-architect
- [Other relevant subagents based on context]

After solving all sub-problems, provide a consolidated summary of results.
```

### Step 3: Aggregate and Present

After the subagent completes its work:
1. Review the consolidated results
2. Synthesize the findings into a coherent response
3. Present the final solution to the user
4. Note any outstanding issues or follow-up items

## Why This Approach?

**Context Preservation**: By delegating detailed work to the claude-worker subagent, we:
- Keep the main conversation focused on high-level coordination
- Preserve context for follow-up questions
- Reduce token usage in the main thread
- Allow the subagent to use its own context window for detailed problem-solving

**Flexibility**: The claude-worker can invoke other specialized subagents as needed, providing a one-level delegation hierarchy that handles most complex tasks efficiently.

## Example Usage

User request: "Refactor the authentication system, add OAuth support, and update the documentation"

Decomposition:
1. Analyze current authentication implementation
2. Design OAuth integration approach
3. Implement OAuth provider support
4. Refactor existing auth code for compatibility
5. Update API documentation
6. Update user-facing documentation
7. Add tests for OAuth flow

Then delegate to claude-worker with instructions to use:
- proposal-writer for the OAuth design
- senior-code-reviewer after implementation
- documentation-architect for docs
- test-execution-analyst for testing strategy

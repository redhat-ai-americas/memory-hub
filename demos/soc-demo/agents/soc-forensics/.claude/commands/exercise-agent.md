# Exercise Agent

Test agent behavior through structured role-play scenarios. This command validates that the agent responds correctly, uses tools appropriately, and handles edge cases gracefully — all without deploying to OpenShift.

**Prerequisites: The agent must be implemented (run `/create-agent` first). `src/agent.py` and at least one prompt in `prompts/` must exist.**

## Process

### Step 1: Load the Agent's Design

Read the following files to understand what the agent should do:

- `AGENT_PLAN.md` — the approved design (if it exists)
- `src/agent.py` — the actual implementation
- `prompts/system.md` — the system prompt
- `agent.yaml` — configuration (model, tools, MCP servers)
- All files in `tools/` — what tools are available and their visibility
- All files in `rules/` — behavioral constraints
- All `SKILL.md` files in `skills/` — available skills

Build a mental model of: what inputs the agent expects, what tools it should call and when, what outputs it should produce, and what it should refuse to do.

### Step 2: Define Test Scenarios

Create a set of test scenarios covering three categories.

**Happy path scenarios** (at least 3): Straightforward inputs where the agent should succeed. These test the core workflow end-to-end. If `AGENT_PLAN.md` has eval cases, use those as a starting point.

**Edge case scenarios** (at least 2): Unusual but valid inputs that test boundary conditions. Examples:
- Very short or very long input
- Input in an unexpected format
- Input that requires multiple tool calls
- Input where the first search yields no useful results

**Failure scenarios** (at least 2): Inputs where the agent should fail gracefully. Examples:
- Request that violates a rule
- Request outside the agent's scope
- Tool returns an error
- Ambiguous input that needs clarification

For each scenario, write:
- A name and one-sentence description
- The simulated user input
- Expected behavior (which tools should be called, in what order)
- Expected output characteristics (not exact text, but qualities: "should include citations", "should refuse politely", etc.)

Present the scenarios to the developer for approval before running them.

### Step 3: Run Each Scenario

For each approved scenario, simulate the interaction:

1. **Set up**: Create the agent instance with `agent.yaml` configuration.
2. **Inject input**: Add the user message to the conversation.
3. **Execute**: Call `step()` and observe the behavior.
4. **Trace tool calls**: Note which tools were called, with what arguments, and what they returned.
5. **Evaluate output**: Compare the agent's response against expected behavior.

Since the agent calls an LLM (which may not be available locally), exercise scenarios in one of two modes:

**Live mode** (LLM endpoint available): Run the agent for real. This gives the most accurate results but requires a running model endpoint. Check if the endpoint in `agent.yaml` is reachable before attempting this.

**Dry-run mode** (no LLM available): Walk through the `step()` logic manually, reasoning about what the LLM would likely respond at each point. This is less precise but still catches structural issues like:
- Tools that would never be called due to visibility mismatches
- Missing prompts referenced in code
- Configuration errors
- Broken import chains

Tell the developer which mode you are using and why.

### Step 4: Evaluate Results

For each scenario, assess:

- **Correctness**: Did the agent produce the right kind of output?
- **Tool usage**: Were the right tools called in the right order? Were agent-only tools called from agent code (not offered to the LLM)? Were LLM-only tools available in the tool schemas?
- **Rule compliance**: Did the agent follow all rules in `rules/`?
- **Error handling**: When things went wrong, did the agent fail gracefully with an informative message?
- **Efficiency**: Did the agent avoid unnecessary tool calls or model invocations?

### Step 5: Write Eval Cases

Compile the scenarios and their expected outcomes into `evals/evals.yaml`. Use this structure:

```yaml
cases:
  - name: descriptive_test_name
    description: >
      One sentence explaining what this tests.
    input: "The simulated user message as a plain string"
    expected_behavior: >
      Prose description of what the agent should do: which tools it should
      call, what the output should contain, and how it should behave.
    tags: [smoke]        # Use tags to reflect scenario category:
                         #   smoke / happy_path — core workflow
                         #   edge_case          — boundary conditions
                         #   failure            — graceful error handling
    assertions:
      - type: tool_called        # Verify a specific tool was invoked
        tool: tool_name
      - type: field_exists       # Verify a field is present in the response
        field: answer
      - type: contains           # Verify a field contains a substring
        field: answer
        value: "expected phrase"
      - type: not_contains       # Verify a field does not contain a substring
        field: answer
        value: "phrase that must not appear"
      - type: field_gte          # Verify a numeric field meets a minimum
        field: result_count
        value: 1
```

Available assertion types: `tool_called` (params: `tool`, optional `min_calls`), `field_exists` (params: `field`), `contains` (params: `field`, `value`), `not_contains` (params: `field`, `value`), `field_gte` (params: `field`, `value`), `field_lte` (params: `field`, `value`), `custom` (for external harnesses).

If `evals/evals.yaml` already exists, merge the new cases in under the top-level `cases:` key rather than overwriting the file.

### Step 6: Report

Present a structured report:

**Passed scenarios**: List each passing scenario with a one-line summary.

**Failed scenarios**: For each failure, explain:
- What went wrong
- Why it went wrong (code issue, prompt issue, tool issue, config issue)
- Suggested fix

**Observations**: Note anything surprising or worth discussing, even in passing scenarios:
- Tool call patterns that seem inefficient
- Prompt wording that could be clearer
- Missing error handling
- Opportunities for additional tools or skills

Ask the developer whether to fix any issues now or move on to `/deploy-agent`.

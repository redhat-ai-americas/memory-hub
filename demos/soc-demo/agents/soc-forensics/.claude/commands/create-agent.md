# Create Agent

Scaffold the agent implementation from an approved AGENT_PLAN.md. This command generates the agent subclass, tools, prompts, skills, rules, and configuration based on the plan produced by `/plan-agent`.

**Prerequisites: AGENT_PLAN.md must exist at the project root and be developer-approved. If it does not exist, stop and tell the developer to run `/plan-agent` first.**

## Process

### Step 1: Read and Validate the Plan

Read `AGENT_PLAN.md` from the project root. Confirm it has all required sections:

- Purpose
- Interaction Model
- Tools (with visibility for each)
- Prompts (at minimum a system prompt)
- Skills
- Rules
- Memory
- Configuration
- Eval Cases

If any section is missing or says "TBD", stop and ask the developer whether to proceed with defaults or go back to `/plan-agent` to fill it in.

### Step 2: Generate the Agent Subclass

Create `src/agent.py` based on the plan. The subclass should:

- Import from `base_agent` (`BaseAgent`, `StepResult`, `ModelResponse`, and any Pydantic schemas needed)
- Define Pydantic models for any structured output the agent produces
- Implement `step()` with the agent's core logic
- Use `self.call_model()` for LLM interaction (auto-includes LLM-visible tool schemas)
- Use `self.use_tool(name, **kwargs)` for agent-code tool calls (plane 1)
- Handle tool calls from the LLM response via `response.tool_calls`
- Return `StepResult.done(result=...)` when finished or `StepResult.continue_()` to loop

Reference the existing example at `src/agent.py` (ResearchAssistant) for the pattern. The new agent replaces it entirely — do not keep the example code.

Keep the subclass under 100 lines. If the logic is complex, break helper functions into the class or into separate modules under `src/`.

### Step 3: Generate Tools

For each tool listed in AGENT_PLAN.md, create a file in `tools/`:

- One file per tool, named after the tool function (e.g., `tools/validate_output.py`)
- Use the `@tool` decorator from `base_agent.tools`
- Set `visibility` exactly as specified in the plan (`agent_only`, `llm_only`, or `both`)
- Include a clear docstring with Args/Returns sections (Google style)
- Use proper type hints on all parameters and return values
- Make the function `async` if it performs any I/O; sync is fine for pure computation

Example structure:

```python
from fipsagents.baseagent.tools import tool

@tool(
    description="What this tool does in one sentence",
    visibility="llm_only",
)
async def tool_name(param: str, count: int = 5) -> str:
    """Extended description of what the tool does.

    Args:
        param: What this parameter controls.
        count: How many results to return.

    Returns:
        Formatted results as a string.
    """
    ...
```

Remove the example tools (`tools/web_search.py`, `tools/format_citations.py`) unless the plan calls for them.

For tools marked as "MCP" source in the plan, do not create a local file. Instead, note them for the configuration step — they come from MCP server connections configured in `agent.yaml`.

### Step 4: Generate Prompts

For each prompt in the plan, create a Markdown file in `prompts/`:

- One file per prompt, using the name from the plan (e.g., `prompts/system.md`, `prompts/summarize.md`)
- Include YAML frontmatter with: `name`, `description`, `temperature` (if non-default), and `variables`
- Use `{variable_name}` substitution in the body
- Write clear, specific instructions — not vague placeholders

The system prompt (`prompts/system.md`) is required. Replace the example system prompt with one tailored to this agent's purpose. Include:

- What the agent is and what it does
- Step-by-step instructions for its workflow
- Constraints and behavioral guidelines
- References to available tools (by name) so the LLM knows what it can call

### Step 5: Generate Skills (if specified)

If the plan includes skills, create a directory per skill under `skills/`:

```
skills/
  skill-name/
    SKILL.md
```

Each `SKILL.md` needs:

- YAML frontmatter: `name`, `description`, `version`, `triggers`, `dependencies`, `parameters`
- Markdown body with: behavior instructions, output format, and at least one example

Remove the example skill (`skills/summarize/`) unless the plan calls for it.

If the plan says "None required", leave `skills/` empty (remove the example).

### Step 6: Generate Rules (if specified)

For each rule in the plan, create a Markdown file in `rules/`:

- One file per rule, named descriptively (e.g., `rules/no_pii_in_output.md`)
- Plain Markdown, no frontmatter
- Imperative tone: "Always do X" or "Never do Y"
- Keep each rule focused on a single constraint

Remove the example rule (`rules/citation_required.md`) unless the plan calls for it.

### Step 7: Update agent.yaml

Update `agent.yaml` with settings from the plan:

- Model name and endpoint if different from defaults
- Temperature if specified
- MCP server entries for any "MCP" source tools
- Loop settings (max_iterations, backoff) if the plan specifies them
- Any additional configuration the plan calls for

Preserve the `${VAR:-default}` env var substitution pattern. Every value that might differ between local development and production should use this pattern.

### Step 8: Update pyproject.toml

If the plan mentions a specific agent name, update the project name and description in `pyproject.toml`. Ensure any new dependencies required by tools are listed.

### Step 9: Generate AGENTS.md

Populate `AGENTS.md` using `AGENT_PLAN.md` as the source. Replace the placeholder content with:

- **Agent name**: Use the agent name from the plan as the top-level heading.
- **Version**: Set to `0.1.0`.
- **Capabilities**: Write a short paragraph drawn from the Purpose section of the plan.
- **Tools table**: List every tool with its name, visibility (`agent_only`, `llm_only`, or `both`), and a comma-separated list of its parameters. MCP-sourced tools should be noted as such.
- **Input / Output**: Summarize the expected inputs and outputs from the Interaction Model section of the plan.

Leave the Configuration, Dependencies, Deployment, and Development sections unchanged — they are generic and correct as-is.

### Step 10: Update Tests

Replace `tests/test_example_agent.py` with tests for the new agent. The example tests import `ResearchAssistant` and `ResearchReport` directly and will fail after Step 2 replaces them.

At minimum, the new test file should:

- Import the new agent class and any Pydantic models from `src/agent.py`
- Test that the agent can be instantiated with a mock config
- Test each tool's happy path and error cases
- Test that prompts load correctly
- Test that rules load correctly

Name the test file after the agent (e.g., `tests/test_ticket_triager.py`), or keep the `test_example_agent.py` name if you prefer — just replace the contents.

Also update `evals/evals.yaml` to match the new agent's eval cases from AGENT_PLAN.md. Replace the example Research Assistant cases with cases appropriate for the new agent.

### Step 11: Verify

Run through these checks:

1. **Syntax**: Run `python -c "import src.agent"` to verify the agent module imports cleanly.
2. **Tools**: Run `python -c "from fipsagents.baseagent.tools import ToolRegistry; r = ToolRegistry(); r.discover('./tools'); print([t.name for t in r.get_all()])"` to confirm tools are discoverable.
3. **Tests**: Run `make test` to execute the existing test suite. Fix any failures caused by replacing the example agent.
4. **Lint**: Run `make lint` if ruff is available.

If any check fails, fix the issue before proceeding. Do not leave the project in a broken state.

### Step 12: Summary

Present the developer with a summary of what was generated:

- Agent class name and location
- List of tools with their visibility
- List of prompts
- List of skills and rules (if any)
- Configuration changes made
- Test results

Ask if anything needs adjustment before moving on to `/exercise-agent`.

# Agent Development Rules

This project uses the BaseAgent framework. Follow these conventions:

- Your agent subclass lives in `src/agent.py`. The framework lives in `src/base_agent/` — do not edit it.
- Tools go in `tools/`, one file per tool, using the `@tool` decorator with a `visibility` parameter.
- Prompts go in `prompts/`, one file per prompt, as Markdown with YAML frontmatter.
- Use `self.use_tool()` for agent-code tool calls (plane 1). Use `self.tools.execute()` only in the LLM tool-call dispatch loop (plane 2).
- Run `make test` and `make lint` before committing.

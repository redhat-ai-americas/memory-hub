# Example Tools

This directory contains reference implementations of MCP tools showcasing various FastMCP features.

## What's Here

- **echo.py** - Simple synchronous tool example
- **advanced_examples.py** - Tools with complex parameters and validation
- **needs_elicitation.py** - Interactive tool requiring user input
- **needs_sampling.py** - Tool that uses LLM sampling

## Important Notes

⚠️ **These examples are NOT loaded by the server** - they are in a subdirectory that auto-discovery skips.

💡 **To use an example:**
1. Copy the file to `src/tools/` (parent directory)
2. Customize it for your needs
3. Auto-discovery will register it automatically

🧹 **To remove all examples:**
```bash
./remove_examples.sh
```

This prevents examples from cluttering your AI assistant's context window.

## Learning More

See `CLAUDE.md` and `AGENTS.md` for guidance on implementing tools.

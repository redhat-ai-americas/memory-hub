# Example Prompts

This directory contains reference implementations of MCP prompts.

## What's Here

- **analysis.py** - Code analysis prompts
- **documentation.py** - Documentation generation prompts
- **general.py** - General-purpose prompts

## Important Notes

⚠️ **These examples are NOT loaded by the server** - they are in a subdirectory that auto-discovery skips.

💡 **To use an example:**
1. Copy the file to `src/prompts/` (parent directory)
2. Customize it for your needs
3. Auto-discovery will register it automatically

🧹 **To remove all examples:**
```bash
./remove_examples.sh
```

This prevents examples from cluttering your AI assistant's context window.

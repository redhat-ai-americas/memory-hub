"""
Prompts package for the MCP server.

Prompt modules are automatically discovered and loaded by src/core/loaders.py.

To add a new prompt:
1. Create a new .py file in this directory
2. Import mcp from core.app: from core.app import mcp
3. Define your prompt function with @mcp.prompt() decorator
4. The loader will automatically discover and import it

To remove a prompt:
1. Simply delete the .py file
"""

"""
Tools package for the MCP server.

Tool modules are automatically discovered and loaded by src/core/loaders.py.

To add a new tool:
1. Create a new .py file in this directory
2. Import mcp from core.app: from core.app import mcp
3. Define your tool function with @mcp.tool() decorator
4. The loader will automatically discover and import it

To remove a tool:
1. Simply delete the .py file
"""

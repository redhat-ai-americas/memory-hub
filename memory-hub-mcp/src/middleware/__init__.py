"""
Middleware package for the MCP server.

Middleware modules are automatically discovered and loaded by src/core/loaders.py.

Middleware classes wrap MCP operations to add cross-cutting concerns like logging,
authentication, rate limiting, etc.

Middleware should inherit from fastmcp.server.middleware.Middleware and override
specific hook methods (on_call_tool, on_request, etc.).

To add new middleware:
1. Create a new .py file in this directory
2. Import Middleware: from fastmcp.server.middleware import Middleware
3. Define your middleware class inheriting from Middleware
4. The loader will automatically discover and register it

To remove middleware:
1. Simply delete the .py file
"""

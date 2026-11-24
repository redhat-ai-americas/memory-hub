# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Adding a new tool — REGISTER IT IN main.py

**This server does NOT use the dynamic loader.** `src/main.py` (lines 12–46) statically imports each tool module and calls `mcp.add_tool()` explicitly. The comment in `main.py` explains why: the template's `UnifiedMCPServer`/`load_all` was designed for FastMCP 2 and doesn't register tools correctly in v3.

**When you add a new tool, you MUST also:**
1. Add `from src.tools.<name> import <name>` to the imports in `src/main.py`
2. Add `<name>` to the list passed to `mcp.add_tool()`

If you forget, the tool file will deploy to the container and the loader will silently skip it — `list_tools` will not include it and there will be no error in the logs. Verify with mcp-test-mcp after deployment.

## Build and Test Commands

```bash
# Install dependencies (creates .venv)
make install

# Run server locally (STDIO mode with hot-reload)
make run-local

# Run all tests
make test
# Or directly:
.venv/bin/pytest tests/ -v

# Run single test file
.venv/bin/pytest tests/test_loaders.py -v

# Run tests matching pattern
.venv/bin/pytest tests/ -k "test_auth" -v

# Test with cmcp (requires separate terminal)
make test-local
# Or: cmcp ".venv/bin/python -m src.main" tools/list

# Deploy to OpenShift
make deploy PROJECT=my-project

# Build container for OpenShift (Mac)
podman build --platform linux/amd64 -f Containerfile -t my-mcp:latest .
```

## Architecture Overview

### Static Tool Registration

This server uses **static registration** in `src/main.py` (not the template's dynamic loader). Each tool module is explicitly imported and registered via `mcp.add_tool()`. The template's `UnifiedMCPServer`/`load_all` pipeline exists in `src/core/` but is not the active registration path -- it was designed for FastMCP 2 and does not register tools correctly in v3.

1. **Entry point**: `src/main.py` imports each tool and calls `mcp.add_tool()` explicitly
2. **Central MCP instance**: `src/core/app.py` exports the shared `mcp` FastMCP instance
3. **Transport**: `src/core/server.py` handles STDIO vs HTTP transport selection

Tools use `@mcp.tool` decorators referencing the shared `mcp` instance from `src/core/app.py`. The decorator registers the tool on the instance, and `main.py`'s explicit `add_tool()` calls ensure they appear in `list_tools`.

### Import Convention

**IMPORTANT**: Always use the `src.` prefix for all imports within this project:

```python
# Correct - always use src. prefix
from src.core.app import mcp
from src.core.auth import requires_scopes
from src.tools.my_tool import my_tool

# Incorrect - do NOT use short-form imports
from core.app import mcp  # WRONG
from tools.my_tool import my_tool  # WRONG
```

This convention ensures consistent imports across:
- Component files in `src/tools/`, `src/resources/`, `src/prompts/`, `src/middleware/`
- Test files in `tests/`
- The dynamic loader system

The `conftest.py` at project root adds the project directory to `sys.path`, enabling `src.*` imports.

### Module Structure

```
src/
├── core/
│   ├── app.py        # Creates shared `mcp` FastMCP instance
│   ├── server.py     # UnifiedMCPServer: load + run orchestration
│   ├── loaders.py    # Dynamic discovery of tools/resources/prompts/middleware
│   ├── auth.py       # JWT authentication helpers
│   └── logging.py    # Logging configuration
├── tools/            # Tool implementations (flat directory)
├── resources/        # Resource implementations (supports subdirectories)
├── prompts/          # Python-based prompt definitions
└── middleware/       # Middleware classes (extend FastMCP Middleware base)
```

### Transport Modes

- **STDIO** (local): `MCP_TRANSPORT=stdio` - for cmcp testing
- **HTTP** (OpenShift): `MCP_TRANSPORT=http` - streamable-http on port 8080

## Testing FastMCP Decorated Tools

In FastMCP 3, `@mcp.tool(...)` returns the function directly, so tests import the tool and call it — no `.fn` access needed:

```python
from src.tools.my_tool import my_tool

@pytest.mark.asyncio
async def test_my_tool():
    result = await my_tool(param1="value1")
    assert result == "expected"
```

## Dependency Management

Dependencies must be listed in BOTH files:
- `pyproject.toml` - for local `pip install -e .`
- `requirements.txt` - for container builds

## Adding Components

### Tools (`src/tools/`)

```python
from typing import Annotated
from pydantic import Field
from fastmcp import Context
from src.core.app import mcp

@mcp.tool
async def my_tool(
    param: Annotated[str, Field(description="Parameter description")],
    ctx: Context = None,
) -> str:
    """Tool description for the LLM."""
    return f"Result: {param}"
```

### Resources (`src/resources/`)

Supports subdirectories. Files are auto-discovered.

```python
from src.core.app import mcp

@mcp.resource("weather://{city}/current")
async def get_weather(city: str) -> dict:
    """Weather for a city."""
    return {"city": city, "temperature": 22}
```

### Prompts (`src/prompts/`)

```python
from pydantic import Field
from src.core.app import mcp

@mcp.prompt
def my_prompt(
    query: str = Field(description="User query"),
) -> str:
    """Purpose of this prompt."""
    return f"Please answer: {query}"
```

**Type annotations**: Use parameterized types (`dict[str, str]`, `list[str]`) - never bare `dict` or `list`.

### Middleware (`src/middleware/`)

```python
from fastmcp.server.middleware import Middleware, MiddlewareContext

class MyMiddleware(Middleware):
    async def on_call_tool(self, context: MiddlewareContext, call_next):
        # Pre-execution
        result = await call_next(context)
        # Post-execution
        return result
```

## Prompt Return Types

- `str` - Simple string (default)
- `PromptMessage` - Structured message with role
- `list[PromptMessage]` - Multi-turn conversation

## MCP Development Workflow

This server is mature (14 tools, 3 profiles, static registration). Initial scaffolding is complete. The slash commands below are for **adding new tools**, not for building from scratch.

### Adding New Tools

```
/plan-tools              → Update TOOLS_PLAN.md with new tool designs
        ↓
/create-tools            → Generate scaffolds and implement
        ↓
/exercise-tools          → Test ergonomics by role-playing as consuming agent
        ↓
/deploy-mcp PROJECT=x    → Deploy to OpenShift, verify with mcp-test-mcp
```

| Command | Purpose |
|---------|---------|
| `/plan-tools` | Design new tools, update `TOOLS_PLAN.md` |
| `/create-tools` | Generate scaffolds with `fips-agents`, implement |
| `/exercise-tools` | Role-play as consuming agent, test usability |
| `/deploy-mcp PROJECT=x` | Pre-flight checks, deploy, verify |

## Known Issues and Fixes

### File Permission Issue (Auto-Fixed)

**Problem**: Claude Code's Write tool creates files with `600` permissions (owner-only read/write) as a security measure. OpenShift containers run as arbitrary non-root UIDs that need at least `644` (world-readable) permissions.

**Symptoms**: MCP server starts but reports 0 tools loaded:
```
PermissionError: [Errno 13] Permission denied: '/opt/app-root/src/src/core/some_file.py'
Loaded: {'tools': 0, 'resources': 0, 'prompts': 0, 'middleware': 0}
```

**Automatic Fixes in Place**:
1. **Containerfile**: `RUN find ./src -name "*.py" -exec chmod 644 {} \;` ensures correct permissions in every build
2. **deploy/build-context.sh**: Fixes permissions in the build context and reports how many files were fixed

**Manual Fix** (if needed):
```bash
find src -name "*.py" -perm 600 -exec chmod 644 {} \;
```

**Why This Happens**: This is Claude Code security behavior, not OS behavior. The Write tool intentionally creates files with restrictive permissions to prevent accidental exposure of sensitive content. The Containerfile and `deploy/build-context.sh` fixes ensure this doesn't break OpenShift deployments.

### Import Namespace Issue

**Problem**: Using relative imports or path manipulation can create dual FastMCP instances.

**Solution**: Always use `src.` prefixed absolute imports (see Import Convention section above).

## Testing MCP Servers

### Local Testing with cmcp

```bash
# Start server in STDIO mode
make run-local

# In another terminal, test tools
cmcp ".venv/bin/python -m src.main" tools/list
cmcp ".venv/bin/python -m src.main" tools/call my_tool '{"param": "value"}'
```

### Remote Testing with mcp-test-mcp

After deployment, use `mcp-test-mcp` to verify the server works:

```bash
# List available tools
mcp-test-mcp list_tools --server-url https://<route>/mcp/

# Test a specific tool
mcp-test-mcp test_tool --server-url https://<route>/mcp/ \
  --tool-name my_tool \
  --params '{"param": "value"}'
```

**Important**: If `mcp-test-mcp` tools are not available, ask to have it enabled before testing deployed MCP servers.

## Deployment Guidelines

### OpenShift Deployment

Each MCP server should deploy to its own OpenShift project to avoid naming collisions:

```bash
make deploy PROJECT=my-mcp-server
```

### Pre-deployment Checklist

- [ ] All tests pass: `.venv/bin/pytest tests/ -v --ignore=tests/examples/`
- [ ] Permissions fixed: `find src -name "*.py" -perm 600 -exec chmod 644 {} \;`
- [ ] Dependencies in both `pyproject.toml` and `requirements.txt`
- [ ] No hardcoded secrets in source files
- [ ] `.dockerignore` excludes `__pycache__/`, `.venv/`, `tests/`

### Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `MCP_TRANSPORT` | `stdio` | Transport mode: `stdio` or `http` |
| `MCP_HTTP_HOST` | `127.0.0.1` | HTTP bind address |
| `MCP_HTTP_PORT` | `8000` | HTTP port |
| `MCP_HTTP_PATH` | `/mcp/` | HTTP endpoint path |
| `MCP_LOG_LEVEL` | `INFO` | Logging level |
| `MCP_HOT_RELOAD` | `0` | Enable hot-reload for development |
| `MCP_SERVER_NAME` | `fastmcp-unified` | Server name in MCP responses |

## Context Management

When working on this project, use subagents to preserve context:

- **Long terminal output** (builds, deploys): Use `terminal-worker` subagent
- **Parallel tool implementation**: Use `claude-worker` subagents (one per tool)
- **Research tasks**: Use appropriate specialized subagents

This prevents context compression from losing important information about issues encountered.

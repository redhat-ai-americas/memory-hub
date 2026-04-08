# FastMCP Server Template

A production-ready MCP (Model Context Protocol) server template with dynamic tool/resource loading, Python decorator-based prompts, and seamless OpenShift deployment.

## Features

- 🔧 **Dynamic tool/resource loading** via decorators
- 📁 **Resource subdirectories** for organizing related resources
- 📝 **Python-based prompts** with type safety and FastMCP decorators
- 🔀 **Middleware support** for cross-cutting concerns
- 🏗️ **Generator system** for scaffolding new components with non-interactive CLI
- 🔄 **Selective updates** - patch infrastructure without losing custom code
- 🚀 **One-command OpenShift deployment**
- 🔥 **Hot-reload** for local development
- 🧪 **Local STDIO** and **OpenShift HTTP** transports
- 🔐 **JWT authentication** (optional) with scope-based authorization
- ✅ **Full test suite** with pytest

## Quick Start

### Local Development

```bash
# Install and run locally
make install
make run-local

# Test with cmcp (in another terminal)
cmcp ".venv/bin/python -m src.main" tools/list
```

### Deploy to OpenShift

```bash
# IMPORTANT: Remove examples before first deployment
./remove_examples.sh

# One-command deployment
make deploy

# Or deploy to specific project
make deploy PROJECT=my-project
```

> **Note**: Running `./remove_examples.sh` before deployment removes example code and cache files, significantly reducing build context size and preventing deployment timeouts.

## Claude Code Workflow

This template includes slash commands for Claude Code that provide a structured workflow for developing MCP tools.

### Recommended Sequence

```
/plan-tools          →  TOOLS_PLAN.md (planning, no code)
        ↓
/create-tools        →  Generate + implement tools in parallel
        ↓
/exercise-tools      →  Test ergonomics as consuming agent
        ↓
/deploy-mcp PROJECT=x  →  Deploy to OpenShift (optional)
```

### Slash Commands

| Command | Description |
|---------|-------------|
| `/plan-tools` | Reads [Anthropic's tool design guidance](https://www.anthropic.com/engineering/writing-tools-for-agents) and your proposal, then creates `TOOLS_PLAN.md` with tool specifications. Planning only - no code. |
| `/create-tools` | Reads `TOOLS_PLAN.md`, generates scaffolds with `fips-agents`, and implements each tool in parallel using subagents for efficiency. |
| `/exercise-tools` | Role-plays as the agent that will consume these tools, testing ergonomics, error messages, and composability. Provides structured feedback and makes improvements. |
| `/deploy-mcp PROJECT=name` | Runs pre-flight checks (permissions, tests), deploys to OpenShift, and verifies with `mcp-test-mcp`. |

### When to Use Each Command

- **Starting a new MCP server**: Run `/plan-tools` first to design your tools before writing any code
- **After planning is approved**: Run `/create-tools` to implement everything in parallel
- **Before deployment**: Run `/exercise-tools` to catch usability issues
- **For remote MCP servers**: Run `/deploy-mcp` to deploy to OpenShift

See [CLAUDE.md](CLAUDE.md) for detailed documentation on the workflow, known issues, and troubleshooting.

## Project Structure

```
├── src/
│   ├── core/           # Core server components
│   ├── tools/          # Tool implementations
│   ├── resources/      # Resource implementations (supports subdirectories)
│   │   ├── country_profiles/   # Example: organized by category
│   │   ├── checklists/
│   │   └── emergency_protocols/
│   ├── prompts/        # Python-based prompt definitions
│   └── middleware/     # Middleware implementations
├── tests/              # Test suite
├── .fips-agents-cli/   # Generator templates
├── .template-info      # Template version tracking (for updates)
├── Containerfile       # Container definition
├── deploy/             # OpenShift deploy assets
│   ├── deploy.sh       #   Canonical deploy entrypoint (called by `make deploy`)
│   ├── build-context.sh#   Stages MCP src + memoryhub_core into .build-context/
│   ├── openshift.yaml  #   BuildConfig, Deployment, Service, Route, Secret
│   └── users-configmap.yaml
├── requirements.txt    # Python dependencies
└── Makefile           # Common tasks
```

## Development

### Adding Tools

Create a Python file in `src/tools/`. Tools support rich type annotations, validation, and metadata:

```python
from typing import Annotated
from pydantic import Field
from fastmcp import Context
from fastmcp.exceptions import ToolError
from src.core.app import mcp

@mcp.tool(
    annotations={
        "readOnlyHint": True,
        "idempotentHint": True,
        "openWorldHint": False,
    }
)
async def my_tool(
    param: Annotated[str, Field(description="Parameter description", min_length=1, max_length=100)],
    ctx: Context = None,
) -> str:
    """Tool description for the LLM."""
    await ctx.info("Processing request")

    if not param.strip():
        raise ToolError("Parameter cannot be empty")

    return f"Result: {param}"
```

**Best Practices:**
- Use `Annotated` for parameter descriptions (FastMCP 2.11.0+)
- Add Pydantic `Field` constraints for validation
- Use tool `annotations` for hints about behavior
- Always include `ctx: Context = None` for logging and capabilities
- Raise `ToolError` for user-facing validation errors
- Use structured output (dataclasses) for complex results

See [TOOLS_GUIDE.md](docs/TOOLS_GUIDE.md) for comprehensive examples and patterns.

**Generator examples:**

> **Note**: `fips-agents` is a global CLI tool (installed via pipx). Run it directly - do NOT use `.venv/bin/fips-agents`.

```bash
# Simple tool
fips-agents generate tool my_tool \
    --description "Tool description" \
    --async

# Tool with context
fips-agents generate tool search_documents \
    --description "Search through documents" \
    --async \
    --with-context

# Tool with authentication
fips-agents generate tool protected_operation \
    --description "Protected operation" \
    --async \
    --with-auth

# Tool with parameters from JSON file
fips-agents generate tool complex_tool \
    --description "Complex tool with multiple params" \
    --params params.json \
    --with-context

# Advanced tool with all options
fips-agents generate tool advanced_tool \
    --description "Advanced tool example" \
    --async \
    --with-context \
    --with-auth \
    --return-type "dict" \
    --read-only \
    --idempotent
```

### Adding Resources

Resources can be organized in subdirectories for better structure. Create files in `src/resources/` or any subdirectory:

**Simple resource:**
```python
from src.core.app import mcp

@mcp.resource("resource://my-resource")
async def get_my_resource() -> str:
    return "Resource content"
```

**JSON resource with metadata:**
```python
from src.core.app import mcp

@mcp.resource(
    "data://config",
    mime_type="application/json",
    description="Application configuration data"
)
async def get_config() -> dict:
    return {"version": "1.0", "features": ["tools", "resources"]}
```

**Resource template (parameterized):**
```python
from src.core.app import mcp

@mcp.resource("weather://{city}/current")
async def get_weather(city: str) -> dict:
    """Weather information for a specific city."""
    return {"city": city, "temperature": 22, "condition": "Sunny"}
```

**Organizing resources in subdirectories:**
```
src/resources/
├── country_profiles/
│   ├── __init__.py
│   ├── japan.py          # country-profiles://JP
│   └── france.py         # country-profiles://FR
├── checklists/
│   ├── __init__.py
│   └── travel.py         # travel-checklists://first-trip
└── emergency_protocols/
    ├── __init__.py
    └── passport.py       # emergency-protocols://passport-lost
```

**Generator examples:**
```bash
# Simple resource
fips-agents generate resource my_resource \
    --description "My resource description" \
    --uri "resource://my-resource" \
    --mime-type "text/plain"

# JSON resource
fips-agents generate resource config_data \
    --description "Application configuration" \
    --uri "data://config" \
    --mime-type "application/json"

# Resource in subdirectory (creates country_profiles/japan.py)
fips-agents generate resource country-profiles/japan \
    --description "Japan country profile" \
    --uri "country-profiles://JP" \
    --mime-type "application/json"

# Resource template with async and context
fips-agents generate resource weather \
    --async \
    --with-context \
    --description "Weather data by city" \
    --uri "weather://{city}/current" \
    --mime-type "application/json"
```

Subdirectories are automatically discovered by the loader - no manual registration needed!

### Creating Prompts

Create Python files in `src/prompts/`. Prompts support multiple return types, async operations, context access, and metadata:

**Basic String Prompt:**
```python
from pydantic import Field
from src.core.app import mcp

@mcp.prompt
def my_prompt(
    query: str = Field(description="User query"),
) -> str:
    """Purpose of this prompt"""
    return f"Please answer: {query}"
```

**Async Prompt with Context:**
```python
from pydantic import Field
from fastmcp import Context
from src.core.app import mcp

@mcp.prompt
async def fetch_prompt(
    url: str = Field(description="Data source URL"),
    ctx: Context,
) -> str:
    """Fetch data and create prompt"""
    # Perform async operations
    return f"Analyze data from {url}"
```

**Structured Message Prompt:**
```python
from pydantic import Field
from fastmcp.prompts.prompt import PromptMessage, TextContent
from src.core.app import mcp

@mcp.prompt
def structured_prompt(
    task: str = Field(description="Task description"),
) -> PromptMessage:
    """Create structured message"""
    return PromptMessage(
        role="user",
        content=TextContent(type="text", text=f"Task: {task}")
    )
```

**Advanced with Metadata:**
```python
from pydantic import Field
from src.core.app import mcp

@mcp.prompt(
    name="custom_name",
    title="Human Readable Title",
    description="Custom description",
    tags={"analysis", "reporting"},
    meta={"version": "1.0", "author": "team"}
)
def advanced_prompt(
    data: dict[str, str] = Field(description="Data to process"),
) -> str:
    """Advanced prompt with full metadata"""
    return f"Analyze: {data}"
```

**Generator Examples:**
```bash
# Basic prompt
fips-agents generate prompt summarize_text \
    --description "Summarize text content"

# Async with Context
fips-agents generate prompt fetch_and_analyze \
    --async --with-context \
    --return-type PromptMessage

# With parameters file
fips-agents generate prompt analyze_data \
    --params params.json --with-schema

# Advanced with metadata
fips-agents generate prompt report_generator \
    --async --with-context \
    --prompt-name "generate_report" \
    --title "Report Generator" \
    --tags "reporting,analysis" \
    --meta '{"version": "2.0"}'
```

**Return Types:**
- `str` - Simple string prompt (default)
- `PromptMessage` - Structured message with role
- `list[PromptMessage]` - Multi-turn conversation
- `PromptResult` - Full prompt result object

See [CLAUDE.md](CLAUDE.md) for comprehensive prompt generation documentation and `src/prompts/` for working examples.

### Adding Middleware

Create a file in `src/middleware/`:

```python
from typing import Any, Callable
from fastmcp import Context
from src.core.app import mcp

@mcp.middleware()
async def my_middleware(
    ctx: Context,
    next_handler: Callable,
    *args: Any,
    **kwargs: Any
) -> Any:
    # Pre-execution logic
    result = await next_handler(*args, **kwargs)
    # Post-execution logic
    return result
```

Middleware wraps tool execution to add cross-cutting concerns like logging, authentication, rate limiting, caching, etc.

See `src/middleware/logging_middleware.py` for a working example and `src/middleware/auth_middleware.py` for a commented authentication pattern.

**Generator examples:**
```bash
# Async middleware
fips-agents generate middleware logging_middleware \
    --description "Request logging middleware" \
    --async

# Sync middleware
fips-agents generate middleware rate_limiter \
    --description "Rate limiting middleware" \
    --sync
```

## Testing

### Local Testing (STDIO)

```bash
# Run server
make run-local

# Test with cmcp
make test-local

# Run unit tests
make test
```

### OpenShift Testing (HTTP)

```bash
# Deploy
make deploy

# Test with MCP Inspector
npx @modelcontextprotocol/inspector https://<route-url>/mcp/
```

See [TESTING.md](TESTING.md) for detailed testing instructions.

## Keeping Projects Updated

This template is actively maintained with improvements to infrastructure, generators, and documentation. You can selectively update your project from template changes without losing your custom code.

### Check for Updates

```bash
# See what's changed since project creation
fips-agents patch check
```

This shows available updates organized by category (generators, core, docs, build).

### Update Specific Categories

```bash
# Update generator templates (safe - your code is untouched)
fips-agents patch generators

# Update core infrastructure (shows diffs, asks for approval)
fips-agents patch core

# Update documentation and examples (safe)
fips-agents patch docs

# Update build and deployment files (shows diffs, asks for approval)
fips-agents patch build

# Preview changes without applying (dry run)
fips-agents patch core --dry-run
```

### Update Everything

```bash
# Interactively update all categories
fips-agents patch all

# Skip confirmation prompts (use with caution)
fips-agents patch all --skip-confirmation
```

### What Gets Updated

**Automatically updated (no confirmation):**
- `.fips-agents-cli/generators/` - Code generator templates
- `docs/` - Documentation files
- Example files in `src/*/examples/`

**Asks before updating (shows diffs):**
- `src/core/loaders.py` - Component discovery system
- `src/core/server.py` - Server bootstrap code
- `src/*/__ init__.py` - Package initialization files
- `Makefile`, `Containerfile`, `openshift.yaml` - Build files

**Never updated (your code is protected):**
- `src/tools/*.py` - Your tool implementations
- `src/resources/*.py` - Your resource implementations
- `src/prompts/*.py` - Your prompt definitions
- `src/middleware/*.py` - Your middleware implementations
- `tests/` - Your test files
- `README.md`, `pyproject.toml`, `.env` - Project configuration
- `src/core/app.py`, `src/core/auth.py`, `src/core/logging.py` - User-customizable core files

### Example: Adding New Template Capabilities

Imagine the template adds new authentication capabilities in a future update:

```bash
# Check what's new
fips-agents patch check

# Pull in updated generators so you can generate auth-enabled tools
fips-agents patch generators

# Review and apply core infrastructure updates
fips-agents patch core  # Shows diffs, you decide what to apply

# Your existing tools, resources, and prompts remain untouched!
```

The `.template-info` file tracks which template version your project was created from, enabling smart updates.

## Transport Architecture

MCP supports multiple transport protocols. **The server defines which transport to expose**—clients must connect using the matching transport type.

### How It Works

The `MCP_TRANSPORT` environment variable controls which transport the server runs:

| Transport | Use Case | Client Connection |
|-----------|----------|-------------------|
| `stdio` | Local development, CLI tools like `cmcp` | Spawns server as subprocess |
| `http` | Remote access, OpenShift deployment | HTTP request to `http://host:port/mcp/` |

The same codebase supports both transports. The server reads `MCP_TRANSPORT` at startup and exposes only that transport—there's no negotiation or auto-detection.

### Local Development (STDIO)

```bash
# Server runs in STDIO mode (default)
MCP_TRANSPORT=stdio .venv/bin/python -m src.main

# Client spawns the server as a subprocess
cmcp ".venv/bin/python -m src.main" tools/list
```

STDIO is ideal for local testing because the client manages the server lifecycle directly.

### Remote Deployment (HTTP)

```bash
# Server runs in HTTP mode
MCP_TRANSPORT=http MCP_HTTP_HOST=0.0.0.0 MCP_HTTP_PORT=8080 python -m src.main

# Client connects via HTTP
# (configure your MCP client to use the HTTP endpoint)
```

In OpenShift, the Containerfile sets `MCP_TRANSPORT=http` automatically. The Route exposes the `/mcp/` endpoint with TLS termination.

### Client Configuration

Your MCP client configuration must specify the correct transport:

**For STDIO (local):**
```json
{
  "mcpServers": {
    "my-server": {
      "command": ".venv/bin/python",
      "args": ["-m", "src.main"]
    }
  }
}
```

**For HTTP (remote):**
```json
{
  "mcpServers": {
    "my-server": {
      "url": "https://my-server-route.apps.cluster.example.com/mcp/"
    }
  }
}
```

## Environment Variables

### Local Development
- `MCP_TRANSPORT=stdio` - Use STDIO transport
- `MCP_HOT_RELOAD=1` - Enable hot-reload

### OpenShift Deployment
- `MCP_TRANSPORT=http` - Use HTTP transport (set in Containerfile)
- `MCP_HTTP_HOST=0.0.0.0` - HTTP server host
- `MCP_HTTP_PORT=8080` - HTTP server port
- `MCP_HTTP_PATH=/mcp/` - HTTP endpoint path

### Optional Authentication
- `MCP_AUTH_JWT_SECRET` - JWT secret for symmetric signing
- `MCP_AUTH_JWT_PUBLIC_KEY` - JWT public key for asymmetric
- `MCP_REQUIRED_SCOPES` - Comma-separated required scopes

## Available Commands

```bash
make help         # Show all available commands
make install      # Install dependencies
make run-local    # Run locally with STDIO
make test         # Run test suite
make deploy       # Deploy to OpenShift
make clean        # Clean up OpenShift deployment
```

## Architecture

The server uses FastMCP 2.x with:
- Dynamic component loading at startup
- Hot-reload in development mode
- Python decorator-based prompts with type safety
- Automatic component registration via decorators (`@mcp.tool()`, `@mcp.resource()`, `@mcp.prompt()`, `@mcp.middleware()`)
- Middleware for cross-cutting concerns
- Generator system with Jinja2 templates for scaffolding
- Support for both STDIO (local) and HTTP (OpenShift) transports

See [ARCHITECTURE.md](ARCHITECTURE.md) for detailed architecture information.

## Requirements

- Python 3.11+
- OpenShift CLI (`oc`) for deployment
- cmcp for local testing: `pip install cmcp`

## Contributing and license

This server is part of the [memory-hub](https://github.com/rdwj/memory-hub) monorepo. See the [root README](../README.md) for contribution guidelines and the repository-level [LICENSE](../LICENSE) (Apache 2.0).
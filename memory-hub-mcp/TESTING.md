# Testing Guide

This guide covers how to test the MCP server both locally and on OpenShift.

## Prerequisites

### Local Testing
- Python 3.11+
- cmcp: `pip install cmcp`

### OpenShift Testing
- OpenShift CLI (`oc`)
- mcp-test-mcp MCP server (for automated testing)
- MCP Inspector: `npx @modelcontextprotocol/inspector` (for interactive testing)

## Local Testing (STDIO Transport)

### 1. Install and Run

```bash
# Install dependencies
make install

# Run the server
make run-local
```

### 2. Test with cmcp

In another terminal:

```bash
# List available tools
cmcp ".venv/bin/python -m src.main" tools/list

# Call a tool with parameters
cmcp ".venv/bin/python -m src.main" tools/call my_tool '{"param": "value"}'

# List prompts
cmcp ".venv/bin/python -m src.main" prompts/list

# Get a specific prompt
cmcp ".venv/bin/python -m src.main" prompts/get name=summarize

# List resources
cmcp ".venv/bin/python -m src.main" resources/list

# Read a resource
cmcp ".venv/bin/python -m src.main" resources/read uri=resource://my-resource
```

### 3. Quick Test

```bash
# Run automated local test
make test-local
```

## OpenShift Testing (HTTP Transport)

### 1. Pre-deployment

Before first deployment, remove example code to reduce build context:

```bash
./remove_examples.sh
```

### 2. Deploy to OpenShift

```bash
# Deploy to specific project (recommended - each MCP server gets its own project)
make deploy PROJECT=my-mcp-server

# Or deploy to default project
make deploy
```

### 3. Get the Server URL

```bash
# Get the route
oc get route mcp-server -o jsonpath='{.spec.host}'
```

### 4. Test with mcp-test-mcp (Recommended)

Use `mcp-test-mcp` to verify the deployed server works:

```bash
# List available tools
mcp-test-mcp list_tools --server-url https://<route>/mcp/

# Test a specific tool
mcp-test-mcp test_tool --server-url https://<route>/mcp/ \
  --tool-name my_tool \
  --params '{"param": "value"}'
```

> **Note**: If `mcp-test-mcp` tools are not available, ask to have them enabled before testing deployed MCP servers.

### 5. Test with MCP Inspector (Interactive)

```bash
# Launch MCP Inspector
npx @modelcontextprotocol/inspector https://<route-url>/mcp/
```

The Inspector provides a web UI to:
- Browse available tools, prompts, and resources
- Execute tools interactively
- Test prompt generation
- View server capabilities

### 6. Test with curl (Advanced)

```bash
# Get server info (streamable-http endpoint)
curl -X POST https://<route-url>/mcp/ \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"initialize","params":{"protocolVersion":"1.0.0","capabilities":{},"clientInfo":{"name":"test","version":"1.0.0"}},"id":1}'
```

## Unit Tests

Run the pytest suite:

```bash
# Run all tests
make test

# Run with verbose output
.venv/bin/pytest tests/ -v

# Run specific test file
.venv/bin/pytest tests/test_loaders.py -v

# Run tests matching a pattern
.venv/bin/pytest tests/ -k "test_auth" -v

# Run tests ignoring examples (recommended before deployment)
.venv/bin/pytest tests/ -v --ignore=tests/examples/

# Run with coverage
.venv/bin/pytest tests/ --cov=src --cov-report=html
```

### Testing FastMCP Decorated Functions

FastMCP decorators wrap functions in special objects. Access the underlying function via `.fn` for direct testing:

```python
from src.tools.my_tool import my_tool

my_tool_fn = my_tool.fn  # Access underlying function

@pytest.mark.asyncio
async def test_my_tool():
    result = await my_tool_fn(param1="value1")
    assert result == "expected"
```

### Import Convention

Always use the `src.` prefix for imports in test files:

```python
# Correct
from src.core.app import mcp
from src.tools.my_tool import my_tool

# Incorrect - will cause import errors
from core.app import mcp  # WRONG
from tools.my_tool import my_tool  # WRONG
```

## Troubleshooting

### Local Issues

1. **cmcp not found**
   ```bash
   pip install cmcp
   ```

2. **Module not found errors**
   ```bash
   # Ensure virtual environment is activated
   source .venv/bin/activate
   ```

3. **Permission denied (deploy.sh)**
   ```bash
   chmod +x deploy.sh
   ```

### OpenShift Issues

1. **Not logged in**
   ```bash
   oc login <cluster-url>
   ```

2. **Build fails**
   ```bash
   # Check build logs
   oc logs -f bc/mcp-server
   ```

3. **Pod not running**
   ```bash
   # Check pod status
   oc get pods

   # Check pod logs
   oc logs <pod-name>
   ```

4. **Route not accessible**
   ```bash
   # Verify route exists
   oc get route mcp-server

   # Check service
   oc get svc mcp-server
   ```

5. **Server reports 0 tools loaded (file permissions)**

   Files created by Claude Code subagents may have `600` permissions, preventing the container from reading them.

   Symptoms:
   ```
   PermissionError: [Errno 13] Permission denied: '/opt/app-root/src/src/tools/some_tool.py'
   Loaded: {'tools': 0, 'resources': 0, 'prompts': 0, 'middleware': 0}
   ```

   Fix:
   ```bash
   find src -name "*.py" -perm 600 -exec chmod 644 {} \;
   ```

   > **Note**: The `/deploy-mcp` slash command runs this automatically.

## Environment Variables

### Local Development
```bash
export MCP_TRANSPORT=stdio
export MCP_HOT_RELOAD=1
```

### OpenShift Deployment
The following are set automatically in the container:
- `MCP_TRANSPORT=http`
- `MCP_HTTP_HOST=0.0.0.0`
- `MCP_HTTP_PORT=8080`
- `MCP_HTTP_PATH=/mcp/`

## Ergonomic Testing with /exercise-tools

Use the `/exercise-tools` slash command to test tool usability from an agent's perspective:

```bash
/exercise-tools
```

This command:

- Role-plays as the consuming agent
- Tests tool composability and error handling
- Provides structured feedback on usability issues
- Suggests improvements based on real usage patterns

## Pre-deployment Checklist

Before deploying to OpenShift:

- [ ] All tests pass: `.venv/bin/pytest tests/ -v --ignore=tests/examples/`
- [ ] Permissions fixed: `find src -name "*.py" -perm 600 -exec chmod 644 {} \;`
- [ ] Dependencies in both `pyproject.toml` and `requirements.txt`
- [ ] No hardcoded secrets in source files
- [ ] `.dockerignore` excludes `__pycache__/`, `.venv/`, `tests/`
- [ ] Examples removed: `./remove_examples.sh`

## Tips

1. **Hot Reload**: Local development includes hot-reload for tools and prompts
2. **Verbose Mode**: Use `-v` flag with cmcp for detailed request/response
3. **Multiple Projects**: Deploy to different OpenShift projects for testing
4. **Clean Up**: Use `make clean PROJECT=<name>` to remove deployments
5. **Workflow**: Use `/plan-tools` → `/create-tools` → `/exercise-tools` → `/deploy-mcp` for structured development

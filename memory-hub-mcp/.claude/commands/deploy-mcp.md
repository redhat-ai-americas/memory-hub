---
description: Deploy MCP server to OpenShift with pre-flight checks
---

# Deploy MCP Server

You are deploying an MCP server to OpenShift. This command handles pre-deployment checks and delegates the build/deploy to a terminal-worker subagent.

## Arguments

- **PROJECT**: (required) The OpenShift project/namespace name (e.g., `weather-mcp`)

## Prerequisites

- Tools should be implemented and tested (`/create-tools`)
- Ergonomics should be verified (`/exercise-tools`)
- `mcp-test-mcp` MCP server must be available for verification

## Your Task

### Step 1: Pre-deployment Checks

Run these checks before deployment:

#### A. Permission Fix
```bash
find src -name "*.py" -perm 600 -exec chmod 644 {} \;
```

#### B. Verify .dockerignore
Check that `.dockerignore` excludes:
- `__pycache__/`
- `.venv/`
- `tests/`
- `.env`

#### C. Run Tests
```bash
.venv/bin/pytest tests/ -v --ignore=tests/examples/
```
If tests fail, STOP and report. Do not deploy broken code.

#### D. Check for Secrets
```bash
# Quick check for common patterns
grep -r "password\s*=" src/ --include="*.py" || true
grep -r "api_key\s*=" src/ --include="*.py" || true
grep -r "secret\s*=" src/ --include="*.py" || true
```
If found, warn user and ask for confirmation.

### Step 2: Delegate Deployment to Terminal Worker

Use the Task tool to launch a `terminal-worker` subagent with this prompt:

```
Deploy the MCP server to OpenShift.

Project/Namespace: <PROJECT>

Run these commands in sequence:
1. make deploy PROJECT=<PROJECT>
2. Wait for rollout: oc rollout status deployment/<deployment-name> -n <PROJECT> --timeout=300s
3. Get the route: oc get route -n <PROJECT> -o jsonpath='{.items[0].spec.host}'

Report:
- Whether deployment succeeded
- The route URL if successful
- Any errors encountered
```

### Step 3: Verify Deployment

After the terminal-worker reports success:

#### A. Check if mcp-test-mcp is Available

Look for these tools in your available MCP tools:
- `mcp__mcp-test-mcp__test_tool`
- `mcp__mcp-test-mcp__list_tools`

If NOT available:
```
STOP: mcp-test-mcp is not available. Please enable it and try again.
I need mcp-test-mcp to verify the deployed MCP server works correctly.
```

#### B. Verify Tools with mcp-test-mcp

Use mcp-test-mcp to:
1. List tools on the deployed server
2. Test at least one tool with valid input
3. Test error handling with invalid input

Example verification:
```
# List tools
mcp-test-mcp list_tools --server-url https://<route>/mcp/

# Test a tool
mcp-test-mcp test_tool --server-url https://<route>/mcp/ --tool-name get_weather --params '{"location": "Austin, TX"}'
```

### Step 4: Report Results

Provide a deployment summary:

```markdown
## Deployment Summary

**Project**: <PROJECT>
**Route**: https://<route>
**Status**: SUCCESS / FAILED

### Pre-deployment Checks
- [x] Permissions fixed
- [x] .dockerignore verified
- [x] Tests passed (N tests)
- [x] No hardcoded secrets found

### Deployed Tools
1. tool_name_one - Verified working
2. tool_name_two - Verified working
3. tool_name_three - Verified working

### Verification Results
- Tool listing: PASS
- Happy path test: PASS
- Error handling test: PASS

### Next Steps
[Any recommendations or notes]
```

## Important Guidelines

- **NEVER skip the permission fix** - this is a known issue with subagent-created files
- **ALWAYS run tests before deploying** - don't deploy broken code
- **Use terminal-worker for deployment** - keeps main context clean
- **Verify with mcp-test-mcp** - don't assume deployment worked
- If mcp-test-mcp is unavailable, STOP and ask user to enable it
- Each MCP server should deploy to its own project to avoid naming collisions

## Error Recovery

### Build Fails
Check:
- Are all dependencies in `requirements.txt`?
- Are there import errors? Check with `python -c "from src.main import main"`
- Permission issues? Re-run the permission fix

### Pod Won't Start
Check:
- `oc logs deployment/<name> -n <PROJECT>`
- Missing environment variables?
- Permission denied errors → re-run permission fix and redeploy

### mcp-test-mcp Can't Connect
Check:
- Is the route correct?
- Is the path `/mcp/`? (trailing slash matters)
- Check pod logs for startup errors

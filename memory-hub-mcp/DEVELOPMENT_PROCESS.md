# MCP Server Development Process

This document describes the complete workflow for developing MCP servers using this template, including the slash commands available at each phase.

## Workflow Overview

```
/plan-tools → /create-tools → /exercise-tools → /write-system-prompt → /update-docs → /deploy-mcp
```

Each command builds on the output of the previous one. While you can skip steps for simple servers, following the full workflow ensures quality and consistency.

## Phase 1: Planning

### `/plan-tools`

**Purpose**: Design tools before writing any code.

**When to Use**:
- Starting a new MCP server
- Adding significant new functionality
- Refactoring existing tools

**Prerequisites**:
- Clear understanding of what the MCP server should do
- Optionally: PROPOSAL.md or REQUIREMENTS.md with specifications

**What It Does**:
1. Reads Anthropic's tool design article for best practices
2. Reviews any existing proposals or requirements
3. Creates `TOOLS_PLAN.md` with detailed tool specifications

**Expected Output**:
- `TOOLS_PLAN.md` at project root
- Summary of planned tools presented for approval

**Iteration**:
If feedback requires changes, edit `TOOLS_PLAN.md` directly or re-run `/plan-tools` with updated requirements.

## Phase 2: Implementation

### `/create-tools`

**Purpose**: Generate scaffolds and implement tools based on the plan.

**When to Use**:
- After `/plan-tools` has been approved
- When adding new tools to an existing server

**Prerequisites**:
- `TOOLS_PLAN.md` must exist
- Virtual environment set up (`make install`)

**What It Does**:
1. Reads `TOOLS_PLAN.md` for tool specifications
2. Generates tool scaffolds using `fips-agents generate tool`
3. Launches parallel subagents to implement each tool
4. Runs tests to verify implementation
5. Fixes file permissions for deployment

**Expected Output**:
- Tool files in `src/tools/`
- Test files in `tests/`
- All tests passing

**Iteration**:
If tools need adjustment:
- For minor fixes: Edit files directly
- For significant changes: Use `/implement-mcp-item` for individual tools
- For redesign: Return to `/plan-tools`

### `/implement-mcp-item`

**Purpose**: Implement or fix a single MCP component.

**When to Use**:
- Fixing a specific tool after `/exercise-tools` feedback
- Adding a single new tool, resource, or prompt
- Debugging a specific component

**Prerequisites**:
- Specification of what to implement/fix
- Virtual environment set up

**What It Does**:
1. Implements the specified component
2. Writes or updates tests
3. Runs tests to verify

**Expected Output**:
- Updated component file
- Updated test file
- Tests passing

## Phase 3: Quality Assurance

### `/exercise-tools`

**Purpose**: Test tool ergonomics from an agent's perspective.

**When to Use**:
- After tools are implemented
- Before writing system prompts
- When agents report usability issues

**Prerequisites**:
- Tools implemented in `src/tools/`
- `TOOLS_PLAN.md` for context on intended use

**What It Does**:
1. Reviews each tool as a consuming agent would
2. Tests basic usage, error handling, and tool composition
3. Provides structured feedback with scores
4. Makes non-controversial improvements
5. Asks for guidance on subjective changes

**Expected Output**:
- Ergonomics report for each tool
- Improved tool implementations
- All tests still passing

**Iteration**:
For issues found:
- Clear improvements are made automatically
- Subjective changes require user approval
- Major redesigns may require returning to `/plan-tools`

## Phase 4: Documentation

### `/write-system-prompt`

**Purpose**: Generate a system prompt for agents using this MCP server.

**When to Use**:
- After tools are implemented and tested
- When preparing to integrate with an AI agent
- When tool capabilities have changed significantly

**Prerequisites**:
- Tools implemented in `src/tools/`
- Example code removed (`./remove_examples.sh`)

**What It Does**:
1. Discovers all implemented tools
2. Reads context from TOOLS_PLAN.md and README.md
3. Generates comprehensive system prompt with:
   - Role and capabilities
   - Tool usage guidelines
   - Error handling guidance
   - Tool composition patterns
   - Example interactions

**Expected Output**:
- `SYSTEM_PROMPT.md` at project root
- Summary of agent capabilities

**Iteration**:
Edit `SYSTEM_PROMPT.md` directly to refine guidance. Re-run command if tools change significantly.

### `/update-docs`

**Purpose**: Ensure documentation matches implementation.

**When to Use**:
- Before deployment
- After any significant tool changes
- When onboarding new team members

**Prerequisites**:
- Example code removed (`./remove_examples.sh` - **hard requirement**)
- Tools implemented in `src/tools/`

**What It Does**:
1. Verifies examples are removed (stops if present)
2. Inventories all tools, resources, prompts, and middleware
3. Updates README.md with accurate component documentation
4. Updates ARCHITECTURE.md with component overview

**Expected Output**:
- Updated README.md with tool/resource/prompt tables
- Updated ARCHITECTURE.md with component counts
- Summary of documentation changes

**Iteration**:
Run again after any implementation changes to keep docs current.

## Phase 5: Deployment

### `/deploy-mcp`

**Purpose**: Deploy the MCP server to OpenShift.

**When to Use**:
- After development is complete
- When deploying updates

**Prerequisites**:
- All tests passing
- Documentation updated
- `mcp-test-mcp` available for verification
- OpenShift access configured

**Arguments**:
- `PROJECT` (required): OpenShift project/namespace name

**What It Does**:
1. Pre-deployment checks:
   - Fixes file permissions
   - Verifies .dockerignore
   - Runs test suite
   - Checks for hardcoded secrets
2. Delegates deployment to terminal-worker
3. Verifies deployment with mcp-test-mcp

**Expected Output**:
- MCP server running in OpenShift
- Route URL for accessing the server
- Verification results

**Iteration**:
For deployment issues:
- Check pod logs with `oc logs -n <PROJECT>`
- Fix issues and redeploy
- See Error Recovery section in `/deploy-mcp` command

## Quick Reference

| Phase | Command | Creates/Updates | Prerequisites |
|-------|---------|-----------------|---------------|
| Plan | `/plan-tools` | TOOLS_PLAN.md | None |
| Build | `/create-tools` | src/tools/, tests/ | TOOLS_PLAN.md |
| Build | `/implement-mcp-item` | Single component | Spec |
| QA | `/exercise-tools` | Improved tools | Tools exist |
| Docs | `/write-system-prompt` | SYSTEM_PROMPT.md | Tools exist |
| Docs | `/update-docs` | README.md, ARCHITECTURE.md | Examples removed |
| Deploy | `/deploy-mcp PROJECT=x` | OpenShift deployment | Tests pass |

## Tips for Success

1. **Don't skip planning**: `/plan-tools` saves time by catching design issues early

2. **Remove examples early**: Run `./remove_examples.sh` after generating your first tool

3. **Exercise before documenting**: `/exercise-tools` may reveal changes that affect documentation

4. **Keep docs current**: Run `/update-docs` after any tool changes

5. **Test deployment locally first**: Use `make test-local` with cmcp before deploying

6. **One project per server**: Each MCP server should deploy to its own OpenShift project

## Troubleshooting

### "TOOLS_PLAN.md not found"
Run `/plan-tools` first to create the plan.

### "Examples still present"
Run `./remove_examples.sh` to remove template example code.

### "Permission denied" during deployment
Run: `find src -name "*.py" -perm 600 -exec chmod 644 {} \;`

### "0 tools loaded" after deployment
Check pod logs for import errors. Common cause: permission issues on source files.

### Tests failing after implementation
- Check for missing dependencies in both `pyproject.toml` and `requirements.txt`
- Verify imports use `src.` prefix
- Run `python -c "from src.main import main"` to check for import errors

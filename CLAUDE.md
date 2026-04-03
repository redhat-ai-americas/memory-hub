# MemoryHub

## Project Overview
MemoryHub is a Kubernetes-native agent memory component for OpenShift AI. See docs/ARCHITECTURE.md for the full architecture and docs/SYSTEMS.md for subsystem inventory.

## Issue Management
Use the `/issue-tracker` skill for ALL issue operations. Never create issues manually without using the skill -- it enforces our conventions:
- Every issue references a design document
- Every issue starts in Backlog
- Issues flow: Backlog -> In Progress -> Done

## Development Conventions
- Python with FastAPI for services
- Kubernetes Operator in Python (kopf or operator-sdk)
- Red Hat UBI base images only
- FIPS compliance required
- Use Podman, not Docker
- Use Containerfile, not Dockerfile
- PostgreSQL (OOTB, ships with OpenShift) + pgvector for vector search
- PostgreSQL for graph queries (evolution path to dedicated graph DB)
- MinIO for S3/object storage
- MCP server via fips-agents CLI workflow

## MCP Server (memory-hub-mcp/)
The MCP server lives in `memory-hub-mcp/` and was scaffolded from the fips-agents MCP template. Follow the workflow in order:

1. `/plan-tools` — Design tools, produces TOOLS_PLAN.md (no code)
2. `/create-tools` — Generate and implement tools via parallel subagents
3. `/exercise-tools` — Test from an agent's perspective, refine ergonomics
4. `/write-system-prompt` — Create SYSTEM_PROMPT.md for consuming agents
5. `/update-docs` — Update README and ARCHITECTURE docs
6. `/deploy-mcp PROJECT=memory-hub-mcp` — Deploy to OpenShift with verification

When working in the MCP server, read `memory-hub-mcp/CLAUDE.md` for import conventions, testing patterns, and architecture details. Key points:
- Always use `src.` prefix for imports
- Test decorated functions via `.fn` attribute
- `fips-agents` is a global CLI (pipx), not in the venv
- Fix file permissions before deployment: `find src -name "*.py" -perm 600 -exec chmod 644 {} \;`

## Design Documents
All design docs live in docs/. When implementing a feature, always read the relevant design doc first. If the design doc is a skeleton or has TBD sections, flesh it out before implementing.

## Commit Messages
Use conventional commit format: `subsystem: Description in imperative mood`
Example: `memory-tree: Add versioning with isCurrent flag`

## Testing
- pytest for all Python testing
- 80%+ coverage target
- Test error paths explicitly

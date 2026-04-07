# Python Package Layout

**Status:** Skeleton — to be fleshed out as part of the Cleanup B rename effort.

## Current state (2026-04-06)

This monorepo contains **two distinct Python packages that both declare `name = "memoryhub"`** in their `pyproject.toml`. They are not duplicates of each other — they have completely different file contents and serve different purposes — but the shared distribution name is a known footgun.

### Package A: server-side (root)

| | |
|---|---|
| Path | `src/memoryhub/` |
| Build config | `pyproject.toml` (repo root) |
| Build backend | setuptools |
| Distribution name | `memoryhub` |
| Version | `0.1.0` |
| Contents | `services/`, `storage/`, `models/`, `config.py` |
| Heavy deps | sqlalchemy, asyncpg, pgvector, minio, alembic |
| Used by | The MCP server container, the BFF, the CLI, anything that runs the actual MemoryHub service. |
| Distribution | Not published. The MCP server's `deploy/build-context.sh` copies `src/memoryhub/` and the root `pyproject.toml` into a staged `memoryhub-core/` directory inside the container build context. The Containerfile then runs `pip install ./memoryhub-core/`, which installs it as `memoryhub`. |

### Package B: client-side SDK (sdk/)

| | |
|---|---|
| Path | `sdk/src/memoryhub/` |
| Build config | `sdk/pyproject.toml` |
| Build backend | hatchling |
| Distribution name | `memoryhub` |
| Version | `0.1.0` |
| Contents | `client.py`, `auth.py`, `exceptions.py`, `models.py`, `py.typed` |
| Light deps | httpx, pyjwt, pydantic, fastmcp |
| Used by | External Python clients that talk to the MemoryHub HTTP/MCP API. Future custom agents (not yet built). |
| Distribution | Published to PyPI as `memoryhub` via `scripts/release.sh sdk <version>`. See `.claude/commands/create-release.md`. |

## Why this is a problem

1. **Same import name, different code.** `import memoryhub` resolves to whichever package was last installed into the active environment. A developer running `pip install -e .` from the repo root and then `pip install -e ./sdk/` (or vice versa) will silently overwrite one with the other.
2. **Cognitive load.** A new contributor reading the repo cannot tell from the directory name alone which `memoryhub` is the one published to PyPI vs. the one bundled into the MCP container.
3. **Accidental wrong-package install.** A user who runs `pip install memoryhub` from PyPI gets the SDK and may reasonably expect server-side classes (`memoryhub.services.memory.MemoryService`) to exist. They don't.

## Why this is not yet broken at runtime

The two packages never coexist in the same process:

- The MCP container only installs Package A (server-side) via the `memoryhub-core/` build-context staging trick. The SDK is not in `requirements.txt`.
- External SDK consumers only install Package B from PyPI. They have no reason to install the server-side package, which is not published.

The collision is on disk and in the developer's mental model, not at runtime.

## Proposed direction (TBD)

Likely: rename the server-side package to something like `memoryhub_server` or `memoryhub_core` and keep `memoryhub` as the PyPI/SDK name (since that name is already public on PyPI and is the user-visible identifier).

Affected on rename:
- `src/memoryhub/` → `src/memoryhub_server/` (or similar)
- All `from memoryhub.services...` / `from memoryhub.storage...` imports across the MCP server, BFF, CLI, alembic migrations, tests
- `pyproject.toml` `name`
- `memory-hub-mcp/deploy/build-context.sh` (the `memoryhub-core/` staging directory)
- `memory-hub-mcp/Containerfile` (the `pip install ./memoryhub-core/` line if path changes)
- `memoryhub-ui/backend/` if it imports server-side code
- `alembic/` migration `env.py`
- Any docs that reference `memoryhub.services` etc.

This is a non-trivial cross-package refactor that should be done in a focused session, not bundled with feature work.

## Out of scope for this doc (until fleshed out)

- Final naming decision
- Migration script for existing deployments
- Whether to also rename the `sdk/` directory itself for clarity
- Whether the SDK needs to vendor any types from the server-side package (currently it does not — `models.py` is independent)

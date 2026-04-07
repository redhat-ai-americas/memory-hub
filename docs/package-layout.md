# Python Package Layout

**Status:** Resolved 2026-04-07 (#55).

## Current state

The monorepo contains two distinct Python packages with two distinct distribution names:

### Package A: `memoryhub-core` (server-side)

| | |
|---|---|
| Path | `src/memoryhub_core/` |
| Build config | `pyproject.toml` (repo root) |
| Build backend | setuptools |
| Distribution name | `memoryhub-core` |
| Import name | `memoryhub_core` |
| Version | `0.3.0` |
| Contents | `services/`, `storage/`, `models/`, `config.py`, plus the FIPS-aware embedding integration |
| Heavy deps | sqlalchemy, asyncpg, pgvector, minio, alembic |
| Used by | The MCP server container, the dashboard BFF, the alembic migrations, the seed-oauth-clients script, and the root-level test suite. |
| Distribution | Not published to PyPI. The MCP server's `deploy/build-context.sh` and the dashboard UI's `deploy/build-context.sh` both copy `src/memoryhub_core/` and the root `pyproject.toml` into a staged `memoryhub_core/` directory inside the container build context. The Containerfile then runs `pip install ./memoryhub_core/`. |

### Package B: `memoryhub` (client SDK)

| | |
|---|---|
| Path | `sdk/src/memoryhub/` |
| Build config | `sdk/pyproject.toml` |
| Build backend | hatchling |
| Distribution name | `memoryhub` |
| Import name | `memoryhub` |
| Version | `0.1.0` |
| Contents | `client.py`, `auth.py`, `exceptions.py`, `models.py`, `config.py`, `py.typed` |
| Light deps | httpx, pyjwt, pydantic, pyyaml, fastmcp |
| Used by | External Python clients that talk to the MemoryHub HTTP/MCP API. The `memoryhub-cli` package depends on it transitively. Future custom agents. |
| Distribution | Published to PyPI as `memoryhub` via `scripts/release.sh sdk <version>`. See `.claude/commands/create-release.md`. |

The two packages now have distinct distribution names AND distinct import names. They can coexist in the same environment without ambiguity (though there is no reason to).

## How #55 was resolved

The original problem was that both packages declared `name = "memoryhub"` in their `pyproject.toml`. `import memoryhub` resolved to whichever was last installed, which silently broke developer workflows whenever someone ran `pip install -e .` from the repo root and `pip install -e ./sdk/` in the same venv. The collision lived on disk and in mental models even though it never actually broke runtime (the two packages never coexisted in production processes — the MCP container only installed the server-side library, and external SDK consumers only installed the SDK from PyPI).

The fix was a single atomic rename:

- `src/memoryhub/` → `src/memoryhub_core/`
- Root `pyproject.toml`: `name = "memoryhub"` → `name = "memoryhub-core"`, version `0.2.0` → `0.3.0`
- All `from memoryhub.X import Y` → `from memoryhub_core.X import Y` (and `import memoryhub.X` → `import memoryhub_core.X`) across:
  - The package itself (internal imports)
  - All 13 MCP tools and `_deps.py` in `memory-hub-mcp/src/tools/`
  - The `memory-hub-mcp/tests/` suite
  - The dashboard BFF (`memoryhub-ui/backend/src/routes.py` + tests)
  - The root-level test suite (`tests/test_models/`, `tests/test_services/`, `tests/integration/`)
  - The alembic migration `env.py`
  - The `scripts/seed-oauth-clients.py` helper
- Both Containerfiles updated: `COPY ./memoryhub-core/` (memory-hub-mcp) and `COPY ./memoryhub/` (memoryhub-ui — which had been silently inconsistent with its own build script) both became `COPY ./memoryhub_core/`. This also fixed a real bug in the memoryhub-ui build pipeline where the build script staged to `memoryhub-core/` but the Containerfile was reading from `memoryhub/`.
- Both `deploy/build-context.sh` scripts updated to stage to `memoryhub_core/` and copy from `src/memoryhub_core/`.
- Documentation updated: this file marks resolved; `SYSTEMS.md` and `ARCHITECTURE.md` drop their #55 follow-up callouts; `README.md` drops its "two memoryhub packages" footnote; `memory-hub-mcp/TOOLS_PLAN.md` and `memory-hub-mcp/.claude/commands/deploy-mcp.md` update their `memoryhub.services` path references.

The SDK was not touched. The CLI was not touched. The auth service does not depend on the package and was not touched.

All five test suites stayed green at the same baseline counts before and after the rename: mcp-server 134, root services + models 117, BFF 39, SDK 66, memoryhub-cli 27. Pure rename, no behavior change.

## Lessons

1. **The build pipeline inconsistency would have been a deploy-time time bomb.** The `memoryhub-ui` Containerfile had been reading from `memoryhub/` while the build script staged to `memoryhub-core/` for some time. The dashboard pod that was running before #55 was from a build that succeeded under different conditions; subsequent rebuilds would have failed silently. The `#55` rename surfaced the inconsistency and fixed it. Generalizable lesson: when two files refer to the same artifact by name, run a grep to confirm they agree.

2. **Atomic renames over compatibility shims.** The first design fork in the #55 plan was "single atomic commit vs gradual migration with a compatibility shim that re-exports from the new name." The compatibility shim would have entrenched the very problem #55 set out to solve — keeping `import memoryhub` working as an alias for the server-side library would have meant the dual-name footgun never went away. Single atomic rename was the right call.

3. **Distribution name vs import name vs directory name.** All three should match for clarity, even though Python's packaging story technically allows them to differ. `memoryhub-core` (distribution, with hyphen per PEP 503), `memoryhub_core` (import, underscore per Python identifier rules), `src/memoryhub_core/` (directory, matching the import name). Same for the SDK side: `memoryhub`, `memoryhub`, `sdk/src/memoryhub/`. No surprises.

# Contributing to MemoryHub

Thanks for your interest in MemoryHub. This guide covers how the repo is laid out, how to set up a development environment for each subproject, the conventions we follow, and how to file issues and PRs.

If anything here is unclear, file an issue and tag it `documentation` — that's a good first contribution in itself.

## Repo layout in one paragraph

MemoryHub is a monorepo with one server-side library (`src/memoryhub_core/`) and four deployable subprojects (`memory-hub-mcp/`, `memoryhub-auth/`, `memoryhub-ui/`, plus the published Python `sdk/`) and one CLI client (`memoryhub-cli/`). The MCP server, BFF, alembic migrations, and the seed-OAuth-clients script all import from the server-side library; the SDK and CLI are independent and never touch the server-side code. See [`docs/SYSTEMS.md`](docs/SYSTEMS.md) for the per-subsystem inventory and [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the system overview.

## Setting up a dev environment

Each subproject has its own venv. Pick the one(s) you need.

### Server-side library + root tests + alembic

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest tests/ -q
```

### MCP server (`memory-hub-mcp/`)

```bash
cd memory-hub-mcp
make install
.venv/bin/pytest tests/ -q --ignore=tests/examples/
```

### Python SDK (`sdk/`)

```bash
cd sdk
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest tests/ -q --ignore=tests/test_rbac_live.py
```

### CLI (`memoryhub-cli/`)

```bash
cd memoryhub-cli
python -m venv .venv && source .venv/bin/activate
pip install -e .
pytest tests/ -q
```

### Dashboard BFF (`memoryhub-ui/backend/`)

```bash
cd memoryhub-ui/backend
python -m venv .venv && source .venv/bin/activate
pip install -e .
pytest tests/ -q
```

### Auth service (`memoryhub-auth/`)

```bash
cd memoryhub-auth
python -m venv .venv && source .venv/bin/activate
pip install -e .
pytest tests/ -q
```

### Frontend (`memoryhub-ui/frontend/`)

```bash
cd memoryhub-ui/frontend
npm install
npm run build
```

## Cluster access

Most contributions never need to touch the demo OpenShift cluster. Local development against SQLite or a podman-run PostgreSQL is enough for almost everything. If you do need access to the cluster — to read logs, reproduce a deploy-specific bug, or run the SDK's live-auth tests — see [`docs/contributor-cluster-access.md`](docs/contributor-cluster-access.md). The short version: read-only access is granted on request, deploy access is not, and the cluster admin (`@rdwj`) handles deploys on their own cadence.

## Filing issues

Use the `/issue-tracker` slash command — it enforces our conventions automatically. If you're filing manually, the rules are:

- **Every issue references a design document.** If the design doesn't exist yet, file the design issue first or write a skeleton in `docs/`. We don't accept feature issues without a design pointer.
- **Every issue starts in the Backlog column** of the MemoryHub project board. Issues flow Backlog → In Progress → Done.
- **Author is `rdwj`.** Do NOT add AI attribution to issue authors. Other developers need to know who to contact about an issue, and the human owner is the point of contact, not the AI assistant that helped draft the body.
- **No internal-tooling issues on this public repo.** If something internal to your dev environment is broken, mention it in conversation rather than filing a public issue that reveals private infrastructure details.

## Submitting pull requests

1. **Read the relevant design doc first.** Most subsystems have one in `docs/`. If you're touching the agent-memory-ergonomics work, read [`docs/agent-memory-ergonomics/design.md`](docs/agent-memory-ergonomics/design.md). If you're touching auth, read [`docs/governance.md`](docs/governance.md). If you're touching the package layout, read [`docs/package-layout.md`](docs/package-layout.md).
2. **Create a branch off `main`.** We don't use feature flags or long-lived branches.
3. **Run the relevant test suite locally** before opening the PR. Each subproject's `pytest tests/ -q` is fast (under a second on a recent laptop).
4. **Run [gitleaks](https://github.com/gitleaks/gitleaks)** before committing. We don't depend on git pre-commit hooks. If you have the `/pre-commit` slash command available, use that.
5. **Open the PR with a clear description** that links the issue number and references the design doc. Reviewers check the design first, then the diff.
6. **Be ready to iterate.** We optimize for the right design, not the fastest merge.

## Commit messages

Use the conventional commit format with a subsystem prefix:

```
subsystem: Description in imperative mood

Optional body explaining the *why*, with context that a future
maintainer reading the log will need.

Closes #NN.
```

Examples from the actual log:

- `mcp-server: Add mode/token-budget and branch-handling to search_memory`
- `sdk: Add .memoryhub.yaml schema and surface new search params (#59, #73)`
- `memoryhub-cli: Add 'memoryhub config init' for project setup (#60)`
- `#58: Add session focus vector with two-vector retrieval (Layer 2)`
- `#55: Rename server-side memoryhub package to memoryhub_core`

Imperative mood: write "Add foo" not "Adds foo" or "Added foo." Body explains why; the diff explains what.

If your commit was assisted by an AI tool, add an `Assisted-by:` trailer (e.g., `Assisted-by: Claude Code (Opus 4.6)`). Do not add `Co-authored-by:` or `Signed-off-by:` trailers — the human author is the sole author of record. The signoff is for the human to add manually before pushing if their workflow requires it.

## Coding conventions

These conventions are enforced by review, not by linters (mostly).

- **Python**: FastAPI for services. Pydantic v2 for data models. SQLAlchemy 2.0 async for the database layer. `pytest` for tests. `ruff` for linting where it's configured.
- **Containers**: Podman, not Docker. `Containerfile`, not `Dockerfile`. Red Hat UBI9 base images only. FIPS compliance is inherited from the cluster.
- **Architecture**: Build `linux/amd64` containers when targeting OpenShift from a Mac (`podman build --platform linux/amd64`).
- **File permissions**: `chmod 644` source files before any container build (Claude Code's Write tool creates 600, which OpenShift's non-root container UIDs cannot read).
- **No early optimization.** Get basic functionality working first. Don't add abstraction for hypothetical future requirements.
- **Don't mock to work around errors.** Let broken things stay visibly broken so they get fixed. Mocks belong in tests, not in production code.
- **Match the existing style.** A new Pydantic model should look like the existing Pydantic models in the same file.

## The same-commit consumer audit rule

When you change the response shape of an MCP tool (rename a field, add a field, remove a field), grep `memoryhub-ui/backend/`, `sdk/`, and `memoryhub-cli/` in the **same commit** that changes the tool. Pydantic's `extra="allow"` masks shape mismatches silently — the consumer doesn't crash, it just sees `None` where data should be. We've been bitten by this twice; the rule exists because of an actual broken-in-production incident.

The recipe is:

```bash
grep -rn 'old_field_name' memoryhub-ui/backend/ sdk/ memoryhub-cli/
```

If anything matches, update it in the same commit. If nothing matches, the change is safe to land.

The current consumer-priority tier list lives in the project's MemoryHub memory; if you're working on this repo with an agent, the agent already has it loaded.

## Mock-vs-real test discipline

A 100%-line-covered unit test suite is **not** sufficient evidence that a server-side change is deploy-ready. We have shipped at least two bugs that the unit tests passed but real production caught:

1. **`numpy.float32` leakage** — pgvector returns numpy arrays, the test mocks return Python lists. The cosine-distance helper propagated `numpy.float32` to the response, which `pydantic_core.to_jsonable_python` rejected, and FastMCP silently dropped `structured_content`. 100% line coverage in unit tests; caught only by post-deploy `mcp-test-mcp` verification.
2. **File permission mismatch** — Claude Code's Write tool creates 600 files, but OpenShift containers run as arbitrary non-root UIDs that need 644 to read. Tests passed locally; container crashed with `PermissionError` on deploy.

Two takeaways:

- **For new code that touches embeddings or pgvector**, add an integration test in `tests/integration/test_pgvector.py`. The integration suite already runs against real PostgreSQL via podman-compose.
- **For deploys**, run `mcp-test-mcp` against the deployed pod to verify the changed code paths actually work end-to-end. The project-local `/deploy-mcp` slash command in `memory-hub-mcp/.claude/commands/deploy-mcp.md` already enforces this.

The full mock-vs-real boundary audit is in the [#58 retrospective](retrospectives/2026-04-07_session-focus-vector-58/RETRO.md) under "Patterns."

## Test data identification and cleanup

When integration tests or manual testing run against a live deployment, they leave test data in the database. To keep dashboards and search results clean, **all test data must be identifiable** so automated cleanup can find it.

**Required convention:** prefix test memory content with `[test]` — e.g., `[test] RBAC scope isolation a1b2c3`. The SDK helper `_test_content()` in `sdk/tests/test_rbac_live.py` does this automatically.

**Known test owner_ids:** integration test fixtures use owner_ids like `test-user`, `dup-test-user`, `domain-test-user`, etc. The full list lives in `scripts/cleanup-test-data.py`.

**Cleanup tooling:**

- **Local:** `python scripts/cleanup-test-data.py` (dry-run by default, pass `--execute` to soft-delete)
- **Cluster:** `deploy/cleanup/cronjob.yaml` runs weekly on Sundays at 03:00 UTC

Both tools soft-delete matching rows (set `deleted_at`, clear `is_current`). They do not hard-delete — that's reserved for the admin API (#45).

## Documentation expectations

- **Update docs in the same PR as the code change.** A new feature with a stale design doc is worse than a new feature with no doc.
- **`SYSTEMS.md` and `ARCHITECTURE.md` are the repo's front door.** Keep them current. If you add or remove a subsystem, update both.
- **Per-subsystem docs in `docs/`** are the design source of truth. If implementation drifts from design, update the design first (or file an issue tracking the drift).
- **Retrospectives.** After a major effort or a session that taught you something durable, write a retro under `retrospectives/YYYY-MM-DD_<topic>/RETRO.md`. The retros are where the project's institutional knowledge lives — they're worth more than the design docs in some cases.

## Project conventions reference

For the full list of conventions (Podman, FIPS, OpenShift namespace handling, MCP server scaffold rules, and more), see [`CLAUDE.md`](CLAUDE.md). It's the agent-facing version of this guide and the two should stay in sync.

## License

By submitting a contribution, you agree that your contribution will be licensed under the project's [Apache License 2.0](LICENSE).

---

Copyright 2026 Wes Jackson · Apache 2.0

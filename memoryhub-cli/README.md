# memoryhub-cli

Command-line client for MemoryHub — centralized, governed memory for AI agents.

## Install

```bash
pip install memoryhub-cli
```

## Authentication

The CLI supports two authentication modes:

**API key (recommended for non-interactive use):**

```bash
# Via environment variable
export MEMORYHUB_API_KEY=mh-dev-abc123

# Or store in the credentials file (INI-style, mode 0600)
mkdir -p ~/.config/memoryhub
cat > ~/.config/memoryhub/credentials << 'EOF'
[default]
api_key = mh-dev-abc123
EOF
chmod 600 ~/.config/memoryhub/credentials
```

API key resolution order: `MEMORYHUB_API_KEY` env var > `~/.config/memoryhub/credentials` (section from `MEMORYHUB_CONTEXT` or `[default]`) > `~/.config/memoryhub/api-key` (legacy flat file) > `api_key` in config.json.

**Server URL:**

The CLI needs to know where the MemoryHub server is. The SessionStart hook for Claude Code also reads from this config.

```bash
# Via environment variable
export MEMORYHUB_URL=https://memoryhub.example.com/mcp/

# Or save to ~/.config/memoryhub/config.json (also set by memoryhub config init)
echo '{"url": "https://memoryhub.example.com/mcp/"}' > ~/.config/memoryhub/config.json
chmod 600 ~/.config/memoryhub/config.json
```

API-key URL resolution: `MEMORYHUB_URL` env var > `url` in the credentials section
selected by `MEMORYHUB_CONTEXT` (or `[default]`) > `url` in `config.json`.

**OAuth (interactive setup):**

```bash
memoryhub login
```

OAuth settings resolve from environment variables over `config.json`;
`MEMORYHUB_CONTEXT` selects API-key credentials sections. When both API-key and
OAuth configuration are available, API-key authentication takes precedence.

## Check the connection

Run `memoryhub doctor` after configuring the CLI and before connecting an agent:

```bash
memoryhub doctor
memoryhub doctor --edition local
memoryhub doctor --edition cluster
```

By default, the command detects the edition from the installed packages. When
`memoryhub-local` is installed, it checks the personal edition's local database
and embedding model. Otherwise, it uses the configured API key or OAuth
credentials to check the cluster MCP endpoint, authenticate, and run a
write/search/read/delete smoke test. Cluster results also include the session
identity, reported scopes, session expiry, and project memberships when the
server provides them. Doctor warns when the session expires within five
minutes and stops before writing if reported scopes lack user-memory read or
write access. The `--edition local` and
`--edition cluster` options force one path regardless of installed packages;
forcing local checks without `memoryhub-local` installed reports an install
instruction.

The cluster smoke test creates a short, user-scoped memory prefixed with
`[test]` and a random per-run identifier, then soft-deletes it. If cleanup
fails, the report identifies the test memory and tells you to remove it with
`memoryhub delete <memory-id>`.

Select a named credentials section for one cluster check with `--context`.
This option selects cluster checks even if `memoryhub-local` is installed.
`MEMORYHUB_CONTEXT` remains the default for other CLI commands, and
`MEMORYHUB_URL`, when set, overrides the saved URL. OAuth credentials continue
to come from their normal environment variables or `config.json`.

```bash
memoryhub doctor --edition cluster --context staging
```

The table and JSON report include the selected context and sanitized server URL
so you can confirm which endpoint was checked. The server URL omits URL
credentials, query parameters, and fragments.

Use JSON output for scripts or quiet output when only the exit status matters:

```bash
memoryhub doctor --output json
memoryhub doctor --output quiet
```

For cluster checks, exit status is `0` when all checks pass. A failed check
returns nonzero and includes a next action. Table failures show the checks and
remediation in the terminal. After diagnostics begin, JSON failures include the
check results and `next_action` in an error envelope on stderr. Missing
configuration uses the standard error envelope with remediation in its message.
Quiet mode suppresses the check report and uses the same health exit status.
Configuration errors may still print the standard error message.

For example, if the endpoint responds but rejects authentication, the table
shows the later checks as skipped and gives a credential-specific next action:

```text
MemoryHub Doctor

  Edition:         cluster
  Endpoint:        passed  MCP endpoint responded.
  Authentication:  failed  The server rejected the configured credentials.
  Write:           skipped Authentication failed.
  Search:          skipped Authentication failed.
  Read:            skipped Authentication failed.
  Delete:          skipped Authentication failed.

  Next action: Run 'memoryhub login' or check the API key and OAuth configuration.
```

For common failures:

- **Endpoint unreachable:** confirm `MEMORYHUB_URL` is the MCP URL (usually
  ending in `/mcp/`) and that the endpoint is reachable.
- **Authentication failed:** run `memoryhub login` or verify the configured API
  key or OAuth credentials. An API key takes precedence when both auth modes
  are configured.
- **Write, search, read, or delete failed:** check the account's user-scope
  permissions and the corresponding server services. If cleanup failed, use
  the reported ID with `memoryhub delete <memory-id>`.

## Usage

```bash
# Search for memories
memoryhub search "deployment patterns"

# List memories by creation time (no semantic search)
memoryhub list --project-id my-project --max 20

# Read a specific memory
memoryhub read <memory-id>

# Write a new memory
memoryhub write "Use Podman, not Docker" --scope user --weight 0.9

# Campaign-scoped operations (requires project enrollment)
memoryhub search "shared patterns" --project-id my-project --domain React
memoryhub write "Use vLLM for embeddings" --project-id my-project --domain ML

# Compact output for LLM context injection (content only, no metadata)
memoryhub search "project conventions" --output compact

# Set up project-level memory loading
memoryhub config init
memoryhub config regenerate

# Admin: provision and manage agents
memoryhub admin create-agent my-agent --scopes user,project
memoryhub admin list-agents
memoryhub admin rotate-secret my-agent
memoryhub admin disable-agent my-agent
```

The `--project-id` flag enables campaign-scoped memory access. When your project is enrolled in campaigns via `.memoryhub.yaml`, the CLI auto-loads the project identifier from config, so you can omit the flag in most cases. Use `--domain` to tag writes or boost domain-matching results in search.

## Output formats

The `--output` / `-o` flag controls output format on most commands:

- `table` (default) -- Rich-formatted tables for interactive use
- `json` -- Machine-readable JSON envelope (`{"status": "ok", "data": {...}}`)
- `quiet` -- No output (exit code only)
- `compact` -- Content-only text for LLM context injection, no IDs or metadata

## Project configuration

`memoryhub config` generates a project-local `.memoryhub.yaml` and a companion `.claude/rules/memoryhub-loading.md` rule file. Both files are meant to be committed so every contributor's agent inherits the same loading policy.

`memoryhub config init` is an interactive wizard that asks about session shape, loading pattern, focus source, and retrieval defaults, then writes both files at the project root. If a legacy `.claude/rules/memoryhub-integration.md` already exists, it is backed up to `.bak` before the new rule file is written.

`memoryhub config regenerate` re-renders the rule file from `.memoryhub.yaml` after you hand-edit the YAML. It reads the YAML and rewrites the Markdown rule file only; it does not modify `.memoryhub.yaml`.

Per-developer connection params (`url`, `auth_url`, `client_id`, `client_secret`) live separately at `~/.config/memoryhub/config.json` and are managed by `memoryhub login`. They are not stored in `.memoryhub.yaml` and are not committed.

## Further documentation

The CLI is one surface of the [memory-hub](https://github.com/redhat-ai-americas/memory-hub) monorepo. For deeper context:

- **[Architecture overview](https://github.com/redhat-ai-americas/memory-hub/blob/main/docs/ARCHITECTURE.md)** — System design, deployment topology
- **[MCP server tool reference](https://github.com/redhat-ai-americas/memory-hub/blob/main/docs/design/mcp-server.md)** — The 15 tools the CLI wraps
- **[Agent memory ergonomics design](https://github.com/redhat-ai-americas/memory-hub/blob/main/docs/agent-memory-ergonomics/design.md)** — Full `.memoryhub.yaml` schema, rule file templates, and session-loading patterns
- **[Python SDK](https://pypi.org/project/memoryhub/)** — if you'd rather call the tools from Python

## Links

- **[GitHub repository](https://github.com/redhat-ai-americas/memory-hub)**
- **[Issue tracker](https://github.com/redhat-ai-americas/memory-hub/issues)**
- **[License (Apache 2.0)](https://github.com/redhat-ai-americas/memory-hub/blob/main/LICENSE)**

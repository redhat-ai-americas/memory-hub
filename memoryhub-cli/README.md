# memoryhub-cli

Command-line client for MemoryHub — centralized, governed memory for AI agents.

## Install

```bash
pip install memoryhub-cli
```

## Usage

```bash
# Authenticate to a MemoryHub instance
memoryhub login

# Search for memories
memoryhub search "deployment patterns"

# Read a specific memory
memoryhub read <memory-id>

# Write a new memory
memoryhub write "Use Podman, not Docker" --scope user --weight 0.9

# Campaign-scoped operations (requires project enrollment)
memoryhub search "shared patterns" --project-id my-project --domain React
memoryhub write "Use vLLM for embeddings" --project-id my-project --domain ML

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

## Project configuration

`memoryhub config` generates a project-local `.memoryhub.yaml` and a companion `.claude/rules/memoryhub-loading.md` rule file. Both files are meant to be committed so every contributor's agent inherits the same loading policy.

`memoryhub config init` is an interactive wizard that asks about session shape, loading pattern, focus source, and retrieval defaults, then writes both files at the project root. If a legacy `.claude/rules/memoryhub-integration.md` already exists, it is backed up to `.bak` before the new rule file is written.

`memoryhub config regenerate` re-renders the rule file from `.memoryhub.yaml` after you hand-edit the YAML. It reads the YAML and rewrites the Markdown rule file only; it does not modify `.memoryhub.yaml`.

Per-developer connection params (`url`, `auth_url`, `client_id`, `client_secret`) live separately at `~/.config/memoryhub/config.json` and are managed by `memoryhub login`. They are not stored in `.memoryhub.yaml` and are not committed.

## Further documentation

The CLI is one surface of the [memory-hub](https://github.com/redhat-ai-americas/memory-hub) monorepo. For deeper context:

- **[Architecture overview](https://github.com/redhat-ai-americas/memory-hub/blob/main/docs/ARCHITECTURE.md)** — System design, deployment topology
- **[MCP server tool reference](https://github.com/redhat-ai-americas/memory-hub/blob/main/docs/mcp-server.md)** — The 15 tools the CLI wraps
- **[Agent memory ergonomics design](https://github.com/redhat-ai-americas/memory-hub/blob/main/docs/agent-memory-ergonomics/design.md)** — Full `.memoryhub.yaml` schema, rule file templates, and session-loading patterns
- **[Python SDK](https://pypi.org/project/memoryhub/)** — if you'd rather call the tools from Python

## Links

- **[GitHub repository](https://github.com/redhat-ai-americas/memory-hub)**
- **[Issue tracker](https://github.com/redhat-ai-americas/memory-hub/issues)**
- **[License (Apache 2.0)](https://github.com/redhat-ai-americas/memory-hub/blob/main/LICENSE)**

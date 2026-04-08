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

# Set up project-level memory loading
memoryhub config init
memoryhub config regenerate
```

## Project configuration

`memoryhub config` generates a project-local `.memoryhub.yaml` and a companion `.claude/rules/memoryhub-loading.md` rule file. Both files are meant to be committed so every contributor's agent inherits the same loading policy.

`memoryhub config init` is an interactive wizard that asks about session shape, loading pattern, focus source, and retrieval defaults, then writes both files at the project root. If a legacy `.claude/rules/memoryhub-integration.md` already exists, it is backed up to `.bak` before the new rule file is written.

`memoryhub config regenerate` re-renders the rule file from `.memoryhub.yaml` after you hand-edit the YAML. It reads the YAML and rewrites the Markdown rule file only; it does not modify `.memoryhub.yaml`.

Per-developer connection params (`url`, `auth_url`, `client_id`, `client_secret`) live separately at `~/.config/memoryhub/config.json` and are managed by `memoryhub login`. They are not stored in `.memoryhub.yaml` and are not committed.

See [the MemoryHub project docs](https://github.com/rdwj/memory-hub) for the
architecture, rule file templates, and the `.memoryhub.yaml` schema.

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

See [the MemoryHub project docs](https://github.com/rdwj/memory-hub) for the
architecture, rule file templates, and the `.memoryhub.yaml` schema.

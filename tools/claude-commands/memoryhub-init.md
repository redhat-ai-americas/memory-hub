---
description: Bootstrap MemoryHub integration in the current project
---

# MemoryHub Project Bootstrap

Set up MemoryHub integration for the current project by running the
interactive configuration wizard.

## Steps

1. Check if `memoryhub-cli` is installed:
   ```bash
   which memoryhub
   ```
   If not found, tell the user:
   > `memoryhub-cli` is not installed. Install it with:
   > ```
   > pip install memoryhub-cli
   > ```
   > Then run `/memoryhub-init` again.

   Stop here if not installed.

2. Run the interactive init wizard:
   ```bash
   memoryhub config init $ARGUMENTS
   ```
   This walks through session shape, loading pattern, focus source,
   contradiction detection, and campaign enrollment -- then writes
   `.memoryhub.yaml` and `.claude/rules/memoryhub-loading.md`.

3. After the wizard completes, remind the user of remaining setup:
   - **API key**: Create `~/.config/memoryhub/api-key` with their
     operator key (ask their administrator if they don't have one)
   - **MCP server**: Add the MemoryHub MCP server to Claude Code
     settings if not already configured
   - **Commit**: Both `.memoryhub.yaml` and
     `.claude/rules/memoryhub-loading.md` should be committed so
     every contributor's agent inherits the same loading policy

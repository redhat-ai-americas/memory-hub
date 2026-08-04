#!/usr/bin/env bash
# hooks/fetch-memory.sh -- Example setup_complete hook for memory loading
#
# Bound to the setup_complete event via hooks/setup-memory.yaml.
# Whatever this script prints to stdout is injected into the conversation
# context after agent setup. Exit 0 on any failure so the session starts
# normally without hook-provided context.
#
# Environment variables set by the hook system:
#   AGENT_NAME         -- the agent's configured name
#   AGENT_PROJECT_DIR  -- resolved base directory for the agent
#   HOOK_EVENT         -- the event that triggered this hook
#
# The working directory is set to AGENT_PROJECT_DIR.
#
# --- MemoryHub CLI example ---
# Uncomment the following to load memories via the MemoryHub CLI:
#
#   API_KEY_FILE="$HOME/.config/memoryhub/api-key"
#   [ -f "$API_KEY_FILE" ] || exit 0
#   export MEMORYHUB_API_KEY=$(tr -d '\n' < "$API_KEY_FILE")
#
#   memoryhub search \
#     "project context architecture preferences decisions" \
#     --project-id "$AGENT_NAME" \
#     --output compact \
#     --max 20 2>/dev/null || exit 0
#
# --- Static context file example ---
# cat ./context/session-context.md 2>/dev/null || exit 0

echo "Replace this hook with your own memory retrieval logic."

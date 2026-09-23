#!/bin/bash
# Pre-turn re-bias: search for memories relevant to the user's new message.
# Called from UserPromptSubmit hook. Injects results via additionalContext.
# Exits 0 silently on any failure -- the turn proceeds normally.

set -euo pipefail

# --- Credential resolution (same as load-memories.sh) ---

CREDS_FILE="$HOME/.config/memoryhub/credentials"
API_KEY_FILE="$HOME/.config/memoryhub/api-key"

if [ -z "${MEMORYHUB_API_KEY:-}" ]; then
  if [ -f "$CREDS_FILE" ]; then
    SECTION="${MEMORYHUB_CONTEXT:-default}"
    MEMORYHUB_API_KEY=$(awk -v section="$SECTION" '
      /^\[/ { in_section = ($0 == "[" section "]") }
      in_section && /^api_key[[:space:]]*=/ {
        sub(/^api_key[[:space:]]*=[[:space:]]*/, ""); print; exit
      }
    ' "$CREDS_FILE") || true
    if [ -z "${MEMORYHUB_API_KEY:-}" ] && [ "$SECTION" != "default" ]; then
      MEMORYHUB_API_KEY=$(awk '
        /^\[/ { in_section = ($0 == "[default]") }
        in_section && /^api_key[[:space:]]*=/ {
          sub(/^api_key[[:space:]]*=[[:space:]]*/, ""); print; exit
        }
      ' "$CREDS_FILE") || true
    fi
  elif [ -f "$API_KEY_FILE" ]; then
    MEMORYHUB_API_KEY=$(grep -v '^#' "$API_KEY_FILE" | tr -d '\n') || true
  fi
fi
[ -n "${MEMORYHUB_API_KEY:-}" ] || exit 0
export MEMORYHUB_API_KEY

# --- URL resolution ---
if [ -z "${MEMORYHUB_URL:-}" ] && [ -f "$CREDS_FILE" ]; then
  SECTION="${MEMORYHUB_CONTEXT:-default}"
  MEMORYHUB_URL=$(awk -v section="$SECTION" '
    /^\[/ { in_section = ($0 == "[" section "]") }
    in_section && /^url[[:space:]]*=/ {
      sub(/^url[[:space:]]*=[[:space:]]*/, ""); print; exit
    }
  ' "$CREDS_FILE") || true
  if [ -z "${MEMORYHUB_URL:-}" ] && [ "$SECTION" != "default" ]; then
    MEMORYHUB_URL=$(awk '
      /^\[/ { in_section = ($0 == "[default]") }
      in_section && /^url[[:space:]]*=/ {
        sub(/^url[[:space:]]*=[[:space:]]*/, ""); print; exit
      }
    ' "$CREDS_FILE") || true
  fi
fi
[ -n "${MEMORYHUB_URL:-}" ] || exit 0
export MEMORYHUB_URL

# --- Find CLI binary ---
PROJECT_ROOT="${CLAUDE_PROJECT_DIR:-$PWD}"
MEMORYHUB_BIN=$(command -v memoryhub 2>/dev/null) || true
if [ -z "$MEMORYHUB_BIN" ]; then
  for candidate in \
    "$PROJECT_ROOT/.venv/bin/memoryhub" \
    "$PROJECT_ROOT/memoryhub-cli/.venv/bin/memoryhub"; do
    [ -x "$candidate" ] && MEMORYHUB_BIN="$candidate" && break
  done
fi
[ -n "$MEMORYHUB_BIN" ] || exit 0

PROJECT_ID=$(basename "$PROJECT_ROOT")

# stdin from Claude Code contains JSON with "prompt" field.
# `memoryhub rebias` handles both JSON and plain text.
RESULTS=$("$MEMORYHUB_BIN" rebias \
  --project-id "$PROJECT_ID" \
  --output compact \
  --max 10 2>/dev/null) || exit 0

[ -n "$RESULTS" ] || exit 0

# Inject as additionalContext for the model to see.
python3 -c "
import json, sys
ctx = sys.stdin.read()
print(json.dumps({'additionalContext': ctx}))
" <<< "$RESULTS" || exit 0

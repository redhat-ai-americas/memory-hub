#!/bin/bash
# Post-turn extraction: extract facts/decisions/preferences from the model response.
# Called from Stop hook. Writes memories automatically via the extraction pipeline.
# Exits 0 silently on any failure -- does not block the user.

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
    ' "$CREDS_FILE")
    if [ -z "${MEMORYHUB_API_KEY:-}" ] && [ "$SECTION" != "default" ]; then
      MEMORYHUB_API_KEY=$(awk '
        /^\[/ { in_section = ($0 == "[default]") }
        in_section && /^api_key[[:space:]]*=/ {
          sub(/^api_key[[:space:]]*=[[:space:]]*/, ""); print; exit
        }
      ' "$CREDS_FILE")
    fi
  elif [ -f "$API_KEY_FILE" ]; then
    MEMORYHUB_API_KEY=$(grep -v '^#' "$API_KEY_FILE" | tr -d '\n')
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
  ' "$CREDS_FILE")
  if [ -z "${MEMORYHUB_URL:-}" ] && [ "$SECTION" != "default" ]; then
    MEMORYHUB_URL=$(awk '
      /^\[/ { in_section = ($0 == "[default]") }
      in_section && /^url[[:space:]]*=/ {
        sub(/^url[[:space:]]*=[[:space:]]*/, ""); print; exit
      }
    ' "$CREDS_FILE")
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

# stdin from Claude Code contains JSON with "last_assistant_message" field.
# `memoryhub extract` handles both JSON and plain text.
"$MEMORYHUB_BIN" extract \
  --project-id "$PROJECT_ID" \
  --output quiet 2>/dev/null || exit 0

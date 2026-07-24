#!/bin/bash
# Inject MemoryHub memories at Claude Code session start.
# Stdout is added to the conversation context before the first prompt.
# Exits 0 silently on any failure -- the session starts normally and
# the MCP server remains available as a fallback.

set -euo pipefail

# --- Credential resolution ---
# 1. MEMORYHUB_API_KEY env var (already set)
# 2. ~/.config/memoryhub/credentials (INI, MEMORYHUB_CONTEXT or [default])
# 3. ~/.config/memoryhub/api-key (flat file, backwards compat)

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

if [ -z "${MEMORYHUB_URL:-}" ]; then
  CONFIG_FILE="$HOME/.config/memoryhub/config.json"
  if [ -f "$CONFIG_FILE" ]; then
    if command -v jq >/dev/null 2>&1; then
      MEMORYHUB_URL=$(jq -r '.url // empty' "$CONFIG_FILE" 2>/dev/null) || true
    elif command -v python3 >/dev/null 2>&1; then
      MEMORYHUB_URL=$(python3 -c \
        "import json,sys; print(json.load(open(sys.argv[1])).get('url',''))" \
        "$CONFIG_FILE" 2>/dev/null) || true
    else
      MEMORYHUB_URL=$(grep -o '"url"[[:space:]]*:[[:space:]]*"[^"]*"' \
        "$CONFIG_FILE" 2>/dev/null | head -1 \
        | sed 's/.*"url"[[:space:]]*:[[:space:]]*"//;s/"$//') || true
    fi
  fi
fi
[ -n "${MEMORYHUB_URL:-}" ] || exit 0
export MEMORYHUB_URL

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

"$MEMORYHUB_BIN" search \
  "project context architecture preferences decisions workflow" \
  --project-id "$PROJECT_ID" \
  --output compact \
  --max 20 2>/dev/null || exit 0

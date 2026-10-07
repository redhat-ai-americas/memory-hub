#!/bin/bash
# Inject the compiled persona synopsis at session start — WRIG-1483 Phase 1 POC.
#
# Always runs BEFORE load-memories.sh so the standing profile is injected
# first (weight=1.0, unconditional) and search results follow after.
# Exits 0 silently on any failure — session starts normally without the profile.
#
# User ID resolution (first match wins):
#   1. MEMORYHUB_USER_ID env var
#   2. user_id in ~/.config/memoryhub/credentials (MEMORYHUB_CONTEXT section or [default])
#
# If no user_id is found, exits 0 silently (hook is a no-op until configured).
# Run 'memoryhub persona compile --user <id>' to generate a synopsis first.

set -euo pipefail

# --- Credential resolution (mirrors load-memories.sh) ---

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

# --- User ID resolution ---
if [ -z "${MEMORYHUB_USER_ID:-}" ] && [ -f "$CREDS_FILE" ]; then
  SECTION="${MEMORYHUB_CONTEXT:-default}"
  MEMORYHUB_USER_ID=$(awk -v section="$SECTION" '
    /^\[/ { in_section = ($0 == "[" section "]") }
    in_section && /^user_id[[:space:]]*=/ {
      sub(/^user_id[[:space:]]*=[[:space:]]*/, ""); print; exit
    }
  ' "$CREDS_FILE") || true
  if [ -z "${MEMORYHUB_USER_ID:-}" ] && [ "$SECTION" != "default" ]; then
    MEMORYHUB_USER_ID=$(awk '
      /^\[/ { in_section = ($0 == "[default]") }
      in_section && /^user_id[[:space:]]*=/ {
        sub(/^user_id[[:space:]]*=[[:space:]]*/, ""); print; exit
      }
    ' "$CREDS_FILE") || true
  fi
fi
# No user_id → no-op. This is expected on first install before 'memoryhub persona compile'.
[ -n "${MEMORYHUB_USER_ID:-}" ] || exit 0

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

# --- Fetch persona synopsis in compact mode (outputs <memoryhub-persona> block) ---
SYNOPSIS=$("$MEMORYHUB_BIN" persona show \
  --user "$MEMORYHUB_USER_ID" \
  --output compact 2>/dev/null) || exit 0

# If no synopsis exists yet, the command outputs nothing (no-op).
[ -n "$SYNOPSIS" ] || exit 0

# Emit the block to stdout — Claude Code injects it as additionalContext
# before the first prompt. load-memories.sh runs after and appends search hits.
printf '%s\n' "$SYNOPSIS"

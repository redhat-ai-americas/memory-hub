#!/bin/sh
# Record MemoryHub activity without storing prompt or memory content.
# Missing CLI setup is a no-op so hook failures never block the host.

set -eu
EVENT=${1:-}
PROJECT_ROOT=${CLAUDE_PROJECT_DIR:-}
if [ -z "$PROJECT_ROOT" ]; then
  PROJECT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
fi

MEMORYHUB_BIN=$(command -v memoryhub 2>/dev/null || true)
if [ -z "$MEMORYHUB_BIN" ]; then
  for candidate in     "$PROJECT_ROOT/.venv/bin/memoryhub"     "$PROJECT_ROOT/memoryhub-cli/.venv/bin/memoryhub"; do
    if [ -x "$candidate" ]; then
      MEMORYHUB_BIN=$candidate
      break
    fi
  done
fi
[ -n "$MEMORYHUB_BIN" ] || exit 0
"$MEMORYHUB_BIN" activity-hook --event "$EVENT" || exit 0

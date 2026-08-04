#!/bin/bash
# Record the SOC demo harness output with asciinema.
#
# Produces a .cast file that can be replayed with `asciinema play`,
# converted to GIF with `agg`, or converted to SVG with `svg-term-cli`.
#
# Usage:
#   cd memory-hub
#   bash demos/soc-demo/record.sh
#
# Environment:
#   MEMORYHUB_URL       -- MCP server URL (default: reads from credentials)
#   MEMORYHUB_API_KEY   -- API key (default: reads from credentials)
#   MEMORYHUB_CONTEXT   -- Credentials section (default: mcp-rhoai)
#   HARNESS_PHASE_PAUSE -- Seconds between phases (default: 3.0 for recording)
#   HARNESS_ACTION_PAUSE -- Seconds between actions (default: 1.5 for recording)
#
# Output: demos/soc-demo/recordings/soc-demo-YYYY-MM-DD-HHMMSS.cast

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
RECORDINGS_DIR="$SCRIPT_DIR/recordings"

mkdir -p "$RECORDINGS_DIR"

TIMESTAMP=$(date +%Y-%m-%d-%H%M%S)
CAST_FILE="$RECORDINGS_DIR/soc-demo-${TIMESTAMP}.cast"

# Recording-friendly pacing (slower than smoke-test defaults)
export HARNESS_PHASE_PAUSE="${HARNESS_PHASE_PAUSE:-3.0}"
export HARNESS_ACTION_PAUSE="${HARNESS_ACTION_PAUSE:-1.5}"

# Terminal dimensions for readability at conference resolution
COLS=132
ROWS=42

echo "SOC Demo Recording"
echo "==================="
echo "Output: $CAST_FILE"
echo "Terminal: ${COLS}x${ROWS}"
echo "Phase pause: ${HARNESS_PHASE_PAUSE}s"
echo "Action pause: ${HARNESS_ACTION_PAUSE}s"
echo ""
echo "Starting in 3 seconds..."
sleep 3

# Record with asciinema
asciinema rec "$CAST_FILE" \
  --cols "$COLS" \
  --rows "$ROWS" \
  --title "MemoryHub SOC Demo - Cross-Framework Incident Response" \
  --command "cd $REPO_DIR && python demos/soc-demo/harness.py 2>/dev/null" \
  --overwrite

echo ""
echo "Recording saved: $CAST_FILE"
echo ""
echo "Replay:  asciinema play $CAST_FILE"
echo "Speed:   asciinema play --speed=1.5 $CAST_FILE"
echo ""
echo "To convert to GIF (requires agg):"
echo "  agg $CAST_FILE ${CAST_FILE%.cast}.gif --cols $COLS --rows $ROWS --font-size 18"
echo ""
echo "To convert to SVG (requires svg-term-cli):"
echo "  svg-term --in $CAST_FILE --out ${CAST_FILE%.cast}.svg --width $COLS --height $ROWS"

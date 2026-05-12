#!/usr/bin/env bash
#
# Update the MemoryHub MCP server discovery file with a new URL.
#
# This script updates docs/public/discovery.json with the current MCP server
# URL for a given instance (default: "sandbox"). The discovery file is published
# via GitHub Pages to provide a stable discovery endpoint for downstream consumers
# like kagenti-adk E2E tests.
#
# Usage:
#   scripts/update-discovery.sh [--instance NAME] [--push] <mcp-url>
#
# Options:
#   --instance NAME   Instance name to update (default: "sandbox")
#   --push            Push the commit to remote after updating
#
# Example:
#   scripts/update-discovery.sh https://memory-hub-mcp-memory-hub-mcp.apps.cluster-abc.example.com/mcp/
#   scripts/update-discovery.sh --instance prod --push https://mcp.example.com/mcp/
#

set -euo pipefail

INSTANCE="sandbox"
PUSH=false
MCP_URL=""

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --instance)
            INSTANCE="$2"
            shift 2
            ;;
        --push)
            PUSH=true
            shift
            ;;
        *)
            if [[ -z "$MCP_URL" ]]; then
                MCP_URL="$1"
                shift
            else
                echo "Error: unexpected argument: $1" >&2
                exit 1
            fi
            ;;
    esac
done

if [[ -z "$MCP_URL" ]]; then
    echo "Error: MCP URL is required" >&2
    echo "Usage: $0 [--instance NAME] [--push] <mcp-url>" >&2
    exit 1
fi

# Get the repo root
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DISCOVERY_FILE="$REPO_ROOT/docs/public/discovery.json"

if [[ ! -f "$DISCOVERY_FILE" ]]; then
    echo "Error: discovery file not found at $DISCOVERY_FILE" >&2
    exit 1
fi

# Get current date
CURRENT_DATE="$(date +%Y-%m-%d)"

# Update the discovery file using Python (arguments passed via sys.argv to avoid injection)
python3 -c '
import json, sys

discovery_file, instance, mcp_url, current_date = sys.argv[1:5]

with open(discovery_file, "r") as f:
    data = json.load(f)

data.setdefault("instances", {})

if instance in data["instances"]:
    data["instances"][instance]["mcp_url"] = mcp_url
    data["instances"][instance]["updated"] = current_date
else:
    data["instances"][instance] = {
        "mcp_url": mcp_url,
        "environment": instance,
        "updated": current_date,
        "status": "active",
    }

with open(discovery_file, "w") as f:
    json.dump(data, f, indent=2)
    f.write("\n")

print(f"Updated {instance} instance MCP URL to: {mcp_url}")
' "$DISCOVERY_FILE" "$INSTANCE" "$MCP_URL" "$CURRENT_DATE"

# Commit the change
cd "$REPO_ROOT"
git add "$DISCOVERY_FILE"
git commit -m "discovery: Update $INSTANCE MCP URL"

echo ""
echo "Discovery file updated and committed."
echo "The file will be published at: https://redhat-ai-americas.github.io/memory-hub/discovery.json"

# Push if requested
if [[ "$PUSH" == "true" ]]; then
    CURRENT_BRANCH="$(git branch --show-current)"
    git push origin "$CURRENT_BRANCH"
    echo "Changes pushed to origin/$CURRENT_BRANCH"
fi

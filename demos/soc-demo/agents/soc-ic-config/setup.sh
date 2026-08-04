#!/bin/bash
# Configure OpenClaw inside an OpenShell sandbox for the IC role.
# Run this inside the sandbox after creation.

# Add MemoryHub as an MCP server
openclaw mcp add memoryhub \
  --transport streamable-http \
  --url http://memory-hub-mcp.memory-hub-mcp.svc.cluster.local:8080/mcp/

# Copy the SOUL.md (OpenClaw's identity file) to the right location
if [ -f /sandbox/SOUL.md ]; then
  cp /sandbox/SOUL.md ~/.openclaw/SOUL.md
fi

echo "OpenClaw IC agent configured."
echo "Start with: openclaw"

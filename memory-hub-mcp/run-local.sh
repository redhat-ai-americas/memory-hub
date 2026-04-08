#!/usr/bin/env bash
# Run MCP server locally with database connection to port-forwarded PostgreSQL
: "${MEMORYHUB_DB_PASSWORD:?MEMORYHUB_DB_PASSWORD must be set (matching the POSTGRES_PASSWORD in deploy/postgresql/secret.yaml)}"
export MEMORYHUB_DB_HOST=localhost
export MEMORYHUB_DB_PORT=5432
export MEMORYHUB_DB_NAME=memoryhub
export MEMORYHUB_DB_USER=memoryhub
export MCP_TRANSPORT=stdio
export MCP_LOG_LEVEL=WARNING

cd "$(dirname "$0")"
exec .venv/bin/python -m src.main

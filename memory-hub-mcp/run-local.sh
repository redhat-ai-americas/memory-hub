#!/usr/bin/env bash
# Run MCP server locally with database connection to port-forwarded PostgreSQL
export MEMORYHUB_DB_HOST=localhost
export MEMORYHUB_DB_PORT=5432
export MEMORYHUB_DB_NAME=memoryhub
export MEMORYHUB_DB_USER=memoryhub
export MEMORYHUB_DB_PASSWORD=memoryhub-dev-password
export MCP_TRANSPORT=stdio
export MCP_LOG_LEVEL=WARNING

cd "$(dirname "$0")"
exec .venv/bin/python -m src.main

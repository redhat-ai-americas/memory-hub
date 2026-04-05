.PHONY: help install test test-integration deploy-all deploy-db deploy-mcp migrate clean-mcp

# Default target
help:
	@echo "MemoryHub — Available Commands"
	@echo "=============================="
	@echo ""
	@echo "Local Development:"
	@echo "  make install     - Install core library and dev dependencies"
	@echo "  make test             - Run all tests (core + MCP server)"
	@echo "  make test-integration - Run integration tests against real PostgreSQL"
	@echo ""
	@echo "OpenShift Deployment:"
	@echo "  make deploy-all  - Full stack deploy (PostgreSQL + migrations + MCP server)"
	@echo "  make deploy-db   - Deploy PostgreSQL only"
	@echo "  make deploy-mcp  - Deploy MCP server only (skip DB + migrations)"
	@echo "  make migrate     - Run Alembic migrations only"
	@echo "  make clean-mcp   - Remove MCP server from OpenShift"
	@echo ""

# Install core library in development mode
install:
	python3 -m venv .venv
	.venv/bin/pip install --upgrade pip
	.venv/bin/pip install -e '.[dev]'
	@echo "Activate with: source .venv/bin/activate"

# Run all tests
test:
	.venv/bin/pytest tests/ -q -m "not integration"
	cd memory-hub-mcp && ../.venv/bin/pytest tests/ -q

# Run integration tests against real PostgreSQL + pgvector
test-integration:
	scripts/run-integration-tests.sh

# Full stack deployment
deploy-all:
	scripts/deploy-full.sh

# PostgreSQL only
deploy-db:
	scripts/deploy-full.sh --skip-migrations --skip-mcp

# MCP server only (assumes DB + migrations already done)
deploy-mcp:
	scripts/deploy-full.sh --skip-db --skip-migrations

# Alembic migrations only
migrate:
	scripts/run-migrations.sh

# Remove MCP server
clean-mcp:
	cd memory-hub-mcp && make clean PROJECT=memory-hub-mcp

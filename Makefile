.PHONY: help install uninstall dev check-prereqs test test-integration test-auth \
        deploy-all deploy-db deploy-mcp deploy-auth deploy-ui deploy-tile \
        migrate clean-mcp clean-auth

# Default target
help:
	@echo "MemoryHub — Available Commands"
	@echo "=============================="
	@echo ""
	@echo "Cluster install (for evaluators and operators):"
	@echo "  make check-prereqs  - Verify cluster prerequisites without deploying"
	@echo "  make install        - Full stack install: DB + migrations + MCP + auth + UI + RHOAI tile"
	@echo "  make uninstall      - Remove all MemoryHub resources from the cluster"
	@echo ""
	@echo "Partial deploys (advanced):"
	@echo "  make deploy-db      - PostgreSQL + pgvector only"
	@echo "  make deploy-mcp     - MCP server only (assumes DB + migrations done)"
	@echo "  make deploy-auth    - Auth service only"
	@echo "  make deploy-ui      - Dashboard UI only"
	@echo "  make deploy-tile    - RHOAI Applications tile only"
	@echo "  make migrate        - Alembic migrations only"
	@echo "  make clean-mcp      - Remove MCP server from cluster"
	@echo "  make clean-auth     - Remove auth service from cluster"
	@echo ""
	@echo "Local development:"
	@echo "  make dev            - Set up .venv and install core + dev deps"
	@echo "  make test           - Run all tests (core + MCP server)"
	@echo "  make test-integration - Run integration tests against real PostgreSQL"
	@echo "  make test-auth      - Run auth service tests"
	@echo ""
	@echo "Backward compatibility:"
	@echo "  make deploy-all     - Alias for 'make install'"
	@echo ""

# ---------------------------------------------------------------------------
# Cluster install
# ---------------------------------------------------------------------------

install:
	scripts/deploy-full.sh

uninstall:
	scripts/uninstall-full.sh

check-prereqs:
	scripts/check-prereqs.sh

# Backward compat
deploy-all: install

# ---------------------------------------------------------------------------
# Partial deploys
# ---------------------------------------------------------------------------

deploy-db:
	scripts/deploy-full.sh --skip-migrations --skip-mcp --skip-auth --skip-ui --skip-tile

deploy-mcp:
	scripts/deploy-full.sh --skip-db --skip-migrations --skip-auth --skip-ui --skip-tile

deploy-auth:
	cd memoryhub-auth && make deploy PROJECT=memoryhub-auth

deploy-ui:
	memoryhub-ui/deploy/deploy.sh

deploy-tile:
	oc apply -f memoryhub-ui/openshift/odh-application.yaml -n redhat-ods-applications

migrate:
	scripts/run-migrations.sh

clean-mcp:
	cd memory-hub-mcp && make clean PROJECT=memory-hub-mcp

clean-auth:
	cd memoryhub-auth && make clean PROJECT=memoryhub-auth

# ---------------------------------------------------------------------------
# Local development
# ---------------------------------------------------------------------------

dev:
	python3 -m venv .venv
	.venv/bin/pip install --upgrade pip
	.venv/bin/pip install -e '.[dev]'
	@echo "Activate with: source .venv/bin/activate"

test:
	.venv/bin/pytest tests/ -q -m "not integration"
	cd memory-hub-mcp && ../.venv/bin/pytest tests/ -q

test-auth:
	cd memoryhub-auth && make test

test-integration:
	scripts/run-integration-tests.sh

.PHONY: install run-local test test-local deploy clean help

# Variables
VENV ?= .venv
PYTHON ?= python3

# The OpenShift namespace is hardcoded in deploy/deploy.sh on purpose.
# See the comment in that script for the history.
NAMESPACE := memory-hub-mcp

# Default target
help:
	@echo "memory-hub-mcp - Available Commands"
	@echo "==================================="
	@echo "Local Development:"
	@echo "  make install     - Install dependencies"
	@echo "  make run-local   - Run server locally (STDIO mode)"
	@echo "  make test-local  - Test with cmcp locally"
	@echo "  make test        - Run pytest suite"
	@echo ""
	@echo "OpenShift Deployment (always to namespace: $(NAMESPACE)):"
	@echo "  make deploy      - Build + deploy via deploy/deploy.sh"
	@echo "  make clean       - Remove from OpenShift"
	@echo ""
	@echo "Other:"
	@echo "  make help        - Show this help message"

# Install dependencies
install:
	$(PYTHON) -m venv $(VENV)
	$(VENV)/bin/pip install --upgrade pip
	$(VENV)/bin/pip install -r requirements.txt
	@echo "✅ Installation complete. Activate with: source $(VENV)/bin/activate"

# Run locally with STDIO for cmcp testing
run-local: install
	@echo "Starting MCP server in STDIO mode..."
	@echo "Test with: cmcp '$(VENV)/bin/python -m src.main' tools/list"
	MCP_TRANSPORT=stdio MCP_HOT_RELOAD=1 $(VENV)/bin/python -m src.main

# Test locally with cmcp
test-local:
	@echo "Testing MCP server with cmcp..."
	@echo "Listing tools..."
	@cmcp "$(VENV)/bin/python -m src.main" tools/list || echo "cmcp not installed. Install with: pip install cmcp"

# Run pytest tests
test:
	$(VENV)/bin/pytest tests/ -v

# Deploy to OpenShift (namespace is hardcoded in deploy/deploy.sh)
deploy:
	./deploy/deploy.sh

# Clean up OpenShift deployment
clean:
	@echo "Cleaning up namespace: $(NAMESPACE)"
	@oc delete -f deploy/openshift.yaml -n $(NAMESPACE) --ignore-not-found=true || echo "Not deployed or already cleaned"
	@oc delete -f deploy/users-configmap.yaml -n $(NAMESPACE) --ignore-not-found=true || true

# Development shortcuts
dev: run-local

.PHONY: install run-local test test-local deploy clean help

# Variables
VENV ?= .venv
PYTHON ?= python3
PROJECT ?= mcp-demo

# Default target
help:
	@echo "MCP Server Template - Available Commands"
	@echo "========================================"
	@echo "Local Development:"
	@echo "  make install     - Install dependencies"
	@echo "  make run-local   - Run server locally (STDIO mode)"
	@echo "  make test-local  - Test with cmcp locally"
	@echo "  make test        - Run pytest suite"
	@echo ""
	@echo "OpenShift Deployment:"
	@echo "  make deploy      - Deploy to OpenShift (PROJECT=name)"
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

# Deploy to OpenShift
deploy:
	@echo "Deploying to OpenShift project: $(PROJECT)"
	./deploy.sh $(PROJECT)

# Clean up OpenShift deployment
clean:
	@echo "Cleaning up OpenShift project: $(PROJECT)"
	@oc delete -f openshift.yaml -n $(PROJECT) --ignore-not-found=true || echo "Not deployed or already cleaned"

# Development shortcuts
dev: run-local

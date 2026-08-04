# =============================================================================
# Agent Template — Makefile
# =============================================================================
# Developer-facing targets for the agent-loop template.
# Run `make` or `make help` to see available commands.
# =============================================================================

# ---------------------------------------------------------------------------
# Variables (override on the command line: make deploy PROJECT=my-agent)
# ---------------------------------------------------------------------------
VENV        ?= .venv
PYTHON      ?= python3
PROJECT     ?= soc-forensics
IMAGE_NAME  ?= soc-forensics
IMAGE_TAG   ?= latest
CONTEXT     ?=

# Derived
PIP         := $(VENV)/bin/pip
PYTEST      := $(VENV)/bin/pytest
PYTHON_VENV := $(VENV)/bin/python
OC_CTX      := $(if $(CONTEXT),--context=$(CONTEXT))

# ---------------------------------------------------------------------------
# Default target
# ---------------------------------------------------------------------------
.DEFAULT_GOAL := help

# ---------------------------------------------------------------------------
# Development
# ---------------------------------------------------------------------------

.PHONY: install
install: ## Create venv and install all dependencies (dev + memory extras)
	$(PYTHON) -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -e ".[dev,memory]"

.PHONY: run-local
run-local: ## Run the agent locally (HTTP server on port 8080)
	$(PYTHON_VENV) -m src.agent

.PHONY: test
test: ## Run tests with verbose output
	$(PYTEST) -v

.PHONY: test-cov
test-cov: ## Run tests with coverage report
	$(PYTEST) -v --cov=src --cov-report=term-missing --cov-report=html

.PHONY: eval
eval: ## Run eval cases against the agent (mock LLM)
	$(PYTHON_VENV) -m evals.run_evals

.PHONY: lint
lint: ## Run ruff linter (install ruff into venv if missing)
	@$(VENV)/bin/ruff check src/ tests/ evals/ 2>/dev/null \
		|| (echo "ruff not found — installing into venv..." \
		    && $(PIP) install ruff \
		    && $(VENV)/bin/ruff check src/ tests/ evals/)

# ---------------------------------------------------------------------------
# Container
# ---------------------------------------------------------------------------

.PHONY: build
build: ## Build container image with podman (linux/amd64 for OpenShift)
	podman build \
		--platform linux/amd64 \
		-t $(IMAGE_NAME):$(IMAGE_TAG) \
		-f Containerfile . \
		--no-cache

# ---------------------------------------------------------------------------
# Deployment
# ---------------------------------------------------------------------------

.PHONY: deploy
deploy: ## Deploy to OpenShift (make deploy PROJECT=<name>)
	CONTEXT=$(CONTEXT) ./deploy.sh $(PROJECT)

.PHONY: redeploy
redeploy: ## Force-redeploy to OpenShift (pulls fresh image, restarts pods)
	CONTEXT=$(CONTEXT) ./redeploy.sh $(PROJECT) $(IMAGE_TAG)

.PHONY: clean
clean: ## Remove agent resources from OpenShift (make clean PROJECT=<name>)
	@if [ -z "$(PROJECT)" ]; then \
		echo "Error: PROJECT is required.  Usage: make clean PROJECT=my-agent"; \
		exit 1; \
	fi
	@echo "Removing agent resources from project $(PROJECT)..."
	oc delete deployment $(IMAGE_NAME) -n $(PROJECT) $(OC_CTX) --ignore-not-found
	oc delete service $(IMAGE_NAME) -n $(PROJECT) $(OC_CTX) --ignore-not-found
	oc delete configmap $(IMAGE_NAME)-config -n $(PROJECT) $(OC_CTX) --ignore-not-found
	oc delete route $(IMAGE_NAME) -n $(PROJECT) $(OC_CTX) --ignore-not-found
	@echo "Done."

# ---------------------------------------------------------------------------
# fipsagents vendoring
# ---------------------------------------------------------------------------

.PHONY: vendor
vendor: ## Vendor fipsagents source into this project (replaces PyPI dependency)
	fips-agents vendor

.PHONY: update-fipsagents
update-fipsagents: ## Update vendored fipsagents to latest upstream version
	fips-agents vendor --update

.PHONY: update-framework
update-framework: ## Deprecated alias for update-fipsagents (will be removed in a future release)
	@echo "warning: 'make update-framework' is deprecated; use 'make update-fipsagents' instead." >&2
	@$(MAKE) update-fipsagents

# ---------------------------------------------------------------------------
# Help
# ---------------------------------------------------------------------------

.PHONY: help
help: ## Show this help message
	@echo ""
	@echo "Agent Template — available targets"
	@echo "=================================="
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "Variables (override on CLI):"
	@echo "  PROJECT     OpenShift project/namespace  (default: $(PROJECT))"
	@echo "  IMAGE_NAME  Container image name         (default: $(IMAGE_NAME))"
	@echo "  IMAGE_TAG   Container image tag          (default: $(IMAGE_TAG))"
	@echo "  CONTEXT     Kubernetes context (optional) (default: active context)"
	@echo "  VENV        Virtual-env directory         (default: $(VENV))"
	@echo ""

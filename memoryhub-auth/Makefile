.PHONY: install test deploy clean help

VENV ?= .venv
PYTHON ?= python3
PROJECT ?= memoryhub-auth

help:
	@echo "MemoryHub Auth — Available Commands"
	@echo "===================================="
	@echo "Local Development:"
	@echo "  make install     - Install dependencies"
	@echo "  make test        - Run pytest suite"
	@echo "  make run-local   - Run auth server locally"
	@echo ""
	@echo "OpenShift Deployment:"
	@echo "  make deploy      - Deploy to OpenShift (PROJECT=name)"
	@echo "  make clean       - Remove from OpenShift"

install:
	$(PYTHON) -m venv $(VENV)
	$(VENV)/bin/pip install --upgrade pip
	$(VENV)/bin/pip install -e '.[dev]'

test:
	$(VENV)/bin/pytest tests/ -v

run-local:
	AUTH_ISSUER=http://localhost:8081 $(VENV)/bin/python -m src.main

deploy:
	@echo "Deploying to OpenShift project: $(PROJECT)"
	./deploy.sh $(PROJECT)

clean:
	@echo "Cleaning up OpenShift project: $(PROJECT)"
	@oc delete -f openshift.yaml -n $(PROJECT) --ignore-not-found=true || echo "Not deployed or already cleaned"

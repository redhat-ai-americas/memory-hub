#!/usr/bin/env bash
# Create the MemoryHub Python project directory structure.
# Per project conventions, directory creation goes through a shell script.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "Creating MemoryHub project structure in ${ROOT}..."

# Core library
mkdir -p "${ROOT}/src/memoryhub/models"
mkdir -p "${ROOT}/src/memoryhub/storage"
mkdir -p "${ROOT}/src/memoryhub/services"

# Tests
mkdir -p "${ROOT}/tests/test_models"
mkdir -p "${ROOT}/tests/test_storage"
mkdir -p "${ROOT}/tests/test_services"

# Alembic migrations
mkdir -p "${ROOT}/alembic/versions"

# GitHub Actions
mkdir -p "${ROOT}/.github/workflows"

echo "Directory structure created."

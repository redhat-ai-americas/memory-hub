#!/usr/bin/env bash
#
# release.sh - Monorepo-aware release script for memory-hub
#
# Usage: ./scripts/release.sh <component> <version> "<description>"
#
# Example: ./scripts/release.sh sdk 0.2.0 "Add search_memory and write_memory"
#
# Components:
#   sdk  - MemoryHub Python SDK (sdk/)
#   mcp  - MemoryHub MCP Server (memory-hub-mcp/)  [future]
#

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

print_success() { echo -e "${GREEN}✓${NC} $1"; }
print_error() { echo -e "${RED}✗${NC} $1"; }
print_info() { echo -e "${YELLOW}ℹ${NC} $1"; }

if [ $# -ne 3 ]; then
    print_error "Usage: $0 <component> <version> <description>"
    echo "Example: $0 sdk 0.2.0 \"Add search_memory and write_memory\""
    echo
    echo "Components: sdk"
    exit 1
fi

COMPONENT=$1
VERSION=$2
COMMIT_MSG=$3

# Resolve component paths
case "$COMPONENT" in
    sdk)
        VERSION_FILE="sdk/src/memoryhub/__init__.py"
        PYPROJECT_FILE="sdk/pyproject.toml"
        ;;
    # mcp)
    #     VERSION_FILE="memory-hub-mcp/src/__init__.py"  # TODO: add when MCP server gets PyPI releases
    #     PYPROJECT_FILE="memory-hub-mcp/pyproject.toml"
    #     ;;
    *)
        print_error "Unknown component: $COMPONENT"
        echo "Valid components: sdk, mcp"
        exit 1
        ;;
esac

TAG="${COMPONENT}/v${VERSION}"

if ! [[ $VERSION =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    print_error "Invalid version format: $VERSION"
    echo "Version must be in format: x.y.z (e.g., 0.2.0)"
    exit 1
fi

print_info "Preparing release ${TAG}"
echo

# Must run from project root
if [ ! -f "pyproject.toml" ] && [ ! -d "sdk" ]; then
    print_error "Must run from project root directory"
    exit 1
fi

if [ ! -f "$VERSION_FILE" ] || [ ! -f "$PYPROJECT_FILE" ]; then
    print_error "Component files not found:"
    echo "  version file: $VERSION_FILE"
    echo "  pyproject:    $PYPROJECT_FILE"
    exit 1
fi

# Check for uncommitted changes (excluding the files we're about to modify)
if ! git diff --quiet --exit-code -- ":!$VERSION_FILE" ":!$PYPROJECT_FILE"; then
    print_error "You have uncommitted changes. Please commit or stash them first."
    git status --short
    exit 1
fi

print_info "Updating $VERSION_FILE to $VERSION"
sed -i.bak "s/^__version__ = .*/__version__ = \"$VERSION\"/" "$VERSION_FILE"
rm -f "${VERSION_FILE}.bak"
print_success "Updated $VERSION_FILE"

print_info "Updating $PYPROJECT_FILE to $VERSION"
sed -i.bak "s/^version = .*/version = \"$VERSION\"/" "$PYPROJECT_FILE"
rm -f "${PYPROJECT_FILE}.bak"
print_success "Updated $PYPROJECT_FILE"

print_info "Verifying version updates..."
VERSION_PY=$(grep -E '^__version__' "$VERSION_FILE" | cut -d'"' -f2)
VERSION_TOML=$(grep -E '^version' "$PYPROJECT_FILE" | head -1 | cut -d'"' -f2)

if [ "$VERSION_PY" != "$VERSION" ] || [ "$VERSION_TOML" != "$VERSION" ]; then
    print_error "Version verification failed!"
    echo "  $VERSION_FILE: $VERSION_PY"
    echo "  $PYPROJECT_FILE: $VERSION_TOML"
    echo "  expected: $VERSION"
    exit 1
fi
print_success "Version verification passed"

echo
print_info "Changes to be committed:"
git diff "$VERSION_FILE" "$PYPROJECT_FILE"
echo

print_info "Committing changes..."
git add "$VERSION_FILE" "$PYPROJECT_FILE"
git commit -m "$COMMIT_MSG"
print_success "Changes committed"

print_info "Pushing to main..."
git push origin main
print_success "Pushed to main"

print_info "Creating tag ${TAG}..."
git tag "$TAG"
print_success "Tag created"

print_info "Pushing tag ${TAG}..."
git push origin "$TAG"
print_success "Tag pushed"

echo
print_success "Release ${TAG} initiated!"
echo
echo "GitHub Actions will now:"
echo "  1. Create GitHub Release"
echo "  2. Build distribution packages"
echo "  3. Publish to PyPI"
echo
echo "Monitor progress at: https://github.com/redhat-ai-americas/memory-hub/actions"
echo "View release at: https://github.com/redhat-ai-americas/memory-hub/releases/tag/${TAG}"

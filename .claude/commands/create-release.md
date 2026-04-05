# Create Release

Help me create a new release of a memory-hub component.

## Steps

1. Ask me which component to release (`sdk` for the memoryhub PyPI package)
2. Ask me for the version number (should follow semver: major.minor.patch)
3. Ask me for a brief description of what changed in this release
4. Run the component's tests to make sure they pass
5. Run the release script: `./scripts/release.sh <component> <version> "<description>"`

## Components

| Component | Package | PyPI |
|-----------|---------|------|
| `sdk` | memoryhub | https://pypi.org/p/memoryhub |

## Notes

- The release script handles updating version files, pyproject.toml, committing, tagging, and pushing
- Tags follow the pattern `<component>/v<version>` (e.g., `sdk/v0.2.0`)
- GitHub Actions will automatically create a GitHub Release and publish to PyPI
- Make sure all tests pass before releasing
- The `sdk` version lives in `sdk/src/memoryhub/__init__.py` and `sdk/pyproject.toml`

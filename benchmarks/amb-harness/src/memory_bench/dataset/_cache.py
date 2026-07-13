import os
from pathlib import Path


def dataset_cache_dir(name: str) -> Path:
    """Return .datasets/<name> under a writable cache root, creating it if needed."""
    override = os.environ.get("OMB_CACHE_DIR")
    if override:
        path = Path(override) / name
        path.mkdir(parents=True, exist_ok=True)
        return path
    # Walk up from this file until we find pyproject.toml
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").exists():
            path = parent / ".datasets" / name
            path.mkdir(parents=True, exist_ok=True)
            return path
    # Fallback: next to this file
    path = here.parent / ".datasets" / name
    path.mkdir(parents=True, exist_ok=True)
    return path

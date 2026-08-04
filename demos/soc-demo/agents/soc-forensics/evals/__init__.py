"""Eval package for BaseAgent agents.

Sets up sys.path so that ``fipsagents.baseagent`` and the template root are importable
from any submodule, and exports the shared path constants used throughout the
eval suite.
"""

from __future__ import annotations

import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Shared path constants
# ---------------------------------------------------------------------------

_EVALS_DIR = Path(__file__).resolve().parent
_TEMPLATE_ROOT = _EVALS_DIR.parent
_FIXTURES_DIR = _EVALS_DIR / "fixtures"

# Ensure the src/ directory and template root are importable.
_src_dir = str(_TEMPLATE_ROOT / "src")
_root_dir = str(_TEMPLATE_ROOT)
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)
if _root_dir not in sys.path:
    sys.path.insert(0, _root_dir)

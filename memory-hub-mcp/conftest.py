"""Pytest configuration for MCP server projects.

This file is placed at the project root to ensure the src directory
is added to Python's path before any test modules are imported.
"""

import sys
from pathlib import Path

# Add the src directory to Python path
project_root = Path(__file__).parent
src_path = project_root / "src"

if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

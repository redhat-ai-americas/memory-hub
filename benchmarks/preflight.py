#!/usr/bin/env python3
"""Standalone preflight runner.

Imports the preflight module directly (bypassing the adapter package
__init__.py which pulls in the full EvalHub SDK chain).

Usage:
    python benchmarks/preflight.py [--config path/to/config.yaml]

Environment:
    MEMORYHUB_DB_HOST, MEMORYHUB_DB_PORT, MEMORYHUB_DB_USER,
    MEMORYHUB_DB_PASS, MEMORYHUB_DB_NAME -- database connection
    MEMORYHUB_RERANKER_URL -- reranker endpoint (optional)
    MEMORYHUB_TENANT_ID -- target tenant (default: amb-benchmark)
"""

import importlib.util
import sys
from pathlib import Path

_preflight_path = (
    Path(__file__).resolve().parent
    / "evalhub-adapter"
    / "src"
    / "memoryhub_evalhub"
    / "preflight.py"
)
_spec = importlib.util.spec_from_file_location(
    "memoryhub_evalhub.preflight", _preflight_path
)
_mod = importlib.util.module_from_spec(_spec)
sys.modules[_mod.__name__] = _mod
_spec.loader.exec_module(_mod)

if __name__ == "__main__":
    _mod.main()

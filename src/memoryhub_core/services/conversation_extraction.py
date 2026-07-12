"""Backwards-compatibility shim -- canonical module is dreaming.py.

This file re-exports everything from memoryhub_core.services.dreaming so
that existing imports (tests, patches) continue to work.
"""

from memoryhub_core.services.dreaming import *  # noqa: F401,F403
from memoryhub_core.services.dreaming import (  # noqa: F401 -- explicit re-exports for patch targets
    _call_extraction_llm,
    _extract_window,
    _prompt_cache,
    extract_from_thread,
)

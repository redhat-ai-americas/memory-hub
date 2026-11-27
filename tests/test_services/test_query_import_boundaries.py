"""Queries must import in a fresh process without initializing services."""

import subprocess
import sys

import pytest


@pytest.mark.parametrize("module", ["mutations", "entities", "graph"])
def test_query_import_does_not_load_service_package(module):
    result = subprocess.run(
        [sys.executable, "-c", (
            "import importlib, sys; "
            f"importlib.import_module('memoryhub_core.queries.{module}'); "
            "assert 'memoryhub_core.services' not in sys.modules"
        )],
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stderr


def test_legacy_service_errors_keep_the_shared_domain_class_identity():
    from memoryhub_core.exceptions import CurationBlockedError, MemoryAccessDeniedError, MemoryNotFoundError
    from memoryhub_core.services import exceptions

    assert exceptions.CurationBlockedError is CurationBlockedError
    assert exceptions.MemoryAccessDeniedError is MemoryAccessDeniedError
    assert exceptions.MemoryNotFoundError is MemoryNotFoundError

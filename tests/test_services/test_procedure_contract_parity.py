"""The server and the personal edition share one extraction contract (#554).

``procedure_contract.py`` exists twice, byte for byte (core and
memoryhub-local, which cannot import each other), and the local edition
carries the system prompt as a Python constant. These checks fail the build
the moment either copy drifts.
"""

from __future__ import annotations

import ast
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CORE_CONTRACT = ROOT / "src/memoryhub_core/services/procedure_contract.py"
LOCAL_SERVICES = ROOT / "memoryhub-local/src/memoryhub_local/services"


def test_contract_copies_are_identical():
    core = CORE_CONTRACT.read_bytes()
    local = (LOCAL_SERVICES / "procedure_contract.py").read_bytes()
    assert core == local, (
        "procedure_contract.py drifted: copy src/memoryhub_core/services/procedure_contract.py "
        "to memoryhub-local/src/memoryhub_local/services/ unchanged"
    )


def test_contract_imports_nothing_from_either_package():
    tree = ast.parse(CORE_CONTRACT.read_text())
    modules = [
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    ] + [
        alias.name for node in ast.walk(tree) if isinstance(node, ast.Import)
        for alias in node.names
    ]
    assert not [m for m in modules if m.startswith(("memoryhub_core", "memoryhub_local", "src"))]


def _local_prompt() -> dict[str, str]:
    tree = ast.parse((LOCAL_SERVICES / "procedure_prompt.py").read_text())
    values: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    values[target.id] = node.value.value
    return values


def test_local_prompt_matches_the_yaml():
    data = yaml.safe_load((ROOT / "prompts/procedural_extraction.yaml").read_text())
    local = _local_prompt()
    assert local["SYSTEM_PROMPT"] == data["system_prompt"], (
        "regenerate memoryhub-local/.../procedure_prompt.py from prompts/procedural_extraction.yaml"
    )
    assert local["PROMPT_VERSION"] == str(data["version"])

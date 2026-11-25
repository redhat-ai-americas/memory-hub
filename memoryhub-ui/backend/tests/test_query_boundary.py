"""Keep schema/query construction behind the shared Core boundary."""

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
BFF = REPO / "memoryhub-ui" / "backend" / "src"


def test_http_adapters_do_not_construct_or_execute_database_queries():
    violations = []
    builders = {"select", "insert", "update", "delete", "text", "aliased", "create_async_engine"}
    for path in BFF.glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            function = node.func
            if isinstance(function, ast.Name) and function.id in builders:
                violations.append(f"{path.name}:{node.lineno}: {function.id}")
            if isinstance(function, ast.Attribute) and function.attr in {"execute", "scalars"}:
                if isinstance(function.value, ast.Name) and function.value.id in {"db", "session"}:
                    violations.append(f"{path.name}:{node.lineno}: direct query execution")
    assert not violations, "Move reusable queries into memoryhub_core.queries:\n" + "\n".join(violations)


def test_core_queries_and_policy_have_no_http_or_adapter_dependency():
    for folder in (REPO / "src/memoryhub_core/queries", REPO / "src/memoryhub_core/authorization"):
        for path in folder.glob("*.py"):
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node, ast.ImportFrom):
                    assert (node.module or "").split(".")[0] not in {"src", "fastapi", "starlette"}, path
                elif isinstance(node, ast.Import):
                    assert all(alias.name.split(".")[0] not in {"src", "fastapi", "starlette"}
                               for alias in node.names), path

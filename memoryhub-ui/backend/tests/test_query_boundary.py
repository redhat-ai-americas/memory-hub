"""Keep schema/query construction behind the shared Core boundary."""

import ast
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
BFF = REPO / "memoryhub-ui" / "backend" / "src"
CORE = REPO / "src" / "memoryhub_core"

_QUERY_BUILDERS = {
    "aliased",
    "create_async_engine",
    "create_engine",
    "delete",
    "insert",
    "select",
    "text",
    "update",
}
_SESSION_FACTORIES = {"async_sessionmaker", "sessionmaker"}
_EXECUTION_METHODS = {"execute", "scalars"}
_ORM_ROOT_NAMES = {
    "contradiction",
    "entity",
    "memory",
    "node",
    "record",
    "relationship",
    "report",
    "rule",
}
_ORM_RESULT_METHODS = {"first", "get", "one", "one_or_none", "scalar_one", "scalar_one_or_none"}


def _qualified_name(expression: ast.expr, bindings: dict[str, str]) -> str | None:
    if isinstance(expression, ast.Name):
        return bindings.get(expression.id, expression.id)
    if isinstance(expression, ast.Attribute):
        parent = _qualified_name(expression.value, bindings)
        return f"{parent}.{expression.attr}" if parent else None
    return None


def _root_name(expression: ast.expr) -> str | None:
    if isinstance(expression, ast.Name):
        return expression.id
    if isinstance(expression, ast.Attribute):
        return _root_name(expression.value)
    if isinstance(expression, ast.Subscript):
        return _root_name(expression.value)
    return None


def _collect_bindings(tree: ast.AST) -> dict[str, str]:
    """Resolve imports and simple ``alias = imported_name`` assignments."""
    bindings: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                bindings[alias.asname or alias.name.split(".")[0]] = alias.name
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                if alias.name != "*":
                    bindings[alias.asname or alias.name] = f"{module}.{alias.name}".strip(".")

    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            targets: list[ast.expr] = []
            value: ast.expr | None = None
            if isinstance(node, ast.Assign):
                targets = node.targets
                value = node.value
            elif isinstance(node, ast.NamedExpr):
                targets = [node.target]
                value = node.value
            if value is None:
                continue
            qualified = _qualified_name(value, bindings)
            if qualified is None:
                continue
            for target in targets:
                if isinstance(target, ast.Name) and target.id not in bindings:
                    bindings[target.id] = qualified
                    changed = True
    return bindings


def _bff_boundary_violations(tree: ast.AST) -> list[str]:
    """Find persistence construction, execution, or ORM mutation in adapters."""
    bindings = _collect_bindings(tree)
    violations: list[str] = []
    orm_names = set(_ORM_ROOT_NAMES)

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            values = [node.value]
            targets = node.targets
        elif isinstance(node, ast.NamedExpr):
            values = [node.value]
            targets = [node.target]
        else:
            values = []
            targets = []

        if values and isinstance(values[0], ast.Call):
            method = values[0].func
            if isinstance(method, ast.Attribute) and method.attr in _ORM_RESULT_METHODS:
                for target in targets:
                    if isinstance(target, ast.Name):
                        orm_names.add(target.id)
        if values and len(targets) == 1 and isinstance(targets[0], ast.Name):
            source_root = _root_name(values[0])
            if source_root in orm_names:
                orm_names.add(targets[0].id)

        if isinstance(node, ast.Call):
            qualified = _qualified_name(node.func, bindings)
            short_name = qualified.rsplit(".", 1)[-1] if qualified else None
            sqlalchemy_builder = qualified is not None and qualified.startswith("sqlalchemy.")
            unqualified_builder = (
                isinstance(node.func, ast.Name)
                and node.func.id in _QUERY_BUILDERS - {"delete", "update"}
            )
            if (short_name in _SESSION_FACTORIES) or sqlalchemy_builder or unqualified_builder:
                violations.append(f"database construction/query builder: {short_name}")
            if isinstance(node.func, ast.Attribute) and node.func.attr in _EXECUTION_METHODS:
                violations.append(f"direct query execution: {node.func.attr}")
            if isinstance(node.func, ast.Name) and node.func.id in {"setattr", "delattr"}:
                if node.args and _root_name(node.args[0]) in orm_names:
                    violations.append(f"dynamic ORM mutation: {node.func.id}")

        mutation_targets: list[ast.expr] = []
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            mutation_targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        elif isinstance(node, ast.Delete):
            mutation_targets = node.targets
        for target in mutation_targets:
            if _root_name(target) in orm_names and isinstance(target, (ast.Attribute, ast.Subscript)):
                violations.append(f"ORM mutation: {type(target).__name__}")

    return violations


def _import_names(tree: ast.AST) -> set[str]:
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            names.update(f"{module}.{alias.name}" for alias in node.names)
            if node.level and node.module:
                names.add("." * node.level + node.module)
    return names


def _forbidden_core_imports(tree: ast.AST) -> set[str]:
    forbidden = {"fastapi", "starlette", "src", "memoryhub_ui"}
    imports = _import_names(tree)
    return {name for name in imports if name.split(".")[0] in forbidden}


def test_http_adapters_do_not_construct_or_execute_database_queries():
    violations = []
    for path in BFF.rglob("*.py"):
        for violation in _bff_boundary_violations(ast.parse(path.read_text())):
            violations.append(f"{path.name}: {violation}")
    assert not violations, "Move reusable queries into memoryhub_core.queries:\n" + "\n".join(violations)


def test_core_modules_have_no_http_or_adapter_dependency():
    for path in CORE.rglob("*.py"):
        assert not _forbidden_core_imports(ast.parse(path.read_text())), path


def test_query_modules_do_not_depend_on_service_modules():
    for path in (CORE / "queries").rglob("*.py"):
        imports = _import_names(ast.parse(path.read_text()))
        assert not any(
            name.startswith("memoryhub_core.services") or name.startswith(".services")
            for name in imports
        ), path


@pytest.mark.parametrize(
    "source",
    [
        "arbitrary_session.execute(stmt)",
        "report.resolved = True",
        "setattr(report, 'resolved', True)",
        "report.metadata['status'] = 'resolved'",
        "session_factory = async_sessionmaker(engine)",
        "db = create_async_engine(url)",
        "from sqlalchemy.ext.asyncio import async_sessionmaker as factory\nsession_factory = factory(engine)",
    ],
)
def test_bff_boundary_guard_rejects_prohibited_examples(source):
    assert _bff_boundary_violations(ast.parse(source)), source


def test_bff_boundary_guard_allows_transaction_lifecycle_methods():
    source = """
async def commit_transaction(db, entity):
    await db.commit()
    await db.rollback()
    await db.refresh(entity)
"""
    assert not _bff_boundary_violations(ast.parse(source))


def test_core_service_sql_is_not_rejected_by_transport_guard():
    source = """
async def read_with_core_service(session, stmt):
    return await session.execute(stmt)
"""
    assert not _forbidden_core_imports(ast.parse(source))

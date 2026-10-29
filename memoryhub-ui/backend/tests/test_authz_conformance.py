"""The dashboard's read/write rules must equal the MCP server's.

Loads ``memory-hub-mcp/src/core/authz.py`` from the monorepo (or from
``MEMORYHUB_MCP_SRC``) with its request-context imports stubbed, then compares
``authorize_read`` / ``authorize_write`` with ``src.authz`` over every
combination of scope, ownership, membership, identity type and tenant. It also
checks that the SQL read clause selects exactly the rows the Python rule allows.

Skipped when the MCP source is not available (e.g. a standalone UI checkout).
"""

import importlib.util
import itertools
import os
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

from src import authz

HERE = Path(__file__).resolve()
CANDIDATES = [
    os.environ.get("MEMORYHUB_MCP_SRC", ""),
    str(HERE.parents[3] / "memory-hub-mcp"),  # memory-hub/memory-hub-mcp next to memory-hub/memoryhub-ui
    str(HERE.parents[2].parent / "upstream" / "memory-hub-mcp"),
]


def _load_mcp_authz():
    for base in CANDIDATES:
        path = Path(base) / "src" / "core" / "authz.py" if base else None
        if path and path.is_file():
            break
    else:
        pytest.skip("memory-hub-mcp source not found; set MEMORYHUB_MCP_SRC to run the conformance test")
    stubs = {
        "src.core": types.ModuleType("src.core"),
        "src.core.logging": types.ModuleType("src.core.logging"),
        "src.tools": types.ModuleType("src.tools"),
        "src.tools.auth": types.ModuleType("src.tools.auth"),
    }
    stubs["src.core.logging"].get_logger = lambda name: SimpleNamespace(debug=print, warning=print, info=print)
    stubs["src.tools.auth"].DEFAULT_TENANT_ID = "default"
    stubs["src.tools.auth"].get_current_user = lambda: None
    stubs["src.tools.auth"].refresh_session_metadata = lambda: None
    saved = {k: sys.modules.get(k) for k in stubs}
    sys.modules.update(stubs)
    try:
        spec = importlib.util.spec_from_file_location("mcp_authz_under_test", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v
    return module


MCP = None


@pytest.fixture(scope="module")
def mcp():
    return _load_mcp_authz()


SCOPES = authz.ALL_TIERS
IDS = ["alice", "agent-1", "proj-a", "camp-1", "sre", "other"]
SETS = [None, set(), {"proj-a", "camp-1", "sre"}]


def _memories():
    for scope, owner, scope_id, tenant in itertools.product(SCOPES, IDS, [None, *IDS], ["default", "t2"]):
        yield SimpleNamespace(scope=scope, owner_id=owner, scope_id=scope_id, tenant_id=tenant)


def _claims():
    for sub, itype, tenant, scopes in itertools.product(
        ["alice", "agent-1"],
        ["user", "service"],
        ["default", "t2"],
        [["memory:read", "memory:write"], ["memory:read:user", "memory:write:user"], []],
    ):
        yield {"sub": sub, "identity_type": itype, "tenant_id": tenant, "scopes": scopes}


def test_read_rules_match_mcp(mcp):
    checked = 0
    for claims in _claims():
        for memory in _memories():
            for sets in SETS:
                kw = {"campaign_ids": sets, "project_ids": sets, "role_names": sets}
                assert authz.authorize_read(claims, memory, **kw) == mcp.authorize_read(claims, memory, **kw), (
                    claims,
                    memory,
                    sets,
                )
                checked += 1
    assert checked > 10_000


def test_write_rules_match_mcp(mcp):
    for claims in _claims():
        for scope, owner, scope_id, tenant in itertools.product(SCOPES, IDS, [None, *IDS], ["default", "t2"]):
            for sets in SETS:
                kw = {"campaign_ids": sets, "project_ids": sets, "role_names": sets, "scope_id": scope_id}
                assert authz.authorize_write(claims, scope, owner, tenant, **kw) == mcp.authorize_write(
                    claims, scope, owner, tenant, **kw
                ), (claims, scope, owner, scope_id, tenant, sets)


@pytest.mark.parametrize("flag", ["MEMORYHUB_PROJECT_ISOLATION_ENABLED", "MEMORYHUB_ROLE_ISOLATION_ENABLED"])
def test_isolation_flags_follow_the_same_variables(flag, monkeypatch):
    m = SimpleNamespace(
        scope="project" if "PROJECT" in flag else "role", owner_id="x", scope_id="nope", tenant_id="default"
    )
    claims = authz.claims_for("alice", "default")
    assert authz.authorize_read(claims, m, project_ids=set(), role_names=set()) is False
    monkeypatch.setenv(flag, "false")
    assert authz.authorize_read(claims, m, project_ids=set(), role_names=set()) is True


def test_person_is_the_union_of_identities():
    grants = SimpleNamespace(identities={"alice", "agent-1"}, projects={"proj-a"}, roles=set(), campaigns={"camp-1"})
    mine = SimpleNamespace(scope="user", owner_id="agent-1", scope_id=None, tenant_id="default")
    theirs = SimpleNamespace(scope="user", owner_id="bob", scope_id=None, tenant_id="default")
    # MCP decides project access by scope_id only; owner_id does not grant access.
    loose = SimpleNamespace(scope="project", owner_id="proj-a", scope_id="proj-b", tenant_id="default")
    assert authz.person_can_read(grants, "default", mine)
    assert not authz.person_can_read(grants, "default", theirs)
    assert not authz.person_can_read(grants, "default", loose)
    assert not authz.person_can_write(grants, "default", "role", "sre", "sre")  # people never write role memories


def test_sql_clause_selects_what_the_python_rule_allows():
    """Evaluate the SQL clause on SQLite rows and compare with person_can_read."""
    from sqlalchemy import Column, MetaData, String, Table, create_engine, select

    md = MetaData()
    t = Table(
        "m",
        md,
        Column("id", String, primary_key=True),
        *(Column(c, String) for c in ("scope", "owner_id", "scope_id", "tenant_id")),
    )
    engine = create_engine("sqlite://")
    md.create_all(engine)
    rows = [
        dict(id=str(i), scope=m.scope, owner_id=m.owner_id, scope_id=m.scope_id, tenant_id=m.tenant_id)
        for i, m in enumerate(_memories())
    ]
    grants = SimpleNamespace(identities={"alice", "agent-1"}, projects={"proj-a"}, roles={"sre"}, campaigns={"camp-1"})
    with engine.begin() as conn:
        conn.execute(t.insert(), rows)
        got = {r[0] for r in conn.execute(select(t.c.id).where(authz.read_clause(grants, "default", t.c)))}
    expected = {r["id"] for r in rows if authz.person_can_read(grants, "default", SimpleNamespace(**r))}
    assert got == expected

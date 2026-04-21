"""Unit tests for collect_graph_neighbors in the graph service.

collect_graph_neighbors uses a PostgreSQL recursive CTE with uuid[] casts and
unnest(), which cannot run against the SQLite test database (see conftest.py
FREEZE NOTICE). These tests mock session.execute so they exercise all of the
Python-layer logic — early-returns, param construction, depth capping, seed
exclusion, and result mapping — without requiring a live PostgreSQL instance.

Integration against real PostgreSQL lives in tests/integration/.
"""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from memoryhub_core.services.graph import _MAX_NEIGHBORS_CAP, collect_graph_neighbors

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TENANT = "tenant-a"


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


def _row(node_id: uuid.UUID, min_depth: int) -> SimpleNamespace:
    """Simulate a SQLAlchemy Row with node_id and min_depth attributes."""
    return SimpleNamespace(node_id=str(node_id), min_depth=min_depth)


def _make_session(rows: list) -> AsyncMock:
    """Return an AsyncMock session whose execute() returns the given rows."""
    result = MagicMock()
    result.all.return_value = rows
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)
    return session


# ---------------------------------------------------------------------------
# Early-return cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_seed_ids_returns_empty_dict():
    """Empty seed list must short-circuit before touching the database."""
    session = _make_session([])
    result = await collect_graph_neighbors([], session, tenant_id=_TENANT)

    assert result == {}
    session.execute.assert_not_called()


@pytest.mark.asyncio
async def test_no_relationships_returns_empty_dict():
    """DB returns no rows → empty dict, no exception."""
    session = _make_session([])
    seed = _uuid()

    result = await collect_graph_neighbors([seed], session, tenant_id=_TENANT)

    assert result == {}
    session.execute.assert_called_once()


# ---------------------------------------------------------------------------
# Single-hop traversal
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_single_hop_neighbors():
    """Seed A has two neighbors B and C at depth 1."""
    seed = _uuid()
    b, c = _uuid(), _uuid()
    session = _make_session([_row(b, 1), _row(c, 1)])

    result = await collect_graph_neighbors([seed], session, tenant_id=_TENANT)

    assert result == {b: 1, c: 1}


# ---------------------------------------------------------------------------
# Multi-hop traversal
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_multi_hop_distances():
    """A→B→C: B at distance 1, C at distance 2."""
    seed = _uuid()
    b, c = _uuid(), _uuid()
    session = _make_session([_row(b, 1), _row(c, 2)])

    result = await collect_graph_neighbors([seed], session, tenant_id=_TENANT, max_depth=2)

    assert result[b] == 1
    assert result[c] == 2


# ---------------------------------------------------------------------------
# Depth capping
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "requested, expected_capped",
    [
        (1, 1),
        (_MAX_NEIGHBORS_CAP, _MAX_NEIGHBORS_CAP),
        (_MAX_NEIGHBORS_CAP + 1, _MAX_NEIGHBORS_CAP),
        (100, _MAX_NEIGHBORS_CAP),
    ],
)
@pytest.mark.asyncio
async def test_depth_is_capped(requested: int, expected_capped: int):
    """max_depth is silently clamped to _MAX_NEIGHBORS_CAP."""
    session = _make_session([])
    seed = _uuid()

    await collect_graph_neighbors([seed], session, tenant_id=_TENANT, max_depth=requested)

    _, call_kwargs = session.execute.call_args
    params = call_kwargs.get("parameters") or session.execute.call_args[0][1]
    assert params["max_depth"] == expected_capped


# ---------------------------------------------------------------------------
# Seeds excluded from results
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_seed_ids_excluded_from_result():
    """The CTE base case includes seeds at depth 0; the Python layer must
    drop any row whose node_id matches a seed even if the DB returned it."""
    seed = _uuid()
    neighbor = _uuid()
    # Simulate a DB bug / edge case that returns the seed itself at depth 0.
    session = _make_session([_row(seed, 0), _row(neighbor, 1)])

    result = await collect_graph_neighbors([seed], session, tenant_id=_TENANT)

    assert seed not in result
    assert result == {neighbor: 1}


# ---------------------------------------------------------------------------
# Relationship type filtering — param construction
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_type_filter_omits_rel_types_param():
    """When relationship_types is None, :rel_types must not be in params."""
    session = _make_session([])
    seed = _uuid()

    await collect_graph_neighbors([seed], session, tenant_id=_TENANT)

    _, call_kwargs = session.execute.call_args
    params = call_kwargs.get("parameters") or session.execute.call_args[0][1]
    assert "rel_types" not in params


@pytest.mark.asyncio
async def test_type_filter_adds_rel_types_param():
    """When relationship_types is given, :rel_types must appear in params."""
    session = _make_session([])
    seed = _uuid()

    await collect_graph_neighbors(
        [seed],
        session,
        tenant_id=_TENANT,
        relationship_types=["related_to", "derived_from"],
    )

    _, call_kwargs = session.execute.call_args
    params = call_kwargs.get("parameters") or session.execute.call_args[0][1]
    assert params["rel_types"] == ["related_to", "derived_from"]


@pytest.mark.asyncio
async def test_type_filter_sql_clause_present():
    """SQL text must contain the ANY(:rel_types) clause when types are given."""
    session = _make_session([])
    seed = _uuid()

    await collect_graph_neighbors(
        [seed],
        session,
        tenant_id=_TENANT,
        relationship_types=["related_to"],
    )

    sql_obj = session.execute.call_args[0][0]
    assert "ANY(:rel_types)" in str(sql_obj)


@pytest.mark.asyncio
async def test_no_type_filter_sql_clause_absent():
    """Without type filtering the ANY clause must not appear in the SQL."""
    session = _make_session([])
    seed = _uuid()

    await collect_graph_neighbors([seed], session, tenant_id=_TENANT)

    sql_obj = session.execute.call_args[0][0]
    assert "ANY(:rel_types)" not in str(sql_obj)


# ---------------------------------------------------------------------------
# Tenant isolation — param construction
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tenant_id_passed_in_params():
    """tenant_id must appear in the SQL params so the CTE filters correctly."""
    session = _make_session([])
    seed = _uuid()
    specific_tenant = "org-acme"

    await collect_graph_neighbors([seed], session, tenant_id=specific_tenant)

    _, call_kwargs = session.execute.call_args
    params = call_kwargs.get("parameters") or session.execute.call_args[0][1]
    assert params["tenant_id"] == specific_tenant


@pytest.mark.asyncio
async def test_tenant_isolation_different_tenants_get_different_params():
    """Two calls with different tenants pass their respective tenant_ids."""
    seed = _uuid()

    session_a = _make_session([])
    await collect_graph_neighbors([seed], session_a, tenant_id="tenant-a")
    _, kw_a = session_a.execute.call_args
    params_a = kw_a.get("parameters") or session_a.execute.call_args[0][1]

    session_b = _make_session([])
    await collect_graph_neighbors([seed], session_b, tenant_id="tenant-b")
    _, kw_b = session_b.execute.call_args
    params_b = kw_b.get("parameters") or session_b.execute.call_args[0][1]

    assert params_a["tenant_id"] == "tenant-a"
    assert params_b["tenant_id"] == "tenant-b"


# ---------------------------------------------------------------------------
# Temporal filtering — param construction
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_as_of_uses_is_null_clause():
    """Without as_of, the SQL should filter valid_until IS NULL."""
    session = _make_session([])
    seed = _uuid()

    await collect_graph_neighbors([seed], session, tenant_id=_TENANT)

    sql_obj = session.execute.call_args[0][0]
    assert "valid_until IS NULL" in str(sql_obj)
    _, call_kwargs = session.execute.call_args
    params = call_kwargs.get("parameters") or session.execute.call_args[0][1]
    assert "as_of" not in params


@pytest.mark.asyncio
async def test_as_of_uses_range_clause():
    """With as_of set, the SQL should use the validity window check."""
    session = _make_session([])
    seed = _uuid()
    ts = datetime(2025, 1, 1, tzinfo=UTC)

    await collect_graph_neighbors([seed], session, tenant_id=_TENANT, as_of=ts)

    sql_obj = session.execute.call_args[0][0]
    assert "valid_from <= :as_of" in str(sql_obj)
    _, call_kwargs = session.execute.call_args
    params = call_kwargs.get("parameters") or session.execute.call_args[0][1]
    assert params["as_of"] == ts


# ---------------------------------------------------------------------------
# Seed IDs are passed as strings (uuid[] bind expects strings)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_seed_ids_serialized_as_strings():
    """UUID objects in seed_ids must be converted to strings for the bind param."""
    session = _make_session([])
    seed = _uuid()

    await collect_graph_neighbors([seed], session, tenant_id=_TENANT)

    _, call_kwargs = session.execute.call_args
    params = call_kwargs.get("parameters") or session.execute.call_args[0][1]
    assert params["seed_ids"] == [str(seed)]


# ---------------------------------------------------------------------------
# Multiple seeds
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_multiple_seeds_all_excluded_from_results():
    """All seed IDs must be stripped from the result even if DB returns them."""
    seed_a, seed_b = _uuid(), _uuid()
    neighbor = _uuid()
    session = _make_session([_row(seed_a, 0), _row(seed_b, 0), _row(neighbor, 1)])

    result = await collect_graph_neighbors([seed_a, seed_b], session, tenant_id=_TENANT)

    assert seed_a not in result
    assert seed_b not in result
    assert result == {neighbor: 1}


@pytest.mark.asyncio
async def test_multiple_seeds_passed_correctly():
    """All seed UUIDs must appear in the seed_ids param."""
    seed_a, seed_b = _uuid(), _uuid()
    session = _make_session([])

    await collect_graph_neighbors([seed_a, seed_b], session, tenant_id=_TENANT)

    _, call_kwargs = session.execute.call_args
    params = call_kwargs.get("parameters") or session.execute.call_args[0][1]
    assert set(params["seed_ids"]) == {str(seed_a), str(seed_b)}


# ---------------------------------------------------------------------------
# Result mapping — UUID conversion
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_result_keys_are_uuid_objects():
    """node_id strings from DB rows must be converted back to uuid.UUID."""
    seed = _uuid()
    neighbor = _uuid()
    session = _make_session([_row(neighbor, 1)])

    result = await collect_graph_neighbors([seed], session, tenant_id=_TENANT)

    assert all(isinstance(k, uuid.UUID) for k in result)


# ---------------------------------------------------------------------------
# SQL structure sanity checks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sql_contains_recursive_cte():
    """The generated SQL must use a recursive CTE."""
    session = _make_session([])
    seed = _uuid()

    await collect_graph_neighbors([seed], session, tenant_id=_TENANT)

    sql_obj = session.execute.call_args[0][0]
    sql_text = str(sql_obj).upper()
    assert "WITH RECURSIVE" in sql_text


@pytest.mark.asyncio
async def test_sql_contains_min_depth_aggregation():
    """The result SELECT must use MIN(depth) to report shortest path."""
    session = _make_session([])
    seed = _uuid()

    await collect_graph_neighbors([seed], session, tenant_id=_TENANT)

    sql_obj = session.execute.call_args[0][0]
    assert "MIN(depth)" in str(sql_obj)

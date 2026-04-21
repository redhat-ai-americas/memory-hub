"""Tests for the consolidated manage_graph tool.

Migrated from test_create_relationship.py, test_get_relationships.py, and
test_get_similar_memories.py — all three actions now dispatch through
manage_graph(action=...).
"""

import inspect
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp.exceptions import ToolError

import src.tools.auth as auth_mod
from src.tools.manage_graph import manage_graph


# ── tool-level structural tests ──────────────────────────────────────────────

def test_manage_graph_is_callable():
    """Verify manage_graph is a decorated MCP tool."""
    assert callable(manage_graph)


def test_manage_graph_is_async():
    """The tool function must be async."""
    assert inspect.iscoroutinefunction(manage_graph)


def test_manage_graph_has_action_param():
    """manage_graph must accept an action parameter."""
    sig = inspect.signature(manage_graph)
    assert "action" in sig.parameters


def test_manage_graph_has_create_relationship_params():
    """Verify parameters for the create_relationship action are present."""
    sig = inspect.signature(manage_graph)
    param_names = set(sig.parameters.keys())
    required = {"source_id", "target_id", "relationship_type"}
    assert required.issubset(param_names), (
        f"Missing create_relationship params: {required - param_names}"
    )
    assert "metadata" in param_names


def test_manage_graph_has_get_relationships_params():
    """Verify parameters for the get_relationships action are present."""
    sig = inspect.signature(manage_graph)
    param_names = set(sig.parameters.keys())
    required = {"node_id"}
    assert required.issubset(param_names), (
        f"Missing get_relationships params: {required - param_names}"
    )
    optional = {"relationship_type", "direction", "include_provenance"}
    assert optional.issubset(param_names), (
        f"Missing optional get_relationships params: {optional - param_names}"
    )


def test_manage_graph_has_get_similar_params():
    """Verify parameters for the get_similar action are present."""
    sig = inspect.signature(manage_graph)
    param_names = set(sig.parameters.keys())
    required = {"memory_id"}
    assert required.issubset(param_names), (
        f"Missing get_similar params: {required - param_names}"
    )
    optional = {"threshold", "max_results", "offset"}
    assert optional.issubset(param_names), (
        f"Missing optional get_similar params: {optional - param_names}"
    )


def test_manage_graph_default_values():
    """Verify default values for optional parameters."""
    sig = inspect.signature(manage_graph)
    params = sig.parameters

    assert params["metadata"].default is None
    assert params["direction"].default == "both"
    assert params["include_provenance"].default is False
    assert params["threshold"].default == 0.80
    assert params["max_results"].default == 10
    assert params["offset"].default == 0


# ── invalid action ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_manage_graph_invalid_action():
    """An unrecognized action raises ToolError listing valid options."""
    auth_mod._current_session = {
        "user_id": "wjackson",
        "scopes": ["user"],
        "identity_type": "user",
    }
    try:
        with pytest.raises(ToolError, match="Invalid action"):
            await manage_graph(action="do_something_weird")
    finally:
        auth_mod._current_session = None


# ── authentication ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_manage_graph_requires_auth_create_relationship():
    """Unauthenticated create_relationship raises ToolError."""
    auth_mod._current_session = None
    with pytest.raises(ToolError, match="Authentication required"):
        await manage_graph(
            action="create_relationship",
            source_id=str(uuid.uuid4()),
            target_id=str(uuid.uuid4()),
            relationship_type="related_to",
        )


@pytest.mark.asyncio
async def test_manage_graph_requires_auth_get_relationships():
    """Unauthenticated get_relationships raises ToolError."""
    auth_mod._current_session = None
    with pytest.raises(ToolError):
        await manage_graph(action="get_relationships", node_id=str(uuid.uuid4()))


@pytest.mark.asyncio
async def test_manage_graph_requires_auth_get_similar():
    """Unauthenticated get_similar raises ToolError."""
    auth_mod._current_session = None
    with pytest.raises(ToolError):
        await manage_graph(action="get_similar", memory_id=str(uuid.uuid4()))


# ── create_relationship tests ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_relationship_invalid_type():
    """Invalid relationship_type raises ToolError listing valid options."""
    with pytest.raises(ToolError, match="derived_from"):
        await manage_graph(
            action="create_relationship",
            source_id=str(uuid.uuid4()),
            target_id=str(uuid.uuid4()),
            relationship_type="bad_type",
        )


@pytest.mark.asyncio
async def test_create_relationship_invalid_uuid():
    """Bad UUID format raises ToolError with clear message."""
    with pytest.raises(ToolError, match="Invalid source_id format"):
        await manage_graph(
            action="create_relationship",
            source_id="not-a-uuid",
            target_id=str(uuid.uuid4()),
            relationship_type="related_to",
        )


@pytest.mark.asyncio
async def test_create_relationship_self_reference():
    """Same source and target raises ToolError."""
    same_id = str(uuid.uuid4())
    with pytest.raises(ToolError, match="self-referential"):
        await manage_graph(
            action="create_relationship",
            source_id=same_id,
            target_id=same_id,
            relationship_type="related_to",
        )


@pytest.mark.asyncio
async def test_create_relationship_success():
    """Successful creation returns the relationship data."""
    mock_result = MagicMock()
    mock_result.model_dump.return_value = {
        "id": str(uuid.uuid4()),
        "source_id": str(uuid.uuid4()),
        "target_id": str(uuid.uuid4()),
        "relationship_type": "related_to",
    }

    mock_session = AsyncMock()
    mock_gen = AsyncMock()
    mock_memory = SimpleNamespace(scope="user", owner_id="test-user", tenant_id="default")

    with (
        patch("src.tools.manage_graph.get_db_session", return_value=(mock_session, mock_gen)),
        patch("src.tools.manage_graph.release_db_session", new_callable=AsyncMock),
        patch("src.tools.manage_graph.read_memory_service", new_callable=AsyncMock, return_value=mock_memory),
        patch("src.tools.manage_graph.create_relationship_service", new_callable=AsyncMock, return_value=mock_result),
    ):
        result = await manage_graph(
            action="create_relationship",
            source_id=str(uuid.uuid4()),
            target_id=str(uuid.uuid4()),
            relationship_type="related_to",
        )
    assert "error" not in result
    assert result["relationship_type"] == "related_to"


# ── get_relationships tests ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_relationships_invalid_uuid():
    """Bad UUID format raises ToolError with a clear message."""
    with pytest.raises(ToolError, match="Invalid node_id format"):
        await manage_graph(action="get_relationships", node_id="not-a-uuid")


@pytest.mark.asyncio
async def test_get_relationships_invalid_direction():
    """Invalid direction raises ToolError listing valid options."""
    with pytest.raises(ToolError, match="outgoing"):
        await manage_graph(
            action="get_relationships",
            node_id=str(uuid.uuid4()),
            direction="sideways",
        )


@pytest.mark.asyncio
async def test_get_relationships_invalid_type():
    """Invalid relationship_type raises ToolError listing valid types."""
    with pytest.raises(ToolError, match="derived_from"):
        await manage_graph(
            action="get_relationships",
            node_id=str(uuid.uuid4()),
            relationship_type="bad_type",
        )


@pytest.mark.asyncio
async def test_get_relationships_success():
    """Successful query returns relationships and count."""
    mock_rel = MagicMock()
    mock_rel.model_dump.return_value = {
        "id": str(uuid.uuid4()),
        "relationship_type": "related_to",
    }

    mock_session = AsyncMock()
    mock_gen = AsyncMock()

    with (
        patch("src.tools.manage_graph.get_db_session", return_value=(mock_session, mock_gen)),
        patch("src.tools.manage_graph.release_db_session", new_callable=AsyncMock),
        patch("src.tools.manage_graph.get_relationships_service", new_callable=AsyncMock, return_value=[mock_rel]),
        patch("src.tools.manage_graph.get_projects_for_user", new_callable=AsyncMock, return_value=set()),
        patch("src.tools.manage_graph.get_roles_for_user", new_callable=AsyncMock, return_value=set()),
    ):
        result = await manage_graph(action="get_relationships", node_id=str(uuid.uuid4()))
    assert result["count"] == 1
    assert len(result["relationships"]) == 1


@pytest.mark.asyncio
async def test_get_relationships_forwards_tenant_id_to_service():
    """Phase 4 (#46): the tool must forward claims.tenant_id into the
    get_relationships_service call so the SQL-level filter runs in the
    caller's tenant."""
    mock_session = AsyncMock()
    mock_gen = AsyncMock()
    fake_claims = {
        "sub": "wjackson",
        "identity_type": "user",
        "tenant_id": "tenant_a",
        "scopes": ["memory:read:user", "memory:write:user"],
    }

    with (
        patch(
            "src.tools.manage_graph.get_claims_from_context",
            return_value=fake_claims,
        ),
        patch(
            "src.tools.manage_graph.get_db_session",
            return_value=(mock_session, mock_gen),
        ),
        patch(
            "src.tools.manage_graph.release_db_session",
            new_callable=AsyncMock,
        ),
        patch(
            "src.tools.manage_graph.get_relationships_service",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_service,
        patch(
            "src.tools.manage_graph.get_projects_for_user",
            new_callable=AsyncMock,
            return_value=set(),
        ),
        patch(
            "src.tools.manage_graph.get_roles_for_user",
            new_callable=AsyncMock,
            return_value=set(),
        ),
    ):
        await manage_graph(action="get_relationships", node_id=str(uuid.uuid4()))

    _, kwargs = mock_service.call_args
    assert kwargs.get("tenant_id") == "tenant_a", (
        f"Expected tenant_id='tenant_a' forwarded into get_relationships_service, "
        f"got kwargs={kwargs}"
    )


# ── get_similar tests ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_similar_invalid_uuid():
    """Bad UUID format raises ToolError with a clear message."""
    with pytest.raises(ToolError, match="Invalid memory_id format"):
        await manage_graph(action="get_similar", memory_id="not-a-uuid")


@pytest.mark.asyncio
async def test_get_similar_success():
    """Successful query returns paged results."""
    mock_session = AsyncMock()
    mock_gen = AsyncMock()
    fake_source = SimpleNamespace(
        scope="user", owner_id="wjackson", tenant_id="default"
    )

    with (
        patch(
            "src.tools.manage_graph.get_db_session",
            return_value=(mock_session, mock_gen),
        ),
        patch(
            "src.tools.manage_graph.release_db_session", new_callable=AsyncMock
        ),
        patch(
            "src.tools.manage_graph.read_memory_service",
            new_callable=AsyncMock,
            return_value=fake_source,
        ),
        patch(
            "src.tools.manage_graph.get_similar_memories_service",
            new_callable=AsyncMock,
            return_value={"results": [], "total": 0, "has_more": False},
        ),
    ):
        auth_mod._current_session = {
            "user_id": "wjackson",
            "scopes": ["user"],
            "identity_type": "user",
        }
        try:
            result = await manage_graph(action="get_similar", memory_id=str(uuid.uuid4()))
        finally:
            auth_mod._current_session = None
    assert result["total"] == 0
    assert result["has_more"] is False


@pytest.mark.asyncio
async def test_get_similar_returns_results_for_owner():
    """Regression for #47: results from the service must reach the caller.

    The previous post-fetch RBAC filter dropped every result because the
    service-layer items only contain {id, stub, score} — not scope/owner_id —
    so the SimpleNamespace defaults rejected everything via authorize_read.
    Verify that when the caller owns the source, all returned items pass
    through unchanged.
    """
    mock_session = AsyncMock()
    mock_gen = AsyncMock()
    fake_source = SimpleNamespace(
        scope="user", owner_id="wjackson", tenant_id="default"
    )
    sim_id = uuid.uuid4()
    service_results = {
        "results": [
            {"id": sim_id, "stub": "similar 1", "score": 0.92},
            {"id": uuid.uuid4(), "stub": "similar 2", "score": 0.85},
        ],
        "total": 2,
        "has_more": False,
    }

    with (
        patch(
            "src.tools.manage_graph.get_db_session",
            return_value=(mock_session, mock_gen),
        ),
        patch(
            "src.tools.manage_graph.release_db_session", new_callable=AsyncMock
        ),
        patch(
            "src.tools.manage_graph.read_memory_service",
            new_callable=AsyncMock,
            return_value=fake_source,
        ),
        patch(
            "src.tools.manage_graph.get_similar_memories_service",
            new_callable=AsyncMock,
            return_value=service_results,
        ),
    ):
        auth_mod._current_session = {
            "user_id": "wjackson",
            "scopes": ["user"],
            "identity_type": "user",
        }
        try:
            result = await manage_graph(action="get_similar", memory_id=str(uuid.uuid4()))
        finally:
            auth_mod._current_session = None

    assert result.get("error") is not True
    assert "results" in result
    assert len(result["results"]) == 2
    assert result["total"] == 2
    # IDs must be JSON-serializable strings, not UUID objects
    assert all(isinstance(item["id"], str) for item in result["results"])


@pytest.mark.asyncio
async def test_get_similar_unauthorized_for_other_owner():
    """Regression for #47: callers cannot read memories outside their scope.

    Even though the post-fetch filter is gone, caller-vs-source authorization
    must still reject reads of memories owned by other users at user scope.
    """
    mock_session = AsyncMock()
    mock_gen = AsyncMock()
    other_owner_source = SimpleNamespace(
        scope="user", owner_id="someone-else", tenant_id="default"
    )

    auth_mod._current_session = {
        "user_id": "wjackson",
        "scopes": ["user"],
        "identity_type": "user",
    }
    try:
        with (
            patch(
                "src.tools.manage_graph.get_db_session",
                return_value=(mock_session, mock_gen),
            ),
            patch(
                "src.tools.manage_graph.release_db_session",
                new_callable=AsyncMock,
            ),
            patch(
                "src.tools.manage_graph.read_memory_service",
                new_callable=AsyncMock,
                return_value=other_owner_source,
            ),
            pytest.raises(ToolError, match="Not authorized"),
        ):
            await manage_graph(action="get_similar", memory_id=str(uuid.uuid4()))
    finally:
        auth_mod._current_session = None


@pytest.mark.asyncio
async def test_get_similar_forwards_tenant_id_to_service():
    """Phase 4 (#46): the tool must forward claims.tenant_id into both
    read_memory_service (auth check) and get_similar_memories_service so the
    SQL-level tenant filter runs in the correct tenant."""
    mock_session = AsyncMock()
    mock_gen = AsyncMock()
    fake_source = SimpleNamespace(
        scope="user", owner_id="wjackson", tenant_id="tenant_a"
    )
    fake_claims = {
        "sub": "wjackson",
        "identity_type": "user",
        "tenant_id": "tenant_a",
        "scopes": ["memory:read:user", "memory:write:user"],
    }

    with (
        patch(
            "src.tools.manage_graph.get_claims_from_context",
            return_value=fake_claims,
        ),
        patch(
            "src.tools.manage_graph.get_db_session",
            return_value=(mock_session, mock_gen),
        ),
        patch(
            "src.tools.manage_graph.release_db_session",
            new_callable=AsyncMock,
        ),
        patch(
            "src.tools.manage_graph.read_memory_service",
            new_callable=AsyncMock,
            return_value=fake_source,
        ) as mock_read,
        patch(
            "src.tools.manage_graph.get_similar_memories_service",
            new_callable=AsyncMock,
            return_value={"results": [], "total": 0, "has_more": False},
        ) as mock_similar,
    ):
        await manage_graph(action="get_similar", memory_id=str(uuid.uuid4()))

    _, read_kwargs = mock_read.call_args
    assert read_kwargs.get("tenant_id") == "tenant_a", (
        "Expected tenant_id='tenant_a' in read_memory_service kwargs, "
        f"got {read_kwargs}"
    )
    _, similar_kwargs = mock_similar.call_args
    assert similar_kwargs.get("tenant_id") == "tenant_a", (
        f"Expected tenant_id='tenant_a' in get_similar_memories_service kwargs, "
        f"got {similar_kwargs}"
    )

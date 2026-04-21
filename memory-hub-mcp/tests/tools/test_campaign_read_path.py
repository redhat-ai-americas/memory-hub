"""Tests for #162: campaign_ids wired into read-path tools.

Each tool that calls authorize_read or authorize_write must resolve
campaign_ids when the target memory has campaign scope. Without
project_id, campaign-scoped memories should return a helpful ToolError
(not a generic "Not authorized"). With project_id, campaign membership
is resolved and passed to the authz check.
"""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastmcp.exceptions import ToolError

# --- Shared fixtures ---

CAMPAIGN_UUID = str(uuid.uuid4())
MEMORY_UUID = str(uuid.uuid4())


def _campaign_claims():
    """Claims with campaign read/write access."""
    return {
        "sub": "wjackson",
        "identity_type": "user",
        "tenant_id": "default",
        "scopes": [
            "memory:read:user",
            "memory:write:user",
            "memory:read:campaign",
            "memory:write:campaign",
        ],
    }


def _fake_campaign_node(**overrides):
    """Build a campaign-scoped MemoryNodeRead."""
    import datetime as _dt
    from memoryhub_core.models.schemas import MemoryNodeRead, MemoryScope, StorageType

    defaults = dict(
        id=uuid.UUID(MEMORY_UUID),
        parent_id=None,
        content="campaign memory content",
        stub="campaign memory stub",
        storage_type=StorageType.INLINE,
        content_ref=None,
        weight=0.7,
        scope=MemoryScope.CAMPAIGN,
        branch_type=None,
        owner_id=CAMPAIGN_UUID,
        tenant_id="default",
        is_current=True,
        version=1,
        previous_version_id=None,
        metadata=None,
        created_at=_dt.datetime.now(_dt.UTC),
        updated_at=_dt.datetime.now(_dt.UTC),
        expires_at=None,
        has_children=False,
        has_rationale=False,
        branch_count=0,
    )
    defaults.update(overrides)
    return MemoryNodeRead(**defaults)


# --- read_memory ---


@pytest.mark.asyncio
async def test_read_memory_campaign_requires_project_id():
    """Campaign-scoped memory without project_id raises a helpful ToolError."""
    from src.tools.read_memory import read_memory

    fake_node = _fake_campaign_node()
    mock_session = AsyncMock()
    mock_gen = AsyncMock()

    with (
        patch(
            "src.tools.read_memory.get_claims_from_context",
            return_value=_campaign_claims(),
        ),
        patch(
            "src.tools.read_memory.get_db_session",
            return_value=(mock_session, mock_gen),
        ),
        patch("src.tools.read_memory.release_db_session", new_callable=AsyncMock),
        patch(
            "src.tools.read_memory._read_memory",
            new_callable=AsyncMock,
            return_value=fake_node,
        ),
        pytest.raises(ToolError, match="project_id is required"),
    ):
        await read_memory(memory_id=MEMORY_UUID)


@pytest.mark.asyncio
async def test_read_memory_campaign_with_project_id():
    """Campaign-scoped memory succeeds when project_id resolves enrollment."""
    from src.tools.read_memory import read_memory

    fake_node = _fake_campaign_node()
    mock_session = AsyncMock()
    mock_gen = AsyncMock()

    with (
        patch(
            "src.tools.read_memory.get_claims_from_context",
            return_value=_campaign_claims(),
        ),
        patch(
            "src.tools.read_memory.get_db_session",
            return_value=(mock_session, mock_gen),
        ),
        patch("src.tools.read_memory.release_db_session", new_callable=AsyncMock),
        patch(
            "src.tools.read_memory._read_memory",
            new_callable=AsyncMock,
            return_value=fake_node,
        ),
        patch(
            "src.tools.read_memory.get_campaigns_for_project",
            new_callable=AsyncMock,
            return_value={CAMPAIGN_UUID},
        ),
    ):
        result = await read_memory(memory_id=MEMORY_UUID, project_id="my-project")

    assert result["scope"] == "campaign"
    assert result["owner_id"] == CAMPAIGN_UUID


# --- get_memory_history (consolidated into read_memory via #173) ---
# Tests for get_memory_history as a standalone tool were removed when
# the tool was consolidated into read_memory (include_versions=True).
# Campaign-scope coverage for read_memory is above (test_read_memory_*).


# --- get_similar_memories ---


@pytest.mark.asyncio
async def test_get_similar_memories_campaign_requires_project_id():
    from src.tools.manage_graph import manage_graph

    fake_source = SimpleNamespace(
        scope="campaign", owner_id=CAMPAIGN_UUID, tenant_id="default"
    )
    mock_session = AsyncMock()
    mock_gen = AsyncMock()

    with (
        patch(
            "src.tools.manage_graph.get_claims_from_context",
            return_value=_campaign_claims(),
        ),
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
        pytest.raises(ToolError, match="project_id is required"),
    ):
        await manage_graph(action="get_similar", memory_id=MEMORY_UUID)


@pytest.mark.asyncio
async def test_get_similar_memories_campaign_with_project_id():
    from src.tools.manage_graph import manage_graph

    fake_source = SimpleNamespace(
        scope="campaign", owner_id=CAMPAIGN_UUID, tenant_id="default"
    )
    mock_session = AsyncMock()
    mock_gen = AsyncMock()

    with (
        patch(
            "src.tools.manage_graph.get_claims_from_context",
            return_value=_campaign_claims(),
        ),
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
            "src.tools.manage_graph.get_campaigns_for_project",
            new_callable=AsyncMock,
            return_value={CAMPAIGN_UUID},
        ),
        patch(
            "src.tools.manage_graph.get_similar_memories_service",
            new_callable=AsyncMock,
            return_value={"results": [], "total": 0, "has_more": False},
        ),
    ):
        result = await manage_graph(
            action="get_similar", memory_id=MEMORY_UUID, project_id="my-project"
        )

    assert result["total"] == 0


# --- report_contradiction ---


@pytest.mark.asyncio
async def test_report_contradiction_campaign_requires_project_id():
    from src.tools.manage_curation import manage_curation

    fake_node = _fake_campaign_node()
    mock_session = AsyncMock()
    mock_gen = AsyncMock()

    with (
        patch(
            "src.tools.manage_curation.get_claims_from_context",
            return_value=_campaign_claims(),
        ),
        patch(
            "src.tools.manage_curation.get_db_session",
            return_value=(mock_session, mock_gen),
        ),
        patch(
            "src.tools.manage_curation.release_db_session", new_callable=AsyncMock
        ),
        patch(
            "src.tools.manage_curation._read_memory",
            new_callable=AsyncMock,
            return_value=fake_node,
        ),
        pytest.raises(ToolError, match="project_id is required"),
    ):
        await manage_curation(
            action="report_contradiction",
            memory_id=MEMORY_UUID,
            observed_behavior="user used Docker instead of Podman",
        )


@pytest.mark.asyncio
async def test_report_contradiction_campaign_with_project_id():
    from src.tools.manage_curation import manage_curation

    fake_node = _fake_campaign_node()
    mock_session = AsyncMock()
    mock_gen = AsyncMock()

    with (
        patch(
            "src.tools.manage_curation.get_claims_from_context",
            return_value=_campaign_claims(),
        ),
        patch(
            "src.tools.manage_curation.get_db_session",
            return_value=(mock_session, mock_gen),
        ),
        patch(
            "src.tools.manage_curation.release_db_session", new_callable=AsyncMock
        ),
        patch(
            "src.tools.manage_curation._read_memory",
            new_callable=AsyncMock,
            return_value=fake_node,
        ),
        patch(
            "src.tools.manage_curation.get_campaigns_for_project",
            new_callable=AsyncMock,
            return_value={CAMPAIGN_UUID},
        ),
        patch(
            "src.tools.manage_curation._report_contradiction",
            new_callable=AsyncMock,
            return_value=1,
        ),
    ):
        result = await manage_curation(
            action="report_contradiction",
            memory_id=MEMORY_UUID,
            observed_behavior="user used Docker instead of Podman",
            project_id="my-project",
        )

    assert result["contradiction_count"] == 1


# --- create_relationship ---


@pytest.mark.asyncio
async def test_create_relationship_campaign_requires_project_id():
    from src.tools.manage_graph import manage_graph

    fake_node = _fake_campaign_node()
    target_uuid = str(uuid.uuid4())
    mock_session = AsyncMock()
    mock_gen = AsyncMock()

    with (
        patch(
            "src.tools.manage_graph.get_claims_from_context",
            return_value=_campaign_claims(),
        ),
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
            return_value=fake_node,
        ),
        pytest.raises(ToolError, match="project_id is required"),
    ):
        await manage_graph(
            action="create_relationship",
            source_id=MEMORY_UUID,
            target_id=target_uuid,
            relationship_type="related_to",
        )


@pytest.mark.asyncio
async def test_create_relationship_campaign_with_project_id():
    from src.tools.manage_graph import manage_graph

    fake_source = _fake_campaign_node()
    target_id = uuid.uuid4()
    _fake_campaign_node(id=target_id)
    mock_session = AsyncMock()
    mock_gen = AsyncMock()

    # Mock return value for the relationship creation
    fake_rel = SimpleNamespace()
    fake_rel.model_dump = lambda mode="json": {
        "id": str(uuid.uuid4()),
        "source_id": MEMORY_UUID,
        "target_id": str(target_id),
        "relationship_type": "related_to",
    }

    with (
        patch(
            "src.tools.manage_graph.get_claims_from_context",
            return_value=_campaign_claims(),
        ),
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
            "src.tools.manage_graph.get_campaigns_for_project",
            new_callable=AsyncMock,
            return_value={CAMPAIGN_UUID},
        ),
        patch(
            "src.tools.manage_graph.create_relationship_service",
            new_callable=AsyncMock,
            return_value=fake_rel,
        ),
    ):
        result = await manage_graph(
            action="create_relationship",
            source_id=MEMORY_UUID,
            target_id=str(target_id),
            relationship_type="related_to",
            project_id="my-project",
        )

    assert result["relationship_type"] == "related_to"


# --- suggest_merge (consolidated into create_relationship via #174) ---
# Tests for suggest_merge as a standalone tool were removed when the tool
# was consolidated into create_relationship (use relationship_type=
# "conflicts_with" with merge metadata). Campaign-scope coverage for
# create_relationship is above (test_create_relationship_*).


# --- delete_memory ---


@pytest.mark.asyncio
async def test_delete_memory_campaign_requires_project_id():
    from src.tools.delete_memory import delete_memory

    fake_node = _fake_campaign_node()
    mock_session = AsyncMock()
    mock_gen = AsyncMock()

    with (
        patch(
            "src.tools.delete_memory.get_claims_from_context",
            return_value=_campaign_claims(),
        ),
        patch(
            "src.tools.delete_memory.get_db_session",
            return_value=(mock_session, mock_gen),
        ),
        patch("src.tools.delete_memory.release_db_session", new_callable=AsyncMock),
        patch(
            "src.tools.delete_memory._read_memory",
            new_callable=AsyncMock,
            return_value=fake_node,
        ),
        pytest.raises(ToolError, match="project_id is required"),
    ):
        await delete_memory(memory_id=MEMORY_UUID)


@pytest.mark.asyncio
async def test_delete_memory_campaign_with_project_id():
    from src.tools.delete_memory import delete_memory

    fake_node = _fake_campaign_node()
    mock_session = AsyncMock()
    mock_gen = AsyncMock()

    with (
        patch(
            "src.tools.delete_memory.get_claims_from_context",
            return_value=_campaign_claims(),
        ),
        patch(
            "src.tools.delete_memory.get_db_session",
            return_value=(mock_session, mock_gen),
        ),
        patch("src.tools.delete_memory.release_db_session", new_callable=AsyncMock),
        patch(
            "src.tools.delete_memory._read_memory",
            new_callable=AsyncMock,
            return_value=fake_node,
        ),
        patch(
            "src.tools.delete_memory.get_campaigns_for_project",
            new_callable=AsyncMock,
            return_value={CAMPAIGN_UUID},
        ),
        patch(
            "src.tools.delete_memory.svc_delete_memory",
            new_callable=AsyncMock,
            return_value={
                "deleted_id": MEMORY_UUID,
                "versions_deleted": 1,
                "branches_deleted": 0,
                "total_deleted": 1,
            },
        ),
        patch("src.tools.delete_memory.broadcast_after_write", new_callable=AsyncMock),
    ):
        result = await delete_memory(memory_id=MEMORY_UUID, project_id="my-project")

    assert result["total_deleted"] == 1


# --- get_relationships (post-fetch RBAC) ---


@pytest.mark.asyncio
async def test_get_relationships_campaign_nodes_filtered_without_project_id():
    """Without project_id, campaign-scoped related nodes are silently filtered."""
    from src.tools.manage_graph import manage_graph

    mock_session = AsyncMock()
    mock_gen = AsyncMock()

    # Build a relationship where source_node is campaign-scoped
    fake_rel = SimpleNamespace()
    fake_rel.model_dump = lambda mode="json": {
        "id": str(uuid.uuid4()),
        "source_node": {
            "scope": "campaign",
            "owner_id": CAMPAIGN_UUID,
            "tenant_id": "default",
        },
        "target_node": {
            "scope": "user",
            "owner_id": "wjackson",
            "tenant_id": "default",
        },
    }

    with (
        patch(
            "src.tools.manage_graph.get_claims_from_context",
            return_value=_campaign_claims(),
        ),
        patch(
            "src.tools.manage_graph.get_db_session",
            return_value=(mock_session, mock_gen),
        ),
        patch("src.tools.manage_graph.release_db_session", new_callable=AsyncMock),
        patch(
            "src.tools.manage_graph.get_relationships_service",
            new_callable=AsyncMock,
            return_value=[fake_rel],
        ),
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
        result = await manage_graph(action="get_relationships", node_id=MEMORY_UUID)

    # Without project_id, campaign_ids is None → campaign node filtered out
    assert result["count"] == 0
    assert result["omitted_count"] == 1


@pytest.mark.asyncio
async def test_get_relationships_campaign_nodes_accessible_with_project_id():
    """With project_id, campaign-scoped related nodes pass the RBAC filter."""
    from src.tools.manage_graph import manage_graph

    mock_session = AsyncMock()
    mock_gen = AsyncMock()

    fake_rel = SimpleNamespace()
    fake_rel.model_dump = lambda mode="json": {
        "id": str(uuid.uuid4()),
        "source_node": {
            "scope": "campaign",
            "owner_id": CAMPAIGN_UUID,
            "tenant_id": "default",
        },
        "target_node": {
            "scope": "user",
            "owner_id": "wjackson",
            "tenant_id": "default",
        },
    }

    with (
        patch(
            "src.tools.manage_graph.get_claims_from_context",
            return_value=_campaign_claims(),
        ),
        patch(
            "src.tools.manage_graph.get_db_session",
            return_value=(mock_session, mock_gen),
        ),
        patch("src.tools.manage_graph.release_db_session", new_callable=AsyncMock),
        patch(
            "src.tools.manage_graph.get_relationships_service",
            new_callable=AsyncMock,
            return_value=[fake_rel],
        ),
        patch(
            "src.tools.manage_graph.get_campaigns_for_project",
            new_callable=AsyncMock,
            return_value={CAMPAIGN_UUID},
        ),
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
        result = await manage_graph(action="get_relationships", node_id=MEMORY_UUID, project_id="my-project")

    assert result["count"] == 1
    assert "omitted_count" not in result


# --- Signature tests ---


@pytest.mark.parametrize(
    "tool_module,tool_name",
    [
        ("src.tools.read_memory", "read_memory"),
        ("src.tools.manage_graph", "manage_graph"),
        ("src.tools.manage_curation", "manage_curation"),
        ("src.tools.delete_memory", "delete_memory"),
    ],
)
def test_tool_has_project_id_parameter(tool_module, tool_name):
    """All read-path tools must expose project_id for campaign enrollment."""
    import importlib
    import inspect

    mod = importlib.import_module(tool_module)
    tool_fn = getattr(mod, tool_name)
    sig = inspect.signature(tool_fn)
    assert "project_id" in sig.parameters, (
        f"{tool_name} must have a project_id parameter for campaign enrollment (#162)"
    )
    assert sig.parameters["project_id"].default is None, (
        f"{tool_name}.project_id must default to None"
    )

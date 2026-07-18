"""Tests for source tagging: default values, filtering, and reconciliation."""

import inspect
import uuid as _uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

import src.tools.auth as auth_mod
from memoryhub_core.models.schemas import (
    MemoryNodeCreate,
    MemoryNodeRead,
    MemoryNodeStub,
    MemoryScope,
    StorageType,
)
from src.tools.search_memory import search_memory


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_read_node(
    content: str = "test content",
    source: str = "agent",
    weight: float = 0.7,
    owner_id: str = "wjackson",
    tenant_id: str = "default",
) -> MemoryNodeRead:
    """Build a MemoryNodeRead with a configurable source field."""
    return MemoryNodeRead(
        id=_uuid.uuid4(),
        parent_id=None,
        content=content,
        stub=content[:80],
        storage_type=StorageType.INLINE,
        content_ref=None,
        weight=weight,
        scope=MemoryScope.USER,
        branch_type=None,
        owner_id=owner_id,
        tenant_id=tenant_id,
        is_current=True,
        version=1,
        previous_version_id=None,
        metadata=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        expires_at=None,
        has_children=False,
        has_rationale=False,
        branch_count=0,
        source=source,
    )


def _make_stub_node(
    stub: str = "stub text",
    source: str = "agent",
    weight: float = 0.5,
) -> MemoryNodeStub:
    """Build a MemoryNodeStub with a configurable source field."""
    return MemoryNodeStub(
        id=_uuid.uuid4(),
        stub=stub,
        scope=MemoryScope.USER,
        weight=weight,
        branch_type=None,
        has_children=False,
        has_rationale=False,
        source=source,
    )


# ---------------------------------------------------------------------------
# Schema-level tests
# ---------------------------------------------------------------------------


def test_create_memory_default_source():
    """Creating a MemoryNodeCreate without specifying source defaults to None,
    which the service layer interprets as 'agent'."""
    data = MemoryNodeCreate(
        content="remember this",
        scope="user",
        weight=0.7,
        owner_id="wjackson",
    )
    assert data.source is None


def test_create_memory_explicit_source():
    """Setting source='dreaming' on MemoryNodeCreate persists correctly."""
    data = MemoryNodeCreate(
        content="extracted from conversation",
        scope="user",
        weight=0.7,
        owner_id="wjackson",
        source="dreaming",
    )
    assert data.source == "dreaming"


# ---------------------------------------------------------------------------
# Search source filter tests
# ---------------------------------------------------------------------------


async def _run_search_with_source_filter(**call_kwargs):
    """Helper that patches all dependencies and runs search_memory.

    Returns the search_memories mock alongside the tool result so callers
    can inspect forwarded kwargs.
    """
    mock_session = AsyncMock()
    mock_gen = AsyncMock()
    fake_embedding_service = AsyncMock()
    mock_valkey = AsyncMock()
    mock_valkey.read_compilation = AsyncMock(return_value=None)
    mock_valkey.write_compilation = AsyncMock()

    auth_mod._current_session = {
        "user_id": "wjackson",
        "scopes": ["user"],
        "identity_type": "user",
    }
    try:
        with (
            patch(
                "src.tools.search_memory.get_db_session",
                return_value=(mock_session, mock_gen),
            ),
            patch(
                "src.tools.search_memory.release_db_session",
                new_callable=AsyncMock,
            ),
            patch(
                "src.tools.search_memory.get_embedding_service",
                return_value=fake_embedding_service,
            ),
            patch(
                "src.tools.search_memory.search_memories",
                new_callable=AsyncMock,
                return_value=[],
            ) as mock_search,
            patch(
                "src.tools.search_memory.count_search_matches",
                new_callable=AsyncMock,
                return_value=0,
            ) as mock_count,
            patch(
                "src.tools.search_memory.get_valkey_client",
                return_value=mock_valkey,
            ),
            patch(
                "src.tools.search_memory.ROLE_ISOLATION_ENABLED",
                False,
            ),
            patch(
                "src.tools.search_memory.PROJECT_ISOLATION_ENABLED",
                False,
            ),
            patch(
                "src.tools.search_memory.detect_patterns",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            result = await search_memory(query="test query", **call_kwargs)
            return result, mock_search, mock_count
    finally:
        auth_mod._current_session = None


@pytest.mark.asyncio
async def test_search_source_filter():
    """source='dreaming' is forwarded to search_memories."""
    result, mock_search, mock_count = await _run_search_with_source_filter(
        source="dreaming",
    )

    _, search_kwargs = mock_search.call_args
    assert search_kwargs.get("source") == "dreaming", (
        f"Expected source='dreaming' forwarded to search_memories, got {search_kwargs}"
    )


@pytest.mark.asyncio
async def test_search_exclude_source():
    """exclude_source='dreaming' is forwarded to search_memories."""
    result, mock_search, mock_count = await _run_search_with_source_filter(
        exclude_source="dreaming",
    )

    _, search_kwargs = mock_search.call_args
    assert search_kwargs.get("exclude_source") == "dreaming", (
        f"Expected exclude_source='dreaming' forwarded to search_memories, got {search_kwargs}"
    )


# ---------------------------------------------------------------------------
# Search tool parameter defaults
# ---------------------------------------------------------------------------


def test_search_memory_source_params_have_defaults():
    """Verify source and exclude_source parameters exist and default to None."""
    sig = inspect.signature(search_memory)
    params = sig.parameters

    assert "source" in params
    assert params["source"].default is None
    assert "exclude_source" in params
    assert params["exclude_source"].default is None


# ---------------------------------------------------------------------------
# Reconciliation sets source='dreaming'
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reconciliation_sets_dreaming_source():
    """reconcile_candidate creates memories with source='dreaming'."""
    from memoryhub_core.services.reconciliation import (
        ExtractionCandidate,
        reconcile_candidate,
    )

    candidate = ExtractionCandidate(
        content="Paris is the capital of France",
        weight=0.8,
        content_type="experiential",
    )

    fake_node = _make_read_node(
        content=candidate.content,
        source="dreaming",
    )
    fake_curation = {
        "blocked": False,
        "reason": None,
        "detail": None,
        "similar_count": 0,
        "nearest_id": None,
        "nearest_score": None,
        "flags": [],
    }

    captured_data: list[MemoryNodeCreate] = []

    async def fake_create_memory(data, session, embedding_service, **kwargs):
        captured_data.append(data)
        return fake_node, fake_curation

    with (
        patch(
            "memoryhub_core.services.reconciliation.create_memory",
            new_callable=AsyncMock,
            side_effect=fake_create_memory,
        ),
        patch(
            "memoryhub_core.services.reconciliation.check_similarity",
            new_callable=AsyncMock,
            return_value=SimpleNamespace(
                blocked=False,
                similar_count=0,
                nearest_id=None,
                nearest_score=None,
                flags=[],
            ),
        ),
    ):
        result = await reconcile_candidate(
            candidate=candidate,
            owner_id="wjackson",
            scope="user",
            scope_id=None,
            session=AsyncMock(),
            embedding_service=AsyncMock(),
            tenant_id="default",
            extraction_run_id="test-run-001",
        )

    assert result.action == "create"
    assert len(captured_data) == 1
    assert captured_data[0].source == "dreaming"


# ---------------------------------------------------------------------------
# Source in read response
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_source_in_read_response():
    """read_memory returns the source field in its model_dump output."""
    from src.tools.read_memory import read_memory

    fake_node = _make_read_node(source="dreaming")
    mock_session = AsyncMock()
    mock_gen = AsyncMock()

    auth_mod._current_session = {
        "user_id": "wjackson",
        "scopes": ["user"],
        "identity_type": "user",
    }
    try:
        with (
            patch(
                "src.tools.read_memory.get_db_session",
                return_value=(mock_session, mock_gen),
            ),
            patch(
                "src.tools.read_memory.release_db_session",
                new_callable=AsyncMock,
            ),
            patch(
                "src.tools.read_memory._read_memory",
                new_callable=AsyncMock,
                return_value=fake_node,
            ),
        ):
            result = await read_memory(memory_id=str(fake_node.id))
    finally:
        auth_mod._current_session = None

    assert result["source"] == "dreaming"


# ---------------------------------------------------------------------------
# Source in stub response
# ---------------------------------------------------------------------------


def test_source_in_stub_response():
    """MemoryNodeStub includes the source field."""
    stub = _make_stub_node(source="dreaming")
    dumped = stub.model_dump(mode="json")
    assert dumped["source"] == "dreaming"


def test_stub_default_source_is_agent():
    """MemoryNodeStub defaults source to 'agent' when not specified."""
    stub = MemoryNodeStub(
        id=_uuid.uuid4(),
        stub="a stub",
        scope=MemoryScope.USER,
        weight=0.5,
    )
    assert stub.source == "agent"


# ---------------------------------------------------------------------------
# _build_search_filters respects source / exclude_source
# ---------------------------------------------------------------------------


def test_build_search_filters_source_filter():
    """_build_search_filters adds a source == 'dreaming' clause when
    source='dreaming' is passed."""
    from memoryhub_core.services.memory import _build_search_filters

    filters = _build_search_filters(
        scope=None,
        owner_id=None,
        current_only=True,
        authorized_scopes=None,
        tenant_id="default",
        source="dreaming",
    )

    assert filters is not None
    has_source_match = False
    for f in filters:
        clause_str = str(f.compile(compile_kwargs={"literal_binds": True}))
        if "source" in clause_str.lower() and "dreaming" in clause_str.lower() and "!=" not in clause_str:
            has_source_match = True
            break

    assert has_source_match, f"Expected source='dreaming' filter in: {filters}"


def test_build_search_filters_exclude_source():
    """_build_search_filters adds a source != 'dreaming' clause when
    exclude_source='dreaming' is passed."""
    from memoryhub_core.services.memory import _build_search_filters

    filters = _build_search_filters(
        scope=None,
        owner_id=None,
        current_only=True,
        authorized_scopes=None,
        tenant_id="default",
        exclude_source="dreaming",
    )

    assert filters is not None
    has_exclusion = False
    for f in filters:
        clause_str = str(f.compile(compile_kwargs={"literal_binds": True}))
        if "source" in clause_str.lower() and "dreaming" in clause_str.lower() and "!=" in clause_str:
            has_exclusion = True
            break

    assert has_exclusion, f"Expected source != 'dreaming' filter in: {filters}"

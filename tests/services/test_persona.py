"""Tests for the persona compilation service — WRIG-1483."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from memoryhub_core.models.memory import MemoryNode, MemoryRelationship
from memoryhub_core.services.persona import (
    _SYNOPSIS_SOURCE,
    _SYNOPSIS_WEIGHT,
    _create_provenance_edges,
    add_user_pin,
    compile_persona_synopsis,
    get_current_synopsis,
    get_dreaming_nodes,
    get_persona_status,
    get_user_pins,
    mark_synopsis_stale,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_node(**kwargs) -> MemoryNode:
    defaults = {
        "id": uuid.uuid4(),
        "logical_id": uuid.uuid4(),
        "content": "Prefers async communication over meetings.",
        "stub": "Prefers async communication...",
        "scope": "user",
        "owner_id": "alice",
        "tenant_id": "default",
        "source": "dreaming",
        "content_type": "behavioral",
        "weight": 0.8,
        "is_current": True,
        "deleted_at": None,
        "status": "active",
        "updated_at": datetime.now(UTC),
        "created_at": datetime.now(UTC),
        "metadata_": {},
        "domains": [],
        "scope_id": None,
        "version": 1,
        "branch_type": None,
        "parent_id": None,
        "previous_version_id": None,
    }
    defaults.update(kwargs)
    node = MagicMock(spec=MemoryNode)
    for k, v in defaults.items():
        setattr(node, k, v)
    return node


# ---------------------------------------------------------------------------
# get_dreaming_nodes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_dreaming_nodes_returns_facts():
    """Returns a list of fact dicts from the DB query."""
    node = _make_node(
        id=uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001"),
        content="Alice prefers dark mode.",
        updated_at=datetime(2026, 1, 15, tzinfo=UTC),
    )
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [node]

    session = AsyncMock(spec=AsyncSession)
    session.execute = AsyncMock(return_value=mock_result)

    facts = await get_dreaming_nodes("alice", "default", session)

    assert len(facts) == 1
    assert facts[0]["content"] == "Alice prefers dark mode."
    assert facts[0]["id"] == "aaaaaaaa-0000-0000-0000-000000000001"
    assert "2026-01-15" in facts[0]["updated_at"]


@pytest.mark.asyncio
async def test_get_dreaming_nodes_empty():
    """Returns empty list when no behavioral facts exist."""
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    session = AsyncMock(spec=AsyncSession)
    session.execute = AsyncMock(return_value=mock_result)

    facts = await get_dreaming_nodes("nobody", "default", session)
    assert facts == []


# ---------------------------------------------------------------------------
# get_current_synopsis
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_current_synopsis_found():
    """Returns the synopsis node when one exists."""
    node = _make_node(source=_SYNOPSIS_SOURCE, weight=_SYNOPSIS_WEIGHT)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = node
    session = AsyncMock(spec=AsyncSession)
    session.execute = AsyncMock(return_value=mock_result)

    result = await get_current_synopsis("alice", "default", session)
    assert result is node


@pytest.mark.asyncio
async def test_get_current_synopsis_none():
    """Returns None when no synopsis has been compiled."""
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    session = AsyncMock(spec=AsyncSession)
    session.execute = AsyncMock(return_value=mock_result)

    result = await get_current_synopsis("newuser", "default", session)
    assert result is None


# ---------------------------------------------------------------------------
# get_user_pins
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_user_pins_returns_pin_list():
    """Returns a list of pin dicts for a given synopsis."""
    pin = _make_node(
        id=uuid.UUID("cccccccc-0000-0000-0000-000000000003"),
        content="I prefer Rust for systems code.",
        source="user",
        branch_type="fact",
        created_at=datetime(2026, 9, 15, tzinfo=UTC),
    )
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [pin]

    session = AsyncMock(spec=AsyncSession)
    session.execute = AsyncMock(return_value=mock_result)

    pins = await get_user_pins("alice", "default", session)
    assert len(pins) == 1
    assert pins[0]["id"] == "cccccccc-0000-0000-0000-000000000003"
    assert pins[0]["content"] == "I prefer Rust for systems code."
    assert "2026-09-15" in pins[0]["created_at"]


@pytest.mark.asyncio
async def test_get_user_pins_empty():
    """Returns empty list when no pins exist."""
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    session = AsyncMock(spec=AsyncSession)
    session.execute = AsyncMock(return_value=mock_result)

    pins = await get_user_pins("alice", "default", session)
    assert pins == []


# ---------------------------------------------------------------------------
# get_persona_status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_persona_status_no_synopsis():
    """Returns has_synopsis=False and is_stale=True when no synopsis exists."""
    dreaming_node = _make_node()
    mock_dreaming_result = MagicMock()
    mock_dreaming_result.scalars.return_value.all.return_value = [dreaming_node]
    mock_synopsis_result = MagicMock()
    mock_synopsis_result.scalar_one_or_none.return_value = None

    session = AsyncMock(spec=AsyncSession)
    session.execute = AsyncMock(side_effect=[mock_synopsis_result, mock_dreaming_result])

    status = await get_persona_status("alice", "default", session)

    assert status["has_synopsis"] is False
    assert status["is_stale"] is True
    assert "no synopsis" in status["stale_reason"]
    assert status["source_fact_count"] == 1
    assert status["synopsis_id"] is None


@pytest.mark.asyncio
async def test_get_persona_status_current():
    """Returns is_stale=False when synopsis metadata_ stale is falsy."""
    synopsis = _make_node(
        source=_SYNOPSIS_SOURCE,
        weight=_SYNOPSIS_WEIGHT,
        metadata_={"stale": False, "source_fact_count": 3},
        version=2,
    )
    mock_synopsis_result = MagicMock()
    mock_synopsis_result.scalar_one_or_none.return_value = synopsis
    mock_dreaming_result = MagicMock()
    mock_dreaming_result.scalars.return_value.all.return_value = []

    session = AsyncMock(spec=AsyncSession)
    session.execute = AsyncMock(side_effect=[mock_synopsis_result, mock_dreaming_result])

    status = await get_persona_status("alice", "default", session)

    assert status["has_synopsis"] is True
    assert status["is_stale"] is False
    assert status["stale_reason"] is None
    assert status["compiled_fact_count"] == 3
    assert status["version"] == 2


@pytest.mark.asyncio
async def test_get_persona_status_stale():
    """Returns is_stale=True when synopsis metadata_ stale=True."""
    synopsis = _make_node(
        source=_SYNOPSIS_SOURCE,
        weight=_SYNOPSIS_WEIGHT,
        metadata_={"stale": True, "source_fact_count": 2},
    )
    mock_synopsis_result = MagicMock()
    mock_synopsis_result.scalar_one_or_none.return_value = synopsis
    mock_dreaming_result = MagicMock()
    mock_dreaming_result.scalars.return_value.all.return_value = []

    session = AsyncMock(spec=AsyncSession)
    session.execute = AsyncMock(side_effect=[mock_synopsis_result, mock_dreaming_result])

    status = await get_persona_status("alice", "default", session)

    assert status["is_stale"] is True
    assert "dreaming facts" in status["stale_reason"]


# ---------------------------------------------------------------------------
# mark_synopsis_stale
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mark_synopsis_stale_no_synopsis():
    """Returns False when there is no synopsis to mark stale."""
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    session = AsyncMock(spec=AsyncSession)
    session.execute = AsyncMock(return_value=mock_result)

    result = await mark_synopsis_stale("alice", "default", session)
    assert result is False


@pytest.mark.asyncio
async def test_mark_synopsis_stale_already_stale():
    """Returns True and skips update when synopsis is already marked stale."""
    synopsis = _make_node(
        source=_SYNOPSIS_SOURCE,
        metadata_={"stale": True},
    )
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = synopsis
    session = AsyncMock(spec=AsyncSession)
    session.execute = AsyncMock(return_value=mock_result)

    result = await mark_synopsis_stale("alice", "default", session)

    assert result is True
    # commit should NOT be called since it was already stale
    session.commit.assert_not_called()


@pytest.mark.asyncio
async def test_mark_synopsis_stale_marks_and_commits():
    """Writes stale=True to metadata and commits."""
    synopsis = _make_node(
        id=uuid.UUID("dddddddd-0000-0000-0000-000000000004"),
        source=_SYNOPSIS_SOURCE,
        metadata_={"source_fact_count": 3},
    )
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = synopsis
    session = AsyncMock(spec=AsyncSession)
    # First execute: synopsis lookup; second execute: update statement
    session.execute = AsyncMock(side_effect=[mock_result, MagicMock()])

    result = await mark_synopsis_stale("alice", "default", session)

    assert result is True
    session.commit.assert_awaited_once()
    # Verify the update statement was issued
    assert session.execute.await_count == 2


# ---------------------------------------------------------------------------
# _create_provenance_edges
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_provenance_edges_adds_relationships():
    """Adds a MemoryRelationship row for each fact ID."""
    synopsis_id = uuid.uuid4()
    fact_ids = [uuid.uuid4(), uuid.uuid4()]
    tenant_id = "default"

    session = AsyncMock(spec=AsyncSession)
    session.add = MagicMock()
    session.flush = AsyncMock()

    await _create_provenance_edges(synopsis_id, fact_ids, tenant_id, session)

    assert session.add.call_count == 2
    for c in session.add.call_args_list:
        rel = c[0][0]
        assert isinstance(rel, MemoryRelationship)
        assert rel.source_id == synopsis_id
        assert rel.relationship_type == "derived_from"
        assert rel.tenant_id == tenant_id

    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_provenance_edges_empty():
    """No relationships added and no flush when fact_ids is empty."""
    session = AsyncMock(spec=AsyncSession)
    session.add = MagicMock()
    session.flush = AsyncMock()

    await _create_provenance_edges(uuid.uuid4(), [], "default", session)

    session.add.assert_not_called()
    session.flush.assert_awaited_once()


# ---------------------------------------------------------------------------
# add_user_pin
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_user_pin_anchors_to_current_synopsis():
    """Pin parent_id is set to the current synopsis when no synopsis_id given."""
    synopsis_id = uuid.uuid4()
    synopsis = _make_node(id=synopsis_id, source=_SYNOPSIS_SOURCE)
    mock_synopsis_result = MagicMock()
    mock_synopsis_result.scalar_one_or_none.return_value = synopsis

    session = AsyncMock(spec=AsyncSession)
    session.execute = AsyncMock(return_value=mock_synopsis_result)
    session.add = MagicMock()
    session.commit = AsyncMock()

    result = await add_user_pin("alice", "default", "I prefer dark mode.", session)

    assert result["user_id"] == "alice"
    assert result["content"] == "I prefer dark mode."
    assert result["synopsis_id"] == str(synopsis_id)
    assert "pin_id" in result
    assert "note" in result

    session.add.assert_called_once()
    pin_node = session.add.call_args[0][0]
    assert pin_node.source == "user"
    assert pin_node.branch_type == "fact"
    assert pin_node.parent_id == synopsis_id
    assert pin_node.content == "I prefer dark mode."


@pytest.mark.asyncio
async def test_add_user_pin_no_synopsis_stores_free_standing():
    """When no synopsis exists, pin is stored with parent_id=None."""
    mock_synopsis_result = MagicMock()
    mock_synopsis_result.scalar_one_or_none.return_value = None

    session = AsyncMock(spec=AsyncSession)
    session.execute = AsyncMock(return_value=mock_synopsis_result)
    session.add = MagicMock()
    session.commit = AsyncMock()

    result = await add_user_pin("alice", "default", "Prefers pair programming.", session)

    assert result["synopsis_id"] is None
    pin_node = session.add.call_args[0][0]
    assert pin_node.parent_id is None


# ---------------------------------------------------------------------------
# compile_persona_synopsis — version chain
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compile_raises_when_no_facts():
    """Raises ValueError when no dreaming facts are available."""
    mock_dreaming_result = MagicMock()
    mock_dreaming_result.scalars.return_value.all.return_value = []
    session = AsyncMock(spec=AsyncSession)
    session.execute = AsyncMock(return_value=mock_dreaming_result)

    with pytest.raises(ValueError, match="No behavioral dreaming facts"):
        await compile_persona_synopsis(
            "nobody", "default", session,
            model="gemini-pro", url="https://example.com",
        )


@pytest.mark.asyncio
async def test_compile_raises_when_llm_not_configured():
    """Raises ValueError when model/url are not set."""
    session = AsyncMock(spec=AsyncSession)
    with pytest.raises(ValueError, match="MEMORYHUB_CONV_EXTRACTION_MODEL"):
        await compile_persona_synopsis("alice", "default", session)


@pytest.mark.asyncio
async def test_compile_creates_synopsis_node():
    """Happy path: facts → LLM → synopsis node stored."""
    node = _make_node(
        content="Alice prefers async communication.",
        updated_at=datetime(2026, 9, 1, tzinfo=UTC),
    )
    mock_dreaming_result = MagicMock()
    mock_dreaming_result.scalars.return_value.all.return_value = [node]
    mock_synopsis_result = MagicMock()
    mock_synopsis_result.scalar_one_or_none.return_value = None
    mock_pins_result = MagicMock()
    mock_pins_result.scalars.return_value.all.return_value = []

    session = AsyncMock(spec=AsyncSession)
    session.execute = AsyncMock(
        side_effect=[mock_dreaming_result, mock_synopsis_result, mock_pins_result]
    )
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()

    synopsis_md = "## Preferences\n- Async communication.\n"

    with (
        patch("memoryhub_core.services.persona._call_synopsis_llm", new_callable=AsyncMock, return_value=synopsis_md),
        patch("memoryhub_core.services.persona._create_provenance_edges", new_callable=AsyncMock),
    ):
        result = await compile_persona_synopsis(
            "alice", "default", session,
            model="gemini-pro", url="https://example.com",
        )

    assert result["user_id"] == "alice"
    assert result["source_fact_count"] == 1
    assert result["content"] == synopsis_md
    assert result["previous_synopsis_id"] is None
    assert result["version"] == 1
    assert result["is_stale"] is False
    assert "synopsis_id" in result


@pytest.mark.asyncio
async def test_compile_retires_previous_synopsis():
    """Existing synopsis is retired (is_current=False) before new one is stored."""
    dreaming_node = _make_node()
    old_logical_id = uuid.uuid4()
    old_synopsis = _make_node(
        id=uuid.UUID("bbbbbbbb-0000-0000-0000-000000000002"),
        logical_id=old_logical_id,
        source=_SYNOPSIS_SOURCE,
        weight=_SYNOPSIS_WEIGHT,
        is_current=True,
        version=3,
        metadata_={"source_fact_count": 2, "pin_count": 0, "stale": True},
    )

    mock_dreaming_result = MagicMock()
    mock_dreaming_result.scalars.return_value.all.return_value = [dreaming_node]
    mock_synopsis_result = MagicMock()
    mock_synopsis_result.scalar_one_or_none.return_value = old_synopsis
    mock_pins_result = MagicMock()
    mock_pins_result.scalars.return_value.all.return_value = []

    session = AsyncMock(spec=AsyncSession)
    session.execute = AsyncMock(
        side_effect=[mock_dreaming_result, mock_synopsis_result, mock_pins_result]
    )
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()

    with (
        patch("memoryhub_core.services.persona._call_synopsis_llm", new_callable=AsyncMock, return_value="## New\n- Better.\n"),
        patch("memoryhub_core.services.persona._create_provenance_edges", new_callable=AsyncMock),
    ):
        result = await compile_persona_synopsis(
            "alice", "default", session,
            model="gemini-pro", url="https://example.com",
        )

    assert result["previous_synopsis_id"] == "bbbbbbbb-0000-0000-0000-000000000002"
    assert result["version"] == 4  # old was v3, new is v4

    # Old synopsis must be retired
    assert old_synopsis.is_current is False

    # session.add is called first for old_synopsis (retired), then for new_node
    new_node = session.add.call_args_list[1][0][0]
    assert new_node.logical_id == old_logical_id
    assert new_node.previous_version_id == uuid.UUID("bbbbbbbb-0000-0000-0000-000000000002")
    assert new_node.is_current is True
    assert new_node.metadata_["stale"] is False

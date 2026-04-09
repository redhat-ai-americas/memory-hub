"""Cross-tenant tool-level integration tests for issue #46 (Phase 5).

These tests go through the REAL MCP tool functions end-to-end and prove
that a write as tenant A is invisible to a read as tenant B. The trick
is patching ``get_claims_from_context`` per tool module to return a
specific tenant claim and mocking the service boundary with a small
fake that mimics the tenant-filtered SQL behavior from Phase 4.

Together with the per-tool tenant-forwarding tests added in Phase 4f
(test_*.py::test_*_forwards_tenant_id_to_service) and the real-SQL
integration tests in ``tests/integration/test_tenant_isolation.py``,
this file provides the tool-layer acceptance coverage for #46.

What's real in these tests:
  - The tool functions (write_memory, read_memory, search_memory, ...).
  - The authz layer (authorize_read, authorize_write, get_tenant_filter).
  - The Pydantic schemas on inputs and outputs.
  - Claim resolution (patched via get_claims_from_context).

What's faked:
  - The service boundary (create_memory, _read_memory, search_memories,
    ...). The fakes enforce tenant filtering in-memory so the tool sees
    the same shapes the real service would return under tenant isolation.
  - The database session (MagicMock).
  - Push broadcast (no-op mock).
"""

import datetime as _dt
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp.exceptions import ToolError

from memoryhub_core.models.schemas import (
    MemoryNodeRead,
    MemoryScope,
    StorageType,
)
from memoryhub_core.services.exceptions import MemoryNotFoundError

# ---------------------------------------------------------------------------
# Fake in-memory tenant-aware stores
# ---------------------------------------------------------------------------


class FakeMemoryStore:
    """An in-memory stand-in for the memory service layer with tenant
    filtering baked in. Each memory lives in exactly one tenant; reads,
    searches, and history walks filter on tenant_id the same way the
    real SQL layer does in Phase 4.
    """

    def __init__(self) -> None:
        # id -> MemoryNodeRead (which carries tenant_id)
        self.memories: dict[uuid.UUID, MemoryNodeRead] = {}
        # contradictions keyed by memory_id
        self.contradictions: dict[uuid.UUID, list[dict]] = {}
        # relationships keyed by source+target+type
        self.relationships: list[dict] = []
        # curator rules: list of (tenant_id, owner_id, name)
        self.rules: list[dict] = []

    def add(self, memory: MemoryNodeRead) -> None:
        self.memories[memory.id] = memory

    def read(self, memory_id: uuid.UUID, tenant_id: str) -> MemoryNodeRead:
        """Tenant-filtered read — cross-tenant raises MemoryNotFoundError."""
        node = self.memories.get(memory_id)
        if node is None or node.tenant_id != tenant_id:
            raise MemoryNotFoundError(memory_id)
        return node

    def search(
        self,
        *,
        tenant_id: str,
        owner_id: str | None,
    ) -> list[tuple[MemoryNodeRead, float]]:
        """Tenant-filtered search. Returns (node, score) tuples in the
        same shape as the real service, with a fixed synthetic score
        since relevance isn't what's being tested.
        """
        results: list[tuple[MemoryNodeRead, float]] = []
        for node in self.memories.values():
            if node.tenant_id != tenant_id:
                continue
            if owner_id is not None and node.owner_id != owner_id:
                continue
            results.append((node, 0.9))
        return results

    def history(self, memory_id: uuid.UUID, tenant_id: str) -> dict:
        """Tenant-filtered version history walk."""
        node = self.memories.get(memory_id)
        if node is None or node.tenant_id != tenant_id:
            raise MemoryNotFoundError(memory_id)
        # For test purposes, return a single version (the current one).
        version = SimpleNamespace(
            id=node.id,
            version=node.version,
            is_current=True,
            created_at=node.created_at,
            stub=node.stub,
            content=node.content,
            expires_at=None,
        )
        version.model_dump = lambda mode="json": {
            "id": str(node.id),
            "version": node.version,
            "is_current": True,
            "created_at": node.created_at.isoformat(),
            "stub": node.stub,
            "content": node.content,
            "expires_at": None,
        }
        return {
            "versions": [version],
            "total_versions": 1,
            "has_more": False,
            "offset": 0,
        }

    def similar(self, memory_id: uuid.UUID, tenant_id: str) -> dict:
        """Tenant-filtered similar-memories lookup.

        Mimics the real get_similar_memories_service: the source is
        loaded tenant-scoped (cross-tenant source → NotFound), and
        the candidate pool is restricted to the source's (owner, scope,
        tenant) so no cross-tenant bleed can occur even theoretically.
        """
        source = self.memories.get(memory_id)
        if source is None or source.tenant_id != tenant_id:
            raise MemoryNotFoundError(memory_id)
        candidates = [
            {"id": str(m.id), "stub": m.stub, "score": 0.9}
            for m in self.memories.values()
            if m.id != source.id
            and m.owner_id == source.owner_id
            and m.scope == source.scope
            and m.tenant_id == source.tenant_id
        ]
        return {
            "results": candidates,
            "total": len(candidates),
            "has_more": False,
        }

    def get_relationships(self, node_id: uuid.UUID, tenant_id: str) -> list:
        """Tenant-filtered relationship lookup. Starting node must be
        in the caller's tenant (Phase 4 _fetch_current_node tenant-
        filters), else MemoryNotFoundError."""
        source = self.memories.get(node_id)
        if source is None or source.tenant_id != tenant_id:
            raise MemoryNotFoundError(node_id)
        return [
            r
            for r in self.relationships
            if r["tenant_id"] == tenant_id
            and (r["source_id"] == node_id or r["target_id"] == node_id)
        ]


def _make_node(
    *,
    content: str,
    owner_id: str,
    tenant_id: str,
    scope: str = "user",
    parent_id: uuid.UUID | None = None,
    version: int = 1,
) -> MemoryNodeRead:
    """Construct a MemoryNodeRead for use in the fake store."""
    now = _dt.datetime.now(_dt.UTC)
    return MemoryNodeRead(
        id=uuid.uuid4(),
        parent_id=parent_id,
        content=content,
        stub=content[:80],
        storage_type=StorageType.INLINE,
        content_ref=None,
        weight=0.9,
        scope=MemoryScope(scope),
        branch_type=None,
        owner_id=owner_id,
        tenant_id=tenant_id,
        is_current=True,
        version=version,
        previous_version_id=None,
        metadata=None,
        created_at=now,
        updated_at=now,
        expires_at=None,
        has_children=False,
        has_rationale=False,
        branch_count=0,
    )


# ---------------------------------------------------------------------------
# Claim fixtures
# ---------------------------------------------------------------------------


TENANT_A = "tenant_a"
TENANT_B = "tenant_b"

CLAIMS_A_USER_A = {
    "sub": "user_a",
    "identity_type": "user",
    "tenant_id": TENANT_A,
    "scopes": [
        "memory:read",
        "memory:write",
        "memory:read:user",
        "memory:write:user",
    ],
}

CLAIMS_B_USER_B = {
    "sub": "user_b",
    "identity_type": "user",
    "tenant_id": TENANT_B,
    "scopes": [
        "memory:read",
        "memory:write",
        "memory:read:user",
        "memory:write:user",
    ],
}

# Claims for a second user in tenant A (same tenant, different owner).
CLAIMS_A_USER_OTHER = {
    "sub": "user_a_other",
    "identity_type": "user",
    "tenant_id": TENANT_A,
    "scopes": [
        "memory:read",
        "memory:write",
        "memory:read:user",
        "memory:write:user",
    ],
}


# ---------------------------------------------------------------------------
# Shared patch helpers
# ---------------------------------------------------------------------------


def _mock_session():
    return MagicMock(), AsyncMock()


def _mock_create_memory_factory(store: FakeMemoryStore):
    """Build an AsyncMock that populates the store on each call and
    returns the same (memory, curation) shape as the real service."""

    async def _fake(data, session, embedding_service, *, tenant_id, skip_curation=False):
        node = _make_node(
            content=data.content,
            owner_id=data.owner_id,
            tenant_id=tenant_id,
            scope=data.scope.value if hasattr(data.scope, "value") else data.scope,
            parent_id=data.parent_id,
        )
        store.add(node)
        curation = {
            "blocked": False,
            "reason": None,
            "detail": None,
            "similar_count": 0,
            "nearest_id": None,
            "nearest_score": None,
            "flags": [],
        }
        return node, curation

    return AsyncMock(side_effect=_fake)


# ===========================================================================
# write_memory + read_memory — cross-tenant and same-tenant
# ===========================================================================


@pytest.mark.asyncio
async def test_write_as_a_read_as_b_returns_not_found():
    """Phase 5 (#46): a write from tenant A followed by a read from
    tenant B must return a "not found" error — cross-tenant reads are
    indistinguishable from nonexistent rows."""
    from src.tools.read_memory import read_memory
    from src.tools.write_memory import write_memory

    store = FakeMemoryStore()
    mock_session, mock_gen = _mock_session()
    fake_create = _mock_create_memory_factory(store)

    # 1) Write as tenant A.
    with (
        patch(
            "src.tools.write_memory.get_claims_from_context",
            return_value=CLAIMS_A_USER_A,
        ),
        patch(
            "src.tools.write_memory.get_db_session",
            return_value=(mock_session, mock_gen),
        ),
        patch(
            "src.tools.write_memory.release_db_session",
            new_callable=AsyncMock,
        ),
        patch(
            "src.tools.write_memory.get_embedding_service",
            return_value=MagicMock(),
        ),
        patch("src.tools.write_memory.create_memory", new=fake_create),
        patch(
            "src.tools.write_memory.broadcast_after_write",
            new_callable=AsyncMock,
        ),
    ):
        write_result = await write_memory(
            content="secret tenant A data",
            scope="user",
            owner_id="user_a",
        )

    assert write_result.get("error") is not True, write_result
    memory_id = write_result["memory"]["id"]

    # 2) Read as tenant B — must fail with "not found".
    async def _fake_read(mid, session, *, tenant_id):
        return store.read(mid, tenant_id)

    with (
        patch(
            "src.tools.read_memory.get_claims_from_context",
            return_value=CLAIMS_B_USER_B,
        ),
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
            new=AsyncMock(side_effect=_fake_read),
        ),
        pytest.raises(ToolError, match="(?i)not found"),
    ):
        await read_memory(memory_id=memory_id)


@pytest.mark.asyncio
async def test_same_tenant_write_read_roundtrip_works():
    """Baseline: a write from tenant A followed by a read from tenant A
    (same owner) succeeds and returns the stored memory."""
    from src.tools.read_memory import read_memory
    from src.tools.write_memory import write_memory

    store = FakeMemoryStore()
    mock_session, mock_gen = _mock_session()
    fake_create = _mock_create_memory_factory(store)

    with (
        patch(
            "src.tools.write_memory.get_claims_from_context",
            return_value=CLAIMS_A_USER_A,
        ),
        patch(
            "src.tools.write_memory.get_db_session",
            return_value=(mock_session, mock_gen),
        ),
        patch(
            "src.tools.write_memory.release_db_session",
            new_callable=AsyncMock,
        ),
        patch(
            "src.tools.write_memory.get_embedding_service",
            return_value=MagicMock(),
        ),
        patch("src.tools.write_memory.create_memory", new=fake_create),
        patch(
            "src.tools.write_memory.broadcast_after_write",
            new_callable=AsyncMock,
        ),
    ):
        write_result = await write_memory(
            content="tenant A own memory",
            scope="user",
            owner_id="user_a",
        )
    assert write_result.get("error") is not True
    memory_id = write_result["memory"]["id"]

    async def _fake_read(mid, session, *, tenant_id):
        return store.read(mid, tenant_id)

    with (
        patch(
            "src.tools.read_memory.get_claims_from_context",
            return_value=CLAIMS_A_USER_A,
        ),
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
            new=AsyncMock(side_effect=_fake_read),
        ),
    ):
        read_result = await read_memory(memory_id=memory_id)

    assert read_result.get("error") is not True, read_result
    assert read_result["content"] == "tenant A own memory"
    assert read_result["tenant_id"] == TENANT_A


# ===========================================================================
# write_memory + search_memory — cross-tenant and same-tenant
# ===========================================================================


@pytest.mark.asyncio
async def test_search_as_b_does_not_see_a_memories():
    """Phase 5 (#46): memories written by tenant A must be invisible to
    searches from tenant B. Tenant B's search returns empty rather than
    leaking A's content."""
    from src.tools.search_memory import search_memory
    from src.tools.write_memory import write_memory

    store = FakeMemoryStore()
    mock_session, mock_gen = _mock_session()
    fake_create = _mock_create_memory_factory(store)

    # Write two memories as tenant A.
    with (
        patch(
            "src.tools.write_memory.get_claims_from_context",
            return_value=CLAIMS_A_USER_A,
        ),
        patch(
            "src.tools.write_memory.get_db_session",
            return_value=(mock_session, mock_gen),
        ),
        patch(
            "src.tools.write_memory.release_db_session",
            new_callable=AsyncMock,
        ),
        patch(
            "src.tools.write_memory.get_embedding_service",
            return_value=MagicMock(),
        ),
        patch("src.tools.write_memory.create_memory", new=fake_create),
        patch(
            "src.tools.write_memory.broadcast_after_write",
            new_callable=AsyncMock,
        ),
    ):
        await write_memory(
            content="tenant A prefers podman",
            scope="user",
            owner_id="user_a",
        )
        await write_memory(
            content="tenant A uses FastAPI",
            scope="user",
            owner_id="user_a",
        )
    assert len([m for m in store.memories.values() if m.tenant_id == TENANT_A]) == 2

    # Fake service calls that the search tool uses.
    async def _fake_search(
        query, session, embedding_service, *, tenant_id, **kwargs
    ):
        return store.search(tenant_id=tenant_id, owner_id=kwargs.get("owner_id"))

    async def _fake_count(session, *, tenant_id, **kwargs):
        return len(store.search(tenant_id=tenant_id, owner_id=kwargs.get("owner_id")))

    # Tenant B searches: must get zero results.
    with (
        patch(
            "src.tools.search_memory.get_claims_from_context",
            return_value=CLAIMS_B_USER_B,
        ),
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
            return_value=AsyncMock(),
        ),
        patch(
            "src.tools.search_memory.search_memories",
            new=AsyncMock(side_effect=_fake_search),
        ),
        patch(
            "src.tools.search_memory.count_search_matches",
            new=AsyncMock(side_effect=_fake_count),
        ),
    ):
        b_result = await search_memory(query="preferences")

    assert b_result["total_matching"] == 0
    assert b_result["results"] == []
    # The empty-results branch of the tool adds a human-readable message.
    assert "No memories found" in b_result["message"]


@pytest.mark.asyncio
async def test_search_as_a_finds_own_memories():
    """Baseline: tenant A searches and sees its own memories."""
    from src.tools.search_memory import search_memory
    from src.tools.write_memory import write_memory

    store = FakeMemoryStore()
    mock_session, mock_gen = _mock_session()
    fake_create = _mock_create_memory_factory(store)

    with (
        patch(
            "src.tools.write_memory.get_claims_from_context",
            return_value=CLAIMS_A_USER_A,
        ),
        patch(
            "src.tools.write_memory.get_db_session",
            return_value=(mock_session, mock_gen),
        ),
        patch(
            "src.tools.write_memory.release_db_session",
            new_callable=AsyncMock,
        ),
        patch(
            "src.tools.write_memory.get_embedding_service",
            return_value=MagicMock(),
        ),
        patch("src.tools.write_memory.create_memory", new=fake_create),
        patch(
            "src.tools.write_memory.broadcast_after_write",
            new_callable=AsyncMock,
        ),
    ):
        await write_memory(
            content="tenant A own content",
            scope="user",
            owner_id="user_a",
        )

    async def _fake_search(
        query, session, embedding_service, *, tenant_id, **kwargs
    ):
        return store.search(tenant_id=tenant_id, owner_id=kwargs.get("owner_id"))

    async def _fake_count(session, *, tenant_id, **kwargs):
        return len(store.search(tenant_id=tenant_id, owner_id=kwargs.get("owner_id")))

    with (
        patch(
            "src.tools.search_memory.get_claims_from_context",
            return_value=CLAIMS_A_USER_A,
        ),
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
            return_value=AsyncMock(),
        ),
        patch(
            "src.tools.search_memory.search_memories",
            new=AsyncMock(side_effect=_fake_search),
        ),
        patch(
            "src.tools.search_memory.count_search_matches",
            new=AsyncMock(side_effect=_fake_count),
        ),
    ):
        a_result = await search_memory(query="anything")

    assert a_result["total_matching"] == 1
    assert len(a_result["results"]) == 1
    assert a_result["results"][0]["tenant_id"] == TENANT_A


# ===========================================================================
# update_memory cross-tenant
# ===========================================================================


@pytest.mark.asyncio
async def test_update_as_b_fails_on_tenant_a_memory():
    """Phase 5 (#46): a tenant-B caller trying to update a tenant-A
    memory must fail at the read_memory lookup inside update_memory
    (the tenant filter short-circuits before the write path is even
    reached)."""
    from fastmcp.exceptions import ToolError

    from src.tools.update_memory import update_memory
    from src.tools.write_memory import write_memory

    store = FakeMemoryStore()
    mock_session, mock_gen = _mock_session()
    fake_create = _mock_create_memory_factory(store)

    with (
        patch(
            "src.tools.write_memory.get_claims_from_context",
            return_value=CLAIMS_A_USER_A,
        ),
        patch(
            "src.tools.write_memory.get_db_session",
            return_value=(mock_session, mock_gen),
        ),
        patch(
            "src.tools.write_memory.release_db_session",
            new_callable=AsyncMock,
        ),
        patch(
            "src.tools.write_memory.get_embedding_service",
            return_value=MagicMock(),
        ),
        patch("src.tools.write_memory.create_memory", new=fake_create),
        patch(
            "src.tools.write_memory.broadcast_after_write",
            new_callable=AsyncMock,
        ),
    ):
        write_result = await write_memory(
            content="original content",
            scope="user",
            owner_id="user_a",
        )
    memory_id = write_result["memory"]["id"]

    async def _fake_read(mid, session, *, tenant_id):
        return store.read(mid, tenant_id)

    with (
        patch(
            "src.tools.update_memory.get_claims_from_context",
            return_value=CLAIMS_B_USER_B,
        ),
        patch(
            "src.tools.update_memory.get_db_session",
            return_value=(mock_session, mock_gen),
        ),
        patch(
            "src.tools.update_memory.release_db_session",
            new_callable=AsyncMock,
        ),
        patch(
            "src.tools.update_memory.get_embedding_service",
            return_value=MagicMock(),
        ),
        patch(
            "src.tools.update_memory._read_memory",
            new=AsyncMock(side_effect=_fake_read),
        ),
    ):
        with pytest.raises(ToolError, match="not found"):
            await update_memory(memory_id=memory_id, content="hacked content")


@pytest.mark.asyncio
async def test_update_as_same_tenant_succeeds():
    """Baseline: a same-tenant owner can update their own memory."""
    from src.tools.update_memory import update_memory
    from src.tools.write_memory import write_memory

    store = FakeMemoryStore()
    mock_session, mock_gen = _mock_session()
    fake_create = _mock_create_memory_factory(store)

    with (
        patch(
            "src.tools.write_memory.get_claims_from_context",
            return_value=CLAIMS_A_USER_A,
        ),
        patch(
            "src.tools.write_memory.get_db_session",
            return_value=(mock_session, mock_gen),
        ),
        patch(
            "src.tools.write_memory.release_db_session",
            new_callable=AsyncMock,
        ),
        patch(
            "src.tools.write_memory.get_embedding_service",
            return_value=MagicMock(),
        ),
        patch("src.tools.write_memory.create_memory", new=fake_create),
        patch(
            "src.tools.write_memory.broadcast_after_write",
            new_callable=AsyncMock,
        ),
    ):
        write_result = await write_memory(
            content="original content",
            scope="user",
            owner_id="user_a",
        )
    memory_id = write_result["memory"]["id"]

    async def _fake_read(mid, session, *, tenant_id):
        return store.read(mid, tenant_id)

    async def _fake_update(*, memory_id, data, session, embedding_service):
        old = store.memories[memory_id]
        new_version = _make_node(
            content=data.content or old.content,
            owner_id=old.owner_id,
            tenant_id=old.tenant_id,
            version=old.version + 1,
        )
        # Inherit id so downstream references stay consistent, but bump
        # the version. The real service creates a new row; the test only
        # cares about the output shape.
        new_version_dict = new_version.model_dump(mode="python")
        new_version_dict["previous_version_id"] = memory_id
        return MemoryNodeRead(**new_version_dict)

    with (
        patch(
            "src.tools.update_memory.get_claims_from_context",
            return_value=CLAIMS_A_USER_A,
        ),
        patch(
            "src.tools.update_memory.get_db_session",
            return_value=(mock_session, mock_gen),
        ),
        patch(
            "src.tools.update_memory.release_db_session",
            new_callable=AsyncMock,
        ),
        patch(
            "src.tools.update_memory.get_embedding_service",
            return_value=MagicMock(),
        ),
        patch(
            "src.tools.update_memory._read_memory",
            new=AsyncMock(side_effect=_fake_read),
        ),
        patch(
            "src.tools.update_memory.svc_update_memory",
            new=AsyncMock(side_effect=_fake_update),
        ),
        patch(
            "src.tools.update_memory.broadcast_after_write",
            new_callable=AsyncMock,
        ),
    ):
        result = await update_memory(memory_id=memory_id, content="revised")

    assert result["content"] == "revised"
    assert result["version"] == 2


# ===========================================================================
# delete_memory cross-tenant
# ===========================================================================


@pytest.mark.asyncio
async def test_delete_as_b_fails_on_tenant_a_memory():
    """Phase 5 (#46): tenant B cannot delete a tenant A memory. The
    read_memory lookup inside delete_memory tenant-filters, so the
    delete fails at the auth pre-check and never reaches the service
    delete path."""
    from fastmcp.exceptions import ToolError

    from src.tools.delete_memory import delete_memory
    from src.tools.write_memory import write_memory

    store = FakeMemoryStore()
    mock_session, mock_gen = _mock_session()
    fake_create = _mock_create_memory_factory(store)

    with (
        patch(
            "src.tools.write_memory.get_claims_from_context",
            return_value=CLAIMS_A_USER_A,
        ),
        patch(
            "src.tools.write_memory.get_db_session",
            return_value=(mock_session, mock_gen),
        ),
        patch(
            "src.tools.write_memory.release_db_session",
            new_callable=AsyncMock,
        ),
        patch(
            "src.tools.write_memory.get_embedding_service",
            return_value=MagicMock(),
        ),
        patch("src.tools.write_memory.create_memory", new=fake_create),
        patch(
            "src.tools.write_memory.broadcast_after_write",
            new_callable=AsyncMock,
        ),
    ):
        write_result = await write_memory(
            content="important data",
            scope="user",
            owner_id="user_a",
        )
    memory_id = write_result["memory"]["id"]

    async def _fake_read(mid, session, *, tenant_id):
        return store.read(mid, tenant_id)

    svc_delete = AsyncMock()

    with (
        patch(
            "src.tools.delete_memory.get_claims_from_context",
            return_value=CLAIMS_B_USER_B,
        ),
        patch(
            "src.tools.delete_memory.get_db_session",
            return_value=(mock_session, mock_gen),
        ),
        patch(
            "src.tools.delete_memory.release_db_session",
            new_callable=AsyncMock,
        ),
        patch(
            "src.tools.delete_memory._read_memory",
            new=AsyncMock(side_effect=_fake_read),
        ),
        patch("src.tools.delete_memory.svc_delete_memory", new=svc_delete),
        patch(
            "src.tools.delete_memory.broadcast_after_write",
            new_callable=AsyncMock,
        ),
    ):
        with pytest.raises(ToolError, match="not found"):
            await delete_memory(memory_id=memory_id)

    # The service-layer delete must NOT have been invoked: cross-tenant
    # reads short-circuit before the delete path is reached.
    svc_delete.assert_not_awaited()
    # And the memory is still in the store.
    assert memory_id in [str(m.id) for m in store.memories.values()]


# ===========================================================================
# get_memory_history cross-tenant
# ===========================================================================


@pytest.mark.asyncio
async def test_get_memory_history_as_b_fails_on_tenant_a_memory():
    """Phase 5 (#46): get_memory_history tenant-filters the entry-point
    read; tenant B sees "not found" for a tenant A memory, never its
    version chain."""
    from fastmcp.exceptions import ToolError

    from src.tools.get_memory_history import get_memory_history
    from src.tools.write_memory import write_memory

    store = FakeMemoryStore()
    mock_session, mock_gen = _mock_session()
    fake_create = _mock_create_memory_factory(store)

    with (
        patch(
            "src.tools.write_memory.get_claims_from_context",
            return_value=CLAIMS_A_USER_A,
        ),
        patch(
            "src.tools.write_memory.get_db_session",
            return_value=(mock_session, mock_gen),
        ),
        patch(
            "src.tools.write_memory.release_db_session",
            new_callable=AsyncMock,
        ),
        patch(
            "src.tools.write_memory.get_embedding_service",
            return_value=MagicMock(),
        ),
        patch("src.tools.write_memory.create_memory", new=fake_create),
        patch(
            "src.tools.write_memory.broadcast_after_write",
            new_callable=AsyncMock,
        ),
    ):
        write_result = await write_memory(
            content="tenant A initial",
            scope="user",
            owner_id="user_a",
        )
    memory_id = write_result["memory"]["id"]

    async def _fake_read(mid, session, *, tenant_id):
        return store.read(mid, tenant_id)

    async def _fake_history(mid, session, *, tenant_id, **kwargs):
        return store.history(mid, tenant_id)

    with (
        patch(
            "src.tools.get_memory_history.get_claims_from_context",
            return_value=CLAIMS_B_USER_B,
        ),
        patch(
            "src.tools.get_memory_history.get_db_session",
            return_value=(mock_session, mock_gen),
        ),
        patch(
            "src.tools.get_memory_history.release_db_session",
            new_callable=AsyncMock,
        ),
        patch(
            "src.tools.get_memory_history._read_memory",
            new=AsyncMock(side_effect=_fake_read),
        ),
        patch(
            "src.tools.get_memory_history._get_memory_history",
            new=AsyncMock(side_effect=_fake_history),
        ),
    ):
        with pytest.raises(ToolError, match="not found"):
            await get_memory_history(memory_id=memory_id)


@pytest.mark.asyncio
async def test_get_memory_history_same_tenant_succeeds():
    """Baseline: tenant A sees the version history of its own memory."""
    from src.tools.get_memory_history import get_memory_history
    from src.tools.write_memory import write_memory

    store = FakeMemoryStore()
    mock_session, mock_gen = _mock_session()
    fake_create = _mock_create_memory_factory(store)

    with (
        patch(
            "src.tools.write_memory.get_claims_from_context",
            return_value=CLAIMS_A_USER_A,
        ),
        patch(
            "src.tools.write_memory.get_db_session",
            return_value=(mock_session, mock_gen),
        ),
        patch(
            "src.tools.write_memory.release_db_session",
            new_callable=AsyncMock,
        ),
        patch(
            "src.tools.write_memory.get_embedding_service",
            return_value=MagicMock(),
        ),
        patch("src.tools.write_memory.create_memory", new=fake_create),
        patch(
            "src.tools.write_memory.broadcast_after_write",
            new_callable=AsyncMock,
        ),
    ):
        write_result = await write_memory(
            content="content for history",
            scope="user",
            owner_id="user_a",
        )
    memory_id = write_result["memory"]["id"]

    async def _fake_read(mid, session, *, tenant_id):
        return store.read(mid, tenant_id)

    async def _fake_history(mid, session, *, tenant_id, **kwargs):
        return store.history(mid, tenant_id)

    with (
        patch(
            "src.tools.get_memory_history.get_claims_from_context",
            return_value=CLAIMS_A_USER_A,
        ),
        patch(
            "src.tools.get_memory_history.get_db_session",
            return_value=(mock_session, mock_gen),
        ),
        patch(
            "src.tools.get_memory_history.release_db_session",
            new_callable=AsyncMock,
        ),
        patch(
            "src.tools.get_memory_history._read_memory",
            new=AsyncMock(side_effect=_fake_read),
        ),
        patch(
            "src.tools.get_memory_history._get_memory_history",
            new=AsyncMock(side_effect=_fake_history),
        ),
    ):
        result = await get_memory_history(memory_id=memory_id)

    assert result["total_versions"] == 1
    assert len(result["versions"]) == 1
    assert result["versions"][0]["content"] == "content for history"


# ===========================================================================
# create_relationship + get_relationships cross-tenant
# ===========================================================================


@pytest.mark.asyncio
async def test_get_relationships_cross_tenant_returns_not_found():
    """Phase 5 (#46): a relationship created by tenant A is invisible to
    tenant B's get_relationships call. The starting node lookup tenant-
    filters, so tenant B sees "not found" for the A node."""
    from src.tools.get_relationships import get_relationships
    from src.tools.write_memory import write_memory

    store = FakeMemoryStore()
    mock_session, mock_gen = _mock_session()
    fake_create = _mock_create_memory_factory(store)

    # Write two tenant-A memories and link them in the fake store.
    with (
        patch(
            "src.tools.write_memory.get_claims_from_context",
            return_value=CLAIMS_A_USER_A,
        ),
        patch(
            "src.tools.write_memory.get_db_session",
            return_value=(mock_session, mock_gen),
        ),
        patch(
            "src.tools.write_memory.release_db_session",
            new_callable=AsyncMock,
        ),
        patch(
            "src.tools.write_memory.get_embedding_service",
            return_value=MagicMock(),
        ),
        patch("src.tools.write_memory.create_memory", new=fake_create),
        patch(
            "src.tools.write_memory.broadcast_after_write",
            new_callable=AsyncMock,
        ),
    ):
        a1 = await write_memory(
            content="tenant A source", scope="user", owner_id="user_a"
        )
        a2 = await write_memory(
            content="tenant A target", scope="user", owner_id="user_a"
        )

    src_id = uuid.UUID(a1["memory"]["id"])
    tgt_id = uuid.UUID(a2["memory"]["id"])
    store.relationships.append(
        {
            "id": uuid.uuid4(),
            "tenant_id": TENANT_A,
            "source_id": src_id,
            "target_id": tgt_id,
            "relationship_type": "related_to",
        }
    )

    async def _fake_get_rels(
        node_id, session, *, tenant_id, relationship_type=None, direction="both"
    ):
        return store.get_relationships(node_id, tenant_id)

    # Tenant B asks for relationships of the tenant-A source → "not found".
    with (
        patch(
            "src.tools.get_relationships.get_claims_from_context",
            return_value=CLAIMS_B_USER_B,
        ),
        patch(
            "src.tools.get_relationships.get_db_session",
            return_value=(mock_session, mock_gen),
        ),
        patch(
            "src.tools.get_relationships.release_db_session",
            new_callable=AsyncMock,
        ),
        patch(
            "src.tools.get_relationships.get_relationships_service",
            new=AsyncMock(side_effect=_fake_get_rels),
        ),
    ):
        result = await get_relationships(node_id=str(src_id))

    assert result.get("error") is True
    assert "not found" in result["message"].lower()


@pytest.mark.asyncio
async def test_get_relationships_same_tenant_returns_edges():
    """Baseline: tenant A sees its own relationships."""
    from src.tools.get_relationships import get_relationships
    from src.tools.write_memory import write_memory

    store = FakeMemoryStore()
    mock_session, mock_gen = _mock_session()
    fake_create = _mock_create_memory_factory(store)

    with (
        patch(
            "src.tools.write_memory.get_claims_from_context",
            return_value=CLAIMS_A_USER_A,
        ),
        patch(
            "src.tools.write_memory.get_db_session",
            return_value=(mock_session, mock_gen),
        ),
        patch(
            "src.tools.write_memory.release_db_session",
            new_callable=AsyncMock,
        ),
        patch(
            "src.tools.write_memory.get_embedding_service",
            return_value=MagicMock(),
        ),
        patch("src.tools.write_memory.create_memory", new=fake_create),
        patch(
            "src.tools.write_memory.broadcast_after_write",
            new_callable=AsyncMock,
        ),
    ):
        a1 = await write_memory(
            content="source node", scope="user", owner_id="user_a"
        )
        a2 = await write_memory(
            content="target node", scope="user", owner_id="user_a"
        )
    src_id = uuid.UUID(a1["memory"]["id"])
    tgt_id = uuid.UUID(a2["memory"]["id"])

    # Build a relationship with populated source_node/target_node fields
    # that the tool's authorize_read post-filter will accept.
    source_node = store.memories[src_id]
    target_node = store.memories[tgt_id]
    fake_rel = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=TENANT_A,
        source_id=src_id,
        target_id=tgt_id,
        relationship_type="related_to",
    )
    fake_rel.model_dump = lambda mode="json": {
        "id": str(fake_rel.id),
        "tenant_id": TENANT_A,
        "source_id": str(src_id),
        "target_id": str(tgt_id),
        "relationship_type": "related_to",
        "source_node": {
            "scope": source_node.scope.value,
            "owner_id": source_node.owner_id,
            "tenant_id": source_node.tenant_id,
        },
        "target_node": {
            "scope": target_node.scope.value,
            "owner_id": target_node.owner_id,
            "tenant_id": target_node.tenant_id,
        },
    }

    async def _fake_get_rels(
        node_id, session, *, tenant_id, relationship_type=None, direction="both"
    ):
        # Same-tenant query: return one edge.
        return [fake_rel]

    with (
        patch(
            "src.tools.get_relationships.get_claims_from_context",
            return_value=CLAIMS_A_USER_A,
        ),
        patch(
            "src.tools.get_relationships.get_db_session",
            return_value=(mock_session, mock_gen),
        ),
        patch(
            "src.tools.get_relationships.release_db_session",
            new_callable=AsyncMock,
        ),
        patch(
            "src.tools.get_relationships.get_relationships_service",
            new=AsyncMock(side_effect=_fake_get_rels),
        ),
    ):
        result = await get_relationships(node_id=str(src_id))

    assert result.get("error") is not True
    assert result["count"] == 1


# ===========================================================================
# get_similar_memories cross-tenant
# ===========================================================================


@pytest.mark.asyncio
async def test_get_similar_memories_cross_tenant_returns_not_found():
    """Phase 5 (#46): a tenant-B caller targeting a tenant-A memory as
    the similarity source gets "not found" — the source lookup tenant-
    filters at the SQL level."""
    from src.tools.get_similar_memories import get_similar_memories
    from src.tools.write_memory import write_memory

    store = FakeMemoryStore()
    mock_session, mock_gen = _mock_session()
    fake_create = _mock_create_memory_factory(store)

    with (
        patch(
            "src.tools.write_memory.get_claims_from_context",
            return_value=CLAIMS_A_USER_A,
        ),
        patch(
            "src.tools.write_memory.get_db_session",
            return_value=(mock_session, mock_gen),
        ),
        patch(
            "src.tools.write_memory.release_db_session",
            new_callable=AsyncMock,
        ),
        patch(
            "src.tools.write_memory.get_embedding_service",
            return_value=MagicMock(),
        ),
        patch("src.tools.write_memory.create_memory", new=fake_create),
        patch(
            "src.tools.write_memory.broadcast_after_write",
            new_callable=AsyncMock,
        ),
    ):
        a1 = await write_memory(
            content="prefers podman over docker",
            scope="user",
            owner_id="user_a",
        )
    memory_id = a1["memory"]["id"]

    async def _fake_read(mid, session, *, tenant_id):
        return store.read(mid, tenant_id)

    async def _fake_similar(mid, session, *, tenant_id, **kwargs):
        return store.similar(mid, tenant_id)

    with (
        patch(
            "src.tools.get_similar_memories.get_claims_from_context",
            return_value=CLAIMS_B_USER_B,
        ),
        patch(
            "src.tools.get_similar_memories.get_db_session",
            return_value=(mock_session, mock_gen),
        ),
        patch(
            "src.tools.get_similar_memories.release_db_session",
            new_callable=AsyncMock,
        ),
        patch(
            "src.tools.get_similar_memories.read_memory_service",
            new=AsyncMock(side_effect=_fake_read),
        ),
        patch(
            "src.tools.get_similar_memories.get_similar_memories_service",
            new=AsyncMock(side_effect=_fake_similar),
        ),
        pytest.raises(ToolError, match="(?i)not found"),
    ):
        await get_similar_memories(memory_id=memory_id)


@pytest.mark.asyncio
async def test_get_similar_memories_does_not_see_cross_tenant_candidates():
    """Phase 5 (#46): the pipeline's curation similarity check must be
    tenant-scoped. If tenant A and tenant B both write the same content
    under the same owner_id and scope, tenant A's candidate pool must
    not include tenant B's memory. This is the last-mile curation
    invariant from Phase 4c."""
    from src.tools.get_similar_memories import get_similar_memories
    from src.tools.write_memory import write_memory

    store = FakeMemoryStore()
    mock_session, mock_gen = _mock_session()
    fake_create = _mock_create_memory_factory(store)

    # Write two "similar" memories in tenant A (same owner).
    with (
        patch(
            "src.tools.write_memory.get_claims_from_context",
            return_value=CLAIMS_A_USER_A,
        ),
        patch(
            "src.tools.write_memory.get_db_session",
            return_value=(mock_session, mock_gen),
        ),
        patch(
            "src.tools.write_memory.release_db_session",
            new_callable=AsyncMock,
        ),
        patch(
            "src.tools.write_memory.get_embedding_service",
            return_value=MagicMock(),
        ),
        patch("src.tools.write_memory.create_memory", new=fake_create),
        patch(
            "src.tools.write_memory.broadcast_after_write",
            new_callable=AsyncMock,
        ),
    ):
        a1 = await write_memory(
            content="prefers dark mode",
            scope="user",
            owner_id="user_a",
        )
        await write_memory(
            content="prefers dark mode in editor",
            scope="user",
            owner_id="user_a",
        )

    # And write one look-alike in tenant B, also under owner "user_a"
    # (same owner_id string, different tenant — this is the scenario
    # where tenant scoping earns its keep).
    with (
        patch(
            "src.tools.write_memory.get_claims_from_context",
            return_value={**CLAIMS_B_USER_B, "sub": "user_a"},
        ),
        patch(
            "src.tools.write_memory.get_db_session",
            return_value=(mock_session, mock_gen),
        ),
        patch(
            "src.tools.write_memory.release_db_session",
            new_callable=AsyncMock,
        ),
        patch(
            "src.tools.write_memory.get_embedding_service",
            return_value=MagicMock(),
        ),
        patch("src.tools.write_memory.create_memory", new=fake_create),
        patch(
            "src.tools.write_memory.broadcast_after_write",
            new_callable=AsyncMock,
        ),
    ):
        await write_memory(
            content="prefers dark mode everywhere",
            scope="user",
            owner_id="user_a",
        )

    # Now tenant A queries similar for its first memory. The A store
    # has two A-memories and one B-memory. The fake store's `similar()`
    # filters by tenant AND by source owner/scope, so the B memory
    # should be excluded.
    async def _fake_read(mid, session, *, tenant_id):
        return store.read(mid, tenant_id)

    async def _fake_similar(mid, session, *, tenant_id, **kwargs):
        return store.similar(mid, tenant_id)

    with (
        patch(
            "src.tools.get_similar_memories.get_claims_from_context",
            return_value=CLAIMS_A_USER_A,
        ),
        patch(
            "src.tools.get_similar_memories.get_db_session",
            return_value=(mock_session, mock_gen),
        ),
        patch(
            "src.tools.get_similar_memories.release_db_session",
            new_callable=AsyncMock,
        ),
        patch(
            "src.tools.get_similar_memories.read_memory_service",
            new=AsyncMock(side_effect=_fake_read),
        ),
        patch(
            "src.tools.get_similar_memories.get_similar_memories_service",
            new=AsyncMock(side_effect=_fake_similar),
        ),
    ):
        result = await get_similar_memories(memory_id=a1["memory"]["id"])

    # Tenant A's similar search should see exactly one similar candidate
    # (the second A memory), never the B memory.
    assert result.get("error") is not True
    assert result["total"] == 1
    similar_ids = {item["id"] for item in result["results"]}
    # Every returned id must belong to a tenant-A memory.
    for sid in similar_ids:
        matched = next(
            m for m in store.memories.values() if str(m.id) == sid
        )
        assert matched.tenant_id == TENANT_A


# ===========================================================================
# report_contradiction cross-tenant
# ===========================================================================


@pytest.mark.asyncio
async def test_report_contradiction_cross_tenant_fails():
    """Phase 5 (#46): tenant B cannot report a contradiction against a
    tenant A memory. The read_memory lookup inside report_contradiction
    tenant-filters, so the call fails at "not found" before ever
    inserting a contradiction report."""
    from fastmcp.exceptions import ToolError

    from src.tools.report_contradiction import report_contradiction
    from src.tools.write_memory import write_memory

    store = FakeMemoryStore()
    mock_session, mock_gen = _mock_session()
    fake_create = _mock_create_memory_factory(store)

    with (
        patch(
            "src.tools.write_memory.get_claims_from_context",
            return_value=CLAIMS_A_USER_A,
        ),
        patch(
            "src.tools.write_memory.get_db_session",
            return_value=(mock_session, mock_gen),
        ),
        patch(
            "src.tools.write_memory.release_db_session",
            new_callable=AsyncMock,
        ),
        patch(
            "src.tools.write_memory.get_embedding_service",
            return_value=MagicMock(),
        ),
        patch("src.tools.write_memory.create_memory", new=fake_create),
        patch(
            "src.tools.write_memory.broadcast_after_write",
            new_callable=AsyncMock,
        ),
    ):
        write_result = await write_memory(
            content="tenant A preference",
            scope="user",
            owner_id="user_a",
        )
    memory_id = write_result["memory"]["id"]

    async def _fake_read(mid, session, *, tenant_id):
        return store.read(mid, tenant_id)

    fake_svc_report = AsyncMock(return_value=1)

    with (
        patch(
            "src.tools.report_contradiction.get_claims_from_context",
            return_value=CLAIMS_B_USER_B,
        ),
        patch(
            "src.tools.report_contradiction.get_db_session",
            return_value=(mock_session, mock_gen),
        ),
        patch(
            "src.tools.report_contradiction.release_db_session",
            new_callable=AsyncMock,
        ),
        patch(
            "src.tools.report_contradiction._read_memory",
            new=AsyncMock(side_effect=_fake_read),
        ),
        patch(
            "src.tools.report_contradiction._report_contradiction",
            new=fake_svc_report,
        ),
    ):
        with pytest.raises(ToolError, match="not found"):
            await report_contradiction(
                memory_id=memory_id,
                observed_behavior="user used docker",
            )

    # The service must never be called — the cross-tenant read short-
    # circuits the whole path.
    fake_svc_report.assert_not_awaited()


@pytest.mark.asyncio
async def test_report_contradiction_same_tenant_succeeds():
    """Baseline: same-tenant owner can report a contradiction."""
    from src.tools.report_contradiction import report_contradiction
    from src.tools.write_memory import write_memory

    store = FakeMemoryStore()
    mock_session, mock_gen = _mock_session()
    fake_create = _mock_create_memory_factory(store)

    with (
        patch(
            "src.tools.write_memory.get_claims_from_context",
            return_value=CLAIMS_A_USER_A,
        ),
        patch(
            "src.tools.write_memory.get_db_session",
            return_value=(mock_session, mock_gen),
        ),
        patch(
            "src.tools.write_memory.release_db_session",
            new_callable=AsyncMock,
        ),
        patch(
            "src.tools.write_memory.get_embedding_service",
            return_value=MagicMock(),
        ),
        patch("src.tools.write_memory.create_memory", new=fake_create),
        patch(
            "src.tools.write_memory.broadcast_after_write",
            new_callable=AsyncMock,
        ),
    ):
        write_result = await write_memory(
            content="tenant A preference",
            scope="user",
            owner_id="user_a",
        )
    memory_id = write_result["memory"]["id"]

    async def _fake_read(mid, session, *, tenant_id):
        return store.read(mid, tenant_id)

    with (
        patch(
            "src.tools.report_contradiction.get_claims_from_context",
            return_value=CLAIMS_A_USER_A,
        ),
        patch(
            "src.tools.report_contradiction.get_db_session",
            return_value=(mock_session, mock_gen),
        ),
        patch(
            "src.tools.report_contradiction.release_db_session",
            new_callable=AsyncMock,
        ),
        patch(
            "src.tools.report_contradiction._read_memory",
            new=AsyncMock(side_effect=_fake_read),
        ),
        patch(
            "src.tools.report_contradiction._report_contradiction",
            new_callable=AsyncMock,
            return_value=1,
        ),
    ):
        result = await report_contradiction(
            memory_id=memory_id,
            observed_behavior="user used docker",
        )

    assert result["contradiction_count"] == 1
    assert result["memory_id"] == memory_id


# ===========================================================================
# set_curation_rule cross-tenant isolation
# ===========================================================================


@pytest.mark.asyncio
async def test_set_curation_rule_cross_tenant_name_collision_allowed():
    """Phase 5 (#46): both tenants may create a rule named "foo" —
    the uniqueness scope is per-tenant, so tenant B's rule with the
    same name as tenant A's does not collide. Phase 3 validated this
    at the service level; this test proves the tool layer passes the
    tenant filter through correctly."""
    from src.tools.set_curation_rule import set_curation_rule

    mock_session, mock_gen = _mock_session()

    # Build a create_rule stub that returns a fake CuratorRule row with
    # the fields needed by CuratorRuleRead.model_validate.
    def _make_fake_rule(tenant_id: str, name: str, owner_id: str):
        rule = MagicMock()
        rule.id = uuid.uuid4()
        rule.name = name
        rule.description = None
        rule.trigger = "on_write"
        rule.tier = "embedding"
        rule.config = {}
        rule.action = "flag"
        rule.scope_filter = None
        rule.layer = "user"
        rule.owner_id = owner_id
        rule.tenant_id = tenant_id
        rule.override = False
        rule.enabled = True
        rule.priority = 10
        rule.created_at = _dt.datetime.now(_dt.UTC)
        rule.updated_at = _dt.datetime.now(_dt.UTC)
        return rule

    created_tenants: list[str] = []

    async def _fake_create_rule(data, session, *, tenant_id):
        created_tenants.append(tenant_id)
        return _make_fake_rule(tenant_id, data.name, data.owner_id)

    # Both protected-rule and existing-user-rule lookups must return
    # None for each call (two calls per invocation → two side_effects).
    def _make_execute_side_effects():
        return [
            MagicMock(scalar_one_or_none=MagicMock(return_value=None)),
            MagicMock(scalar_one_or_none=MagicMock(return_value=None)),
        ]

    mock_session.execute = AsyncMock(
        side_effect=_make_execute_side_effects() + _make_execute_side_effects()
    )

    with (
        patch(
            "src.tools.set_curation_rule.get_claims_from_context",
            return_value=CLAIMS_A_USER_A,
        ),
        patch(
            "src.tools.set_curation_rule.get_db_session",
            return_value=(mock_session, mock_gen),
        ),
        patch(
            "src.tools.set_curation_rule.release_db_session",
            new_callable=AsyncMock,
        ),
        patch(
            "src.tools.set_curation_rule.create_rule",
            new=AsyncMock(side_effect=_fake_create_rule),
        ),
    ):
        result_a = await set_curation_rule(name="foo", config={"threshold": 0.95})

    assert result_a["created"] is True
    assert result_a["rule"]["tenant_id"] == TENANT_A

    with (
        patch(
            "src.tools.set_curation_rule.get_claims_from_context",
            return_value=CLAIMS_B_USER_B,
        ),
        patch(
            "src.tools.set_curation_rule.get_db_session",
            return_value=(mock_session, mock_gen),
        ),
        patch(
            "src.tools.set_curation_rule.release_db_session",
            new_callable=AsyncMock,
        ),
        patch(
            "src.tools.set_curation_rule.create_rule",
            new=AsyncMock(side_effect=_fake_create_rule),
        ),
    ):
        result_b = await set_curation_rule(name="foo", config={"threshold": 0.90})

    assert result_b["created"] is True
    assert result_b["rule"]["tenant_id"] == TENANT_B
    # Both tenants should have been recorded — they don't collide.
    assert set(created_tenants) == {TENANT_A, TENANT_B}


# ===========================================================================
# Assertion: cross-tenant "not found" leaks no tenant-identifying info
# ===========================================================================


@pytest.mark.asyncio
async def test_cross_tenant_error_does_not_mention_tenant():
    """Phase 4 decision: cross-tenant reads must look indistinguishable
    from "does not exist". The error message must not mention the word
    "tenant" or include any tenant_id value, otherwise the caller could
    infer that the ID exists in some other tenant."""
    from src.tools.read_memory import read_memory
    from src.tools.write_memory import write_memory

    store = FakeMemoryStore()
    mock_session, mock_gen = _mock_session()
    fake_create = _mock_create_memory_factory(store)

    with (
        patch(
            "src.tools.write_memory.get_claims_from_context",
            return_value=CLAIMS_A_USER_A,
        ),
        patch(
            "src.tools.write_memory.get_db_session",
            return_value=(mock_session, mock_gen),
        ),
        patch(
            "src.tools.write_memory.release_db_session",
            new_callable=AsyncMock,
        ),
        patch(
            "src.tools.write_memory.get_embedding_service",
            return_value=MagicMock(),
        ),
        patch("src.tools.write_memory.create_memory", new=fake_create),
        patch(
            "src.tools.write_memory.broadcast_after_write",
            new_callable=AsyncMock,
        ),
    ):
        write_result = await write_memory(
            content="sensitive A data",
            scope="user",
            owner_id="user_a",
        )
    memory_id = write_result["memory"]["id"]

    async def _fake_read(mid, session, *, tenant_id):
        return store.read(mid, tenant_id)

    with (
        patch(
            "src.tools.read_memory.get_claims_from_context",
            return_value=CLAIMS_B_USER_B,
        ),
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
            new=AsyncMock(side_effect=_fake_read),
        ),
        pytest.raises(ToolError) as exc_info,
    ):
        await read_memory(memory_id=memory_id)

    message = str(exc_info.value).lower()
    assert "not found" in message
    assert "tenant" not in message, (
        f"Cross-tenant error message leaks tenant wording: {message!r}"
    )
    assert TENANT_A.lower() not in message
    assert TENANT_B.lower() not in message

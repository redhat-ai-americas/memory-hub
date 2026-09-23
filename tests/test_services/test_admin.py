"""Tests for admin content moderation service operations (issue #45)."""

import uuid
from datetime import UTC, datetime

import pytest

from memoryhub_core.models.memory import MemoryNode
from memoryhub_core.services.admin import (
    hard_delete_memory,
    quarantine_memory,
    restore_memory,
    search_memory_admin,
)
from memoryhub_core.services.exceptions import MemoryNotFoundError


TENANT = "test-tenant"
ACTOR = "admin-agent-01"


def _make_memory(
    *,
    content: str = "test memory content",
    owner_id: str = "user-1",
    scope: str = "user",
    tenant_id: str = TENANT,
    status: str = "active",
    weight: float = 0.8,
) -> MemoryNode:
    now = datetime.now(UTC)
    memory_id = uuid.uuid4()
    return MemoryNode(
        id=memory_id,
        logical_id=memory_id,
        content=content,
        stub=content[:50],
        scope=scope,
        owner_id=owner_id,
        tenant_id=tenant_id,
        status=status,
        weight=weight,
        is_current=True,
        version=1,
        storage_type="inline",
        created_at=now,
        updated_at=now,
    )


class TestQuarantineMemory:
    @pytest.mark.asyncio
    async def test_quarantine_sets_status(self, async_session):
        node = _make_memory()
        async_session.add(node)
        await async_session.commit()

        result = await quarantine_memory(
            async_session,
            memory_id=node.id,
            tenant_id=TENANT,
            actor_id=ACTOR,
            reason="Suspected PII",
        )

        assert result["new_status"] == "quarantined"
        assert result["previous_status"] == "active"
        assert result["reason"] == "Suspected PII"

        # Verify in DB
        await async_session.refresh(node)
        assert node.status == "quarantined"

    @pytest.mark.asyncio
    async def test_quarantine_with_incident_reference(self, async_session):
        node = _make_memory()
        async_session.add(node)
        await async_session.commit()

        result = await quarantine_memory(
            async_session,
            memory_id=node.id,
            tenant_id=TENANT,
            actor_id=ACTOR,
            reason="Data spill",
            incident_reference="INC-2026-0042",
        )

        assert result["incident_reference"] == "INC-2026-0042"

    @pytest.mark.asyncio
    async def test_quarantine_nonexistent_raises(self, async_session):
        with pytest.raises(MemoryNotFoundError):
            await quarantine_memory(
                async_session,
                memory_id=uuid.uuid4(),
                tenant_id=TENANT,
                actor_id=ACTOR,
                reason="test",
            )

    @pytest.mark.asyncio
    async def test_quarantine_wrong_tenant_raises(self, async_session):
        node = _make_memory(tenant_id="other-tenant")
        async_session.add(node)
        await async_session.commit()

        with pytest.raises(MemoryNotFoundError):
            await quarantine_memory(
                async_session,
                memory_id=node.id,
                tenant_id=TENANT,
                actor_id=ACTOR,
                reason="test",
            )


class TestRestoreMemory:
    @pytest.mark.asyncio
    async def test_restore_quarantined_memory(self, async_session):
        node = _make_memory(status="quarantined")
        async_session.add(node)
        await async_session.commit()

        result = await restore_memory(
            async_session,
            memory_id=node.id,
            tenant_id=TENANT,
            actor_id=ACTOR,
            reason="Content reviewed, no issues",
        )

        assert result["new_status"] == "active"
        assert result["previous_status"] == "quarantined"

        await async_session.refresh(node)
        assert node.status == "active"

    @pytest.mark.asyncio
    async def test_restore_active_returns_error(self, async_session):
        node = _make_memory(status="active")
        async_session.add(node)
        await async_session.commit()

        result = await restore_memory(
            async_session,
            memory_id=node.id,
            tenant_id=TENANT,
            actor_id=ACTOR,
            reason="test",
        )

        assert "error" in result
        assert result["current_status"] == "active"

    @pytest.mark.asyncio
    async def test_restore_nonexistent_raises(self, async_session):
        with pytest.raises(MemoryNotFoundError):
            await restore_memory(
                async_session,
                memory_id=uuid.uuid4(),
                tenant_id=TENANT,
                actor_id=ACTOR,
                reason="test",
            )


class TestHardDeleteMemory:
    @pytest.mark.asyncio
    async def test_hard_delete_removes_row(self, async_session):
        node = _make_memory()
        async_session.add(node)
        await async_session.commit()
        node_id = node.id

        result = await hard_delete_memory(
            async_session,
            memory_id=node_id,
            tenant_id=TENANT,
            actor_id=ACTOR,
            reason="Cleanup",
        )

        assert result["memory_id"] == str(node_id)
        assert result["versions_deleted"] >= 1

        # Verify row is gone
        from sqlalchemy import select
        stmt = select(MemoryNode).where(MemoryNode.id == node_id)
        check = await async_session.execute(stmt)
        assert check.scalar_one_or_none() is None

    @pytest.mark.asyncio
    async def test_hard_delete_sanitized_audit(self, async_session):
        node = _make_memory(content="classified data here")
        async_session.add(node)
        await async_session.commit()

        result = await hard_delete_memory(
            async_session,
            memory_id=node.id,
            tenant_id=TENANT,
            actor_id=ACTOR,
            reason="Classified spill",
            incident_reference="INC-2026-0099",
            sanitized_audit=True,
        )

        assert result["sanitized_audit"] is True
        assert result["incident_reference"] == "INC-2026-0099"

    @pytest.mark.asyncio
    async def test_hard_delete_wrong_tenant_raises(self, async_session):
        node = _make_memory(tenant_id="other-tenant")
        async_session.add(node)
        await async_session.commit()

        with pytest.raises(MemoryNotFoundError):
            await hard_delete_memory(
                async_session,
                memory_id=node.id,
                tenant_id=TENANT,
                actor_id=ACTOR,
                reason="test",
            )

    @pytest.mark.asyncio
    async def test_hard_delete_nonexistent_raises(self, async_session):
        with pytest.raises(MemoryNotFoundError):
            await hard_delete_memory(
                async_session,
                memory_id=uuid.uuid4(),
                tenant_id=TENANT,
                actor_id=ACTOR,
                reason="test",
            )


class TestSearchMemoryAdmin:
    @pytest.mark.asyncio
    async def test_search_returns_active_and_quarantined(
        self, async_session, embedding_service,
    ):
        active = _make_memory(content="active memory about API keys")
        quarantined = _make_memory(
            content="quarantined memory about API keys",
            status="quarantined",
        )
        soft_deleted = _make_memory(
            content="soft deleted memory about API keys",
            status="soft_deleted",
        )
        async_session.add_all([active, quarantined, soft_deleted])
        await async_session.commit()

        results = await search_memory_admin(
            async_session,
            embedding_service,
            query="API keys",
            tenant_id=TENANT,
            actor_id=ACTOR,
        )

        # Default includes active + quarantined, NOT soft_deleted
        result_ids = {r["id"] for r in results}
        assert str(active.id) in result_ids
        assert str(quarantined.id) in result_ids
        assert str(soft_deleted.id) not in result_ids

    @pytest.mark.asyncio
    async def test_search_with_explicit_statuses(
        self, async_session, embedding_service,
    ):
        soft_deleted = _make_memory(
            content="soft deleted memory",
            status="soft_deleted",
        )
        async_session.add(soft_deleted)
        await async_session.commit()

        results = await search_memory_admin(
            async_session,
            embedding_service,
            query="soft deleted",
            tenant_id=TENANT,
            actor_id=ACTOR,
            include_statuses=["soft_deleted"],
        )

        result_ids = {r["id"] for r in results}
        assert str(soft_deleted.id) in result_ids

    @pytest.mark.asyncio
    async def test_search_tenant_isolation(
        self, async_session, embedding_service,
    ):
        other_tenant = _make_memory(
            content="other tenant memory",
            tenant_id="other-tenant",
        )
        async_session.add(other_tenant)
        await async_session.commit()

        results = await search_memory_admin(
            async_session,
            embedding_service,
            query="other tenant",
            tenant_id=TENANT,
            actor_id=ACTOR,
        )

        result_ids = {r["id"] for r in results}
        assert str(other_tenant.id) not in result_ids

    @pytest.mark.asyncio
    async def test_search_with_regex(
        self, async_session, embedding_service,
    ):
        match = _make_memory(content="Contains API_KEY=sk-12345 secret")
        no_match = _make_memory(content="No secrets here")
        async_session.add_all([match, no_match])
        await async_session.commit()

        results = await search_memory_admin(
            async_session,
            embedding_service,
            query="secret",
            tenant_id=TENANT,
            actor_id=ACTOR,
            regex=r"API_KEY=\w+",
        )

        result_ids = {r["id"] for r in results}
        assert str(match.id) in result_ids
        assert str(no_match.id) not in result_ids

    @pytest.mark.asyncio
    async def test_search_invalid_regex_raises(
        self, async_session, embedding_service,
    ):
        with pytest.raises(ValueError, match="Invalid regex"):
            await search_memory_admin(
                async_session,
                embedding_service,
                query="test",
                tenant_id=TENANT,
                actor_id=ACTOR,
                regex="[invalid",
            )


class TestStatusFilterInDefaultQueries:
    """Verify that quarantined memories are invisible to normal queries."""

    @pytest.mark.asyncio
    async def test_quarantined_invisible_to_read(self, async_session):
        """read_memory should not return quarantined memories."""
        from memoryhub_core.services.memory import read_memory

        node = _make_memory(status="quarantined")
        async_session.add(node)
        await async_session.commit()

        with pytest.raises(MemoryNotFoundError):
            await read_memory(node.id, async_session, tenant_id=TENANT)

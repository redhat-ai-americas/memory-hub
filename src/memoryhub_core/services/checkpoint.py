"""Workflow checkpoint service -- durable key-value state for recurring agents."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from memoryhub_core.models.memory import MemoryNode
from memoryhub_core.models.schemas import MemoryNodeCreate, MemoryNodeRead
from memoryhub_core.services.embeddings import EmbeddingService
from memoryhub_core.services.memory import create_memory, node_to_read

logger = logging.getLogger(__name__)


async def upsert_checkpoint(
    workflow_name: str,
    state: dict[str, Any],
    session: AsyncSession,
    embedding_service: EmbeddingService,
    *,
    tenant_id: str,
    owner_id: str,
    scope: str = "user",
    scope_id: str | None = None,
) -> tuple[MemoryNodeRead, bool]:
    """Upsert checkpoint state for a workflow.

    Returns (memory, created) where created=True if a new checkpoint was
    created, False if an existing one was updated in-place.

    Args:
        workflow_name: Identifier for the workflow (stored in content field)
        state: State dictionary to persist (stored in metadata_ field)
        session: Database session
        embedding_service: Service for generating embeddings
        tenant_id: Tenant identifier
        owner_id: Owner identifier
        scope: Scope for the checkpoint (default: user)
        scope_id: Scope identifier for project/role scopes

    Returns:
        Tuple of (MemoryNodeRead, bool) where bool indicates if created (True)
        or updated (False).
    """
    # Query for existing checkpoint
    stmt = (
        select(MemoryNode)
        .where(
            MemoryNode.owner_id == owner_id,
            MemoryNode.branch_type == "checkpoint",
            MemoryNode.content == workflow_name,
            MemoryNode.scope == scope,
            MemoryNode.is_current.is_(True),
            MemoryNode.deleted_at.is_(None),
            MemoryNode.tenant_id == tenant_id,
        )
        .limit(1)
    )
    result = await session.execute(stmt)
    node = result.scalar_one_or_none()

    if node is not None:
        # Update existing checkpoint in-place
        node.metadata_ = state
        node.updated_at = datetime.now(UTC)
        await session.commit()
        await session.refresh(node)
        memory = node_to_read(node, has_children=False, has_rationale=False)
        return memory, False

    # Create new checkpoint
    data = MemoryNodeCreate(
        content=workflow_name,
        scope=scope,
        scope_id=scope_id,
        weight=0.3,
        owner_id=owner_id,
        branch_type="checkpoint",
        metadata=state,
    )
    memory, curation_result = await create_memory(
        data=data,
        session=session,
        embedding_service=embedding_service,
        tenant_id=tenant_id,
        skip_curation=True,
    )
    if memory is None:
        # Shouldn't happen with skip_curation=True, but guard anyway
        raise RuntimeError(
            f"Failed to create checkpoint for workflow '{workflow_name}'"
        )
    return memory, True


async def read_checkpoint(
    workflow_name: str,
    session: AsyncSession,
    *,
    tenant_id: str,
    owner_id: str,
    scope: str = "user",
) -> dict[str, Any] | None:
    """Read checkpoint state for a workflow.

    Args:
        workflow_name: Identifier for the workflow
        session: Database session
        tenant_id: Tenant identifier
        owner_id: Owner identifier
        scope: Scope for the checkpoint (default: user)

    Returns:
        State dictionary if found, None if no checkpoint exists.
    """
    stmt = (
        select(MemoryNode)
        .where(
            MemoryNode.owner_id == owner_id,
            MemoryNode.branch_type == "checkpoint",
            MemoryNode.content == workflow_name,
            MemoryNode.scope == scope,
            MemoryNode.is_current.is_(True),
            MemoryNode.deleted_at.is_(None),
            MemoryNode.tenant_id == tenant_id,
        )
        .limit(1)
    )
    result = await session.execute(stmt)
    node = result.scalar_one_or_none()

    if node is None:
        return None

    return node.metadata_

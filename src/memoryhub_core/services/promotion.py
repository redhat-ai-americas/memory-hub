"""Memory promotion service -- graduate memories to broader scopes."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from memoryhub_core.models.memory import MemoryNode
from memoryhub_core.models.schemas import (
    MemoryNodeCreate,
    MemoryNodeRead,
    RelationshipCreate,
)
from memoryhub_core.services.embeddings import EmbeddingService
from memoryhub_core.services.exceptions import MemoryNotFoundError
from memoryhub_core.services.graph import create_relationship
from memoryhub_core.services.memory import create_memory, read_memory

logger = logging.getLogger(__name__)

PROMOTION_ORDER = ["user", "project", "organizational", "enterprise"]


async def promote_memory(
    memory_id: uuid.UUID,
    target_scope: str,
    session: AsyncSession,
    embedding_service: EmbeddingService,
    *,
    tenant_id: str,
    promoted_by: str,
    target_scope_id: str | None = None,
    project_id: str | None = None,
) -> MemoryNodeRead:
    """Promote a memory from a narrower scope to a broader one.

    Creates a new memory at the target scope with the same content, weight,
    and domains as the source. The promoted memory is linked back to the
    source via a `derived_from` relationship. Skips curation since the
    source memory already passed curation once.

    Args:
        memory_id: Source memory to promote.
        target_scope: Target scope (project, organizational, enterprise).
        session: Database session.
        embedding_service: Embedding service for the new memory.
        tenant_id: Tenant ID for both source and promoted memory.
        promoted_by: User or agent performing the promotion.
        target_scope_id: Scope ID for the target (e.g., project ID for
            project scope). Required for project/role scopes.
        project_id: Project context for the promotion (used for authz).

    Returns:
        The newly promoted memory.

    Raises:
        MemoryNotFoundError: Source memory does not exist.
        ValueError: Invalid promotion direction (e.g., project -> user).
    """
    # Read source memory
    source = await read_memory(memory_id, session, tenant_id=tenant_id)

    # Validate promotion direction
    if source.scope not in PROMOTION_ORDER:
        raise ValueError(f"Cannot promote from scope '{source.scope}'")
    if target_scope not in PROMOTION_ORDER:
        raise ValueError(f"Invalid target scope '{target_scope}'")

    source_idx = PROMOTION_ORDER.index(source.scope)
    target_idx = PROMOTION_ORDER.index(target_scope)

    if source_idx >= target_idx:
        raise ValueError(
            f"Cannot promote from '{source.scope}' to '{target_scope}'. "
            f"Promotion must move to a broader scope."
        )

    # Create promoted memory
    now = datetime.now(UTC)
    promoted_metadata = source.metadata or {}
    promoted_metadata["promoted_from"] = {
        "source_id": str(source.id),
        "promoted_by": promoted_by,
        "promoted_at": now.isoformat(),
    }

    create_data = MemoryNodeCreate(
        content=source.content,
        scope=target_scope,
        scope_id=target_scope_id,
        weight=source.weight,
        owner_id=promoted_by,
        metadata=promoted_metadata,
        domains=source.domains,
        content_type=source.content_type,
    )

    promoted_memory, curation_result = await create_memory(
        data=create_data,
        session=session,
        embedding_service=embedding_service,
        tenant_id=tenant_id,
        skip_curation=True,
    )

    if promoted_memory is None:
        # Should never happen with skip_curation=True, but handle defensively
        raise RuntimeError(
            f"Promoted memory creation was blocked by curation: {curation_result}"
        )

    # Create derived_from relationship (promoted -> source)
    relationship_data = RelationshipCreate(
        source_id=promoted_memory.id,
        target_id=source.id,
        relationship_type="derived_from",
        created_by=promoted_by,
    )
    await create_relationship(relationship_data, session)

    return promoted_memory

"""Memory graduation service -- promote experiential memories to knowledge status."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from memoryhub_core.models.schemas import (
    MemoryNodeCreate,
    MemoryNodeRead,
    RelationshipCreate,
)
from memoryhub_core.services.embeddings import EmbeddingService
from memoryhub_core.services.graph import create_relationship
from memoryhub_core.services.memory import create_memory, read_memory

logger = logging.getLogger(__name__)


async def graduate_memory(
    memory_id: uuid.UUID,
    session: AsyncSession,
    embedding_service: EmbeddingService,
    *,
    tenant_id: str,
    graduated_by: str,
    evidence: str | None = None,
    reviewer_note: str | None = None,
    project_id: str | None = None,
) -> MemoryNodeRead:
    """Graduate an experiential memory to knowledge status.

    Creates a new knowledge-type memory with the same content, weight, scope,
    and domains as the source. The graduated memory is linked back to the
    source via a `derived_from` relationship. Optionally creates an evidence
    branch. Skips curation since the source memory already passed curation once.

    Args:
        memory_id: Source memory to graduate (must be experiential).
        session: Database session.
        embedding_service: Embedding service for the new memory.
        tenant_id: Tenant ID for both source and graduated memory.
        graduated_by: User or agent performing the graduation.
        evidence: Optional evidence content to attach as an evidence branch.
        reviewer_note: Optional reviewer note to include in graduation metadata.
        project_id: Project context for the graduation (used for authz).

    Returns:
        The newly graduated memory.

    Raises:
        MemoryNotFoundError: Source memory does not exist.
        ValueError: Source memory is not experiential.
    """
    # TODO: Phase 2 -- gate on memory:knowledge_curator role when capability-based roles exist

    # Read source memory
    source = await read_memory(memory_id, session, tenant_id=tenant_id)

    # Validate content type
    if source.content_type != "experiential":
        raise ValueError(
            f"Cannot graduate memory with content_type '{source.content_type}'. "
            f"Only experiential memories can be graduated to knowledge."
        )

    # Create graduated memory
    now = datetime.now(UTC)
    graduated_metadata = {
        "graduation": {
            "source_id": str(source.id),
            "graduated_by": graduated_by,
            "graduated_at": now.isoformat(),
        }
    }
    if reviewer_note:
        graduated_metadata["graduation"]["reviewer_note"] = reviewer_note

    create_data = MemoryNodeCreate(
        content=source.content,
        scope=source.scope,
        scope_id=source.scope_id,
        weight=source.weight,
        owner_id=source.owner_id,
        metadata=graduated_metadata,
        domains=source.domains,
        content_type="knowledge",
        upstream_trust_level=source.upstream_trust_level,
    )

    graduated_memory, curation_result = await create_memory(
        data=create_data,
        session=session,
        embedding_service=embedding_service,
        tenant_id=tenant_id,
        skip_curation=True,
    )

    if graduated_memory is None:
        # Should never happen with skip_curation=True, but handle defensively
        raise RuntimeError(
            f"Graduated memory creation was blocked by curation: {curation_result}"
        )

    # Create derived_from relationship (graduated -> source)
    relationship_data = RelationshipCreate(
        source_id=graduated_memory.id,
        target_id=source.id,
        relationship_type="derived_from",
        created_by=graduated_by,
    )
    await create_relationship(relationship_data, session)

    # Create evidence branch if provided
    if evidence:
        evidence_data = MemoryNodeCreate(
            content=evidence,
            scope=source.scope,
            scope_id=source.scope_id,
            weight=source.weight,
            owner_id=graduated_by,
            parent_id=graduated_memory.id,
            branch_type="evidence",
            content_type="knowledge",
        )
        await create_memory(
            data=evidence_data,
            session=session,
            embedding_service=embedding_service,
            tenant_id=tenant_id,
            skip_curation=True,
        )

    return graduated_memory

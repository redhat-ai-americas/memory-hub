"""Entity extraction service — find-or-create entities and MENTIONS relationships.

Provides deduplication, aliasing, and entity-memory linking for Phase 2 entity
extraction (#170). All functions are async and accept an explicit AsyncSession.
"""

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from memoryhub_core.models.memory import MemoryNode, MemoryRelationship
from memoryhub_core.models.schemas import MemoryNodeRead, RelationshipCreate, RelationshipRead
from memoryhub_core.models.utils import generate_stub
from memoryhub_core.services.embeddings import EmbeddingService
from memoryhub_core.services.exceptions import MemoryNotFoundError
from memoryhub_core.services.graph import create_relationship
from memoryhub_core.services.memory import node_to_read

logger = logging.getLogger(__name__)

# Valid entity types from the Phase 2 design
VALID_ENTITY_TYPES = frozenset({
    "person", "object", "location", "event", "organization",
})

# Similarity threshold for entity deduplication via vector search.
# Cosine distance < 0.08 (similarity > 0.92) is considered a match.
ENTITY_DEDUP_THRESHOLD = 0.08


async def find_or_create_entity(
    name: str,
    entity_type: str,
    session: AsyncSession,
    embedding_service: EmbeddingService,
    *,
    tenant_id: str,
    owner_id: str,
    aliases: list[str] | None = None,
    confidence: float = 1.0,
    extractor: str = "manual",
) -> tuple[MemoryNodeRead, bool]:
    """Find an existing entity node or create a new one.

    Returns (entity_node, was_created). Deduplication strategy:
    1. Exact match on lower(content) for this tenant+owner
    2. Vector similarity (cosine distance < 0.08) if no exact match

    If a match is found, merges any new aliases into the existing node's
    metadata_["aliases"] list. If no match, creates a new entity node with
    scope="entity" and branch_type=f"entity:{entity_type}".

    Raises ValueError for invalid entity_type.
    """
    if entity_type not in VALID_ENTITY_TYPES:
        raise ValueError(
            f"Invalid entity_type '{entity_type}'. "
            f"Must be one of: {', '.join(sorted(VALID_ENTITY_TYPES))}"
        )

    normalized_name = name.strip()
    if not normalized_name:
        raise ValueError("Entity name cannot be empty")

    # Step 1: Exact match on canonical name (case-insensitive)
    exact_stmt = select(MemoryNode).where(
        MemoryNode.scope == "entity",
        MemoryNode.tenant_id == tenant_id,
        MemoryNode.owner_id == owner_id,
        MemoryNode.deleted_at.is_(None),
        MemoryNode.is_current.is_(True),
    )
    # SQLAlchemy func.lower for portable case-insensitive comparison
    from sqlalchemy import func
    exact_stmt = exact_stmt.where(func.lower(MemoryNode.content) == normalized_name.lower())
    exact_stmt = exact_stmt.limit(1)
    result = await session.execute(exact_stmt)
    existing = result.scalar_one_or_none()

    if existing is not None:
        # Merge aliases if provided
        new_aliases = set(aliases or [])
        existing_aliases = set(existing.metadata_.get("aliases", []) if existing.metadata_ else [])
        merged_aliases = sorted(existing_aliases | new_aliases)
        if merged_aliases != sorted(existing_aliases):
            # Update metadata to include new aliases
            updated_metadata = existing.metadata_ or {}
            updated_metadata["aliases"] = merged_aliases
            existing.metadata_ = updated_metadata
            await session.commit()
            await session.refresh(existing)

        entity_read = node_to_read(existing, has_children=False, has_rationale=False)
        return entity_read, False

    # Step 2: Vector similarity search (if embedding service available)
    embedding = await embedding_service.embed(normalized_name)
    if embedding:
        # Query for entity nodes with similar embeddings
        try:
            distance_expr = MemoryNode.embedding.cosine_distance(embedding)
            vec_stmt = (
                select(MemoryNode, distance_expr.label("distance"))
                .where(
                    MemoryNode.scope == "entity",
                    MemoryNode.tenant_id == tenant_id,
                    MemoryNode.owner_id == owner_id,
                    MemoryNode.deleted_at.is_(None),
                    MemoryNode.is_current.is_(True),
                )
                .order_by(distance_expr)
                .limit(1)
            )
            vec_result = await session.execute(vec_stmt)
            row = vec_result.first()

            if row is not None:
                candidate, distance = row[0], float(row[1])
                if distance < ENTITY_DEDUP_THRESHOLD:
                    # Match found via similarity — merge aliases
                    new_aliases = set(aliases or [])
                    existing_aliases = set(
                        candidate.metadata_.get("aliases", []) if candidate.metadata_ else []
                    )
                    merged_aliases = sorted(existing_aliases | new_aliases | {normalized_name})
                    updated_metadata = candidate.metadata_ or {}
                    updated_metadata["aliases"] = merged_aliases
                    candidate.metadata_ = updated_metadata
                    await session.commit()
                    await session.refresh(candidate)

                    entity_read = node_to_read(candidate, has_children=False, has_rationale=False)
                    return entity_read, False
        except Exception:
            # pgvector not available or query failed — continue to create
            logger.debug(
                "Vector similarity search failed for entity '%s'; creating new node",
                normalized_name,
                exc_info=True,
            )

    # Step 3: No match — create new entity node
    now = datetime.now(UTC)
    entity_id = uuid.uuid4()

    stub = generate_stub(
        content=normalized_name,
        scope="entity",
        weight=0.6,
        branch_count=0,
        has_rationale=False,
    )

    metadata = {
        "aliases": aliases or [],
        "extraction_confidence": confidence,
        "extracted_by": extractor,
    }

    node = MemoryNode(
        id=entity_id,
        content=normalized_name,
        stub=stub,
        scope="entity",
        scope_id=None,
        branch_type=f"entity:{entity_type}",
        weight=0.6,
        owner_id=owner_id,
        tenant_id=tenant_id,
        parent_id=None,
        metadata_=metadata,
        domains=None,
        embedding=embedding,
        is_current=True,
        version=1,
        storage_type="inline",
        content_ref=None,
        created_at=now,
        updated_at=now,
    )

    session.add(node)
    await session.commit()
    await session.refresh(node)

    entity_read = node_to_read(node, has_children=False, has_rationale=False)
    return entity_read, True


async def create_mentions_relationship(
    memory_id: uuid.UUID,
    entity_id: uuid.UUID,
    session: AsyncSession,
    *,
    tenant_id: str,
    created_by: str = "system:entity_extraction",
    metadata: dict[str, Any] | None = None,
) -> RelationshipRead:
    """Create a MENTIONS edge: memory -> entity.

    Idempotent: if an active MENTIONS edge already exists between these nodes,
    returns it without error. Uses the create_relationship service for actual
    creation, catching IntegrityError for race conditions.

    Raises MemoryNotFoundError if either node does not exist.
    """
    # Check for existing active MENTIONS edge
    existing_stmt = select(MemoryRelationship).where(
        MemoryRelationship.source_id == memory_id,
        MemoryRelationship.target_id == entity_id,
        MemoryRelationship.relationship_type == "mentions",
        MemoryRelationship.valid_until.is_(None),
    )
    result = await session.execute(existing_stmt)
    existing = result.scalar_one_or_none()

    if existing is not None:
        # Idempotent — edge already exists, return it
        # Load stubs for the response
        mem_stmt = select(MemoryNode.stub).where(MemoryNode.id == memory_id)
        ent_stmt = select(MemoryNode.stub).where(MemoryNode.id == entity_id)
        mem_stub = (await session.execute(mem_stmt)).scalar_one_or_none()
        ent_stub = (await session.execute(ent_stmt)).scalar_one_or_none()

        return RelationshipRead(
            id=existing.id,
            source_id=existing.source_id,
            target_id=existing.target_id,
            relationship_type=existing.relationship_type,
            metadata_=existing.metadata_,
            created_at=existing.created_at,
            created_by=existing.created_by,
            tenant_id=existing.tenant_id,
            valid_from=existing.valid_from,
            valid_until=existing.valid_until,
            source_stub=mem_stub,
            target_stub=ent_stub,
        )

    # Create new MENTIONS edge via the graph service
    rel_create = RelationshipCreate(
        source_id=memory_id,
        target_id=entity_id,
        relationship_type="mentions",
        created_by=created_by,
        metadata=metadata,
    )

    try:
        return await create_relationship(rel_create, session)
    except IntegrityError as exc:
        # Race condition — another task created the edge between our check
        # and our insert. Rollback and re-query for the existing edge.
        await session.rollback()
        retry_stmt = select(MemoryRelationship).where(
            MemoryRelationship.source_id == memory_id,
            MemoryRelationship.target_id == entity_id,
            MemoryRelationship.relationship_type == "mentions",
            MemoryRelationship.valid_until.is_(None),
        )
        retry_result = await session.execute(retry_stmt)
        retry_edge = retry_result.scalar_one_or_none()

        if retry_edge is not None:
            # Load stubs for the response
            mem_stmt = select(MemoryNode.stub).where(MemoryNode.id == memory_id)
            ent_stmt = select(MemoryNode.stub).where(MemoryNode.id == entity_id)
            mem_stub = (await session.execute(mem_stmt)).scalar_one_or_none()
            ent_stub = (await session.execute(ent_stmt)).scalar_one_or_none()

            return RelationshipRead(
                id=retry_edge.id,
                source_id=retry_edge.source_id,
                target_id=retry_edge.target_id,
                relationship_type=retry_edge.relationship_type,
                metadata_=retry_edge.metadata_,
                created_at=retry_edge.created_at,
                created_by=retry_edge.created_by,
                tenant_id=retry_edge.tenant_id,
                valid_from=retry_edge.valid_from,
                valid_until=retry_edge.valid_until,
                source_stub=mem_stub,
                target_stub=ent_stub,
            )

        # Edge still doesn't exist after race — re-raise original error
        raise ValueError(
            f"Failed to create MENTIONS edge ({memory_id} -> {entity_id})"
        ) from exc


async def find_entities_by_names(
    names: list[str],
    session: AsyncSession,
    *,
    tenant_id: str,
    owner_id: str | None = None,
) -> list[uuid.UUID]:
    """Find entity node IDs matching any of the given names (case-insensitive).

    Used by entity-aware search to pre-filter candidate memories. Returns a
    list of entity IDs that match any of the provided names.
    """
    if not names:
        return []

    # Normalize names for case-insensitive matching
    lowered_names = [n.lower() for n in names if n.strip()]
    if not lowered_names:
        return []

    from sqlalchemy import func

    stmt = select(MemoryNode.id).where(
        MemoryNode.scope == "entity",
        MemoryNode.tenant_id == tenant_id,
        MemoryNode.deleted_at.is_(None),
        func.lower(MemoryNode.content).in_(lowered_names),
    )

    if owner_id is not None:
        stmt = stmt.where(MemoryNode.owner_id == owner_id)

    result = await session.execute(stmt)
    return [row[0] for row in result.all()]

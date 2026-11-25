"""Integrity and live-authority reads used before memory mutations."""

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from memoryhub_core.authorization.human import Access
from memoryhub_core.exceptions import MemoryAccessDeniedError
from memoryhub_core.models.memory import MemoryNode, MemoryRelationship
from memoryhub_core.queries.memories import current_children
from memoryhub_core.queries.projects import writable_by_human


class RelationshipBoundaryError(ValueError):
    """The affected graph contains a missing or cross-tenant endpoint."""


async def mutation_edges(db: AsyncSession, ids):
    # Inspect all touching edges, then reject tenant corruption. Filtering out
    # corrupt edges here would hide a boundary failure during mutation.
    return (
        (
            await db.execute(
                select(MemoryRelationship)
                .where(
                    MemoryRelationship.valid_until.is_(None),
                    or_(MemoryRelationship.source_id.in_(ids), MemoryRelationship.target_id.in_(ids)),
                )
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )


async def existing_relationship_sources(db: AsyncSession, ids, target_id, kind, tenant):
    return (
        (
            await db.execute(
                select(MemoryRelationship.source_id)
                .where(
                    MemoryRelationship.tenant_id == tenant,
                    MemoryRelationship.source_id.in_(ids),
                    MemoryRelationship.target_id == target_id,
                    MemoryRelationship.relationship_type == kind,
                    MemoryRelationship.valid_until.is_(None),
                )
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )


async def authorize_version_neighbors(db: AsyncSession, access: Access, node):
    children = await current_children(db, [node.id], None, lock=True)
    rels = await mutation_edges(db, [node.id])
    if any(rel.tenant_id != access.principal.tenant_id for rel in rels):
        raise RelationshipBoundaryError("Memory relationship boundary invalid")
    neighbor_ids = {rel.target_id if rel.source_id == node.id else rel.source_id for rel in rels}
    if node.parent_id:
        neighbor_ids.add(node.parent_id)
    if neighbor_ids:
        neighbors = (
            (
                await db.execute(
                    select(MemoryNode)
                    .where(
                        MemoryNode.id.in_(neighbor_ids),
                    )
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )
    else:
        neighbors = []
    if len(neighbors) != len(neighbor_ids):
        raise RelationshipBoundaryError("Memory relationship boundary invalid")
    for child in children:
        if not await writable_by_human(db, access, child):
            raise MemoryAccessDeniedError("Memory not found")
    for related in neighbors:
        # Core only re-points an existing MENTIONS edge to an entity when a
        # memory gets a new version. It does not edit the entity itself.
        # Requiring entity write here would block ordinary versioning because
        # entity nodes have their own managed scope.
        related_edges = [rel for rel in rels if related.id in (rel.source_id, rel.target_id)]
        entity_reference = (
            related.id != node.parent_id
            and related.scope == "entity"
            and related.tenant_id == access.principal.tenant_id
            and related.deleted_at is None
            and related.is_current
            and related.status == "active"
            and related_edges
            and all(
                rel.relationship_type == "mentions" and rel.source_id == node.id and rel.target_id == related.id
                for rel in related_edges
            )
        )
        if not entity_reference and not await writable_by_human(db, access, related):
            raise MemoryAccessDeniedError("Memory not found")

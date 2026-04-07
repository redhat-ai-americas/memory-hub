"""Graph relationship service — create, delete, traverse, and query graph edges.

All functions are async and accept an explicit AsyncSession. Relationships are
directed edges between memory nodes with a constrained type vocabulary.
"""

import uuid
from collections import deque

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from memoryhub_core.models.memory import MemoryNode, MemoryRelationship
from memoryhub_core.models.schemas import (
    MemoryNodeRead,
    RelationshipCreate,
    RelationshipRead,
)
from memoryhub_core.services.exceptions import MemoryNotFoundError, RelationshipNotFoundError
from memoryhub_core.services.memory import node_to_read

_MAX_DEPTH_CAP = 10
_MAX_HOPS_CAP = 5


async def create_relationship(
    data: RelationshipCreate,
    session: AsyncSession,
) -> RelationshipRead:
    """Create a directed edge between two current memory nodes.

    Raises MemoryNotFoundError if either node is missing or not current.
    Raises ValueError on duplicate edges (unique constraint violation).
    """
    source, target = await _fetch_both_nodes(data.source_id, data.target_id, session)

    rel = MemoryRelationship(
        id=uuid.uuid4(),
        source_id=data.source_id,
        target_id=data.target_id,
        relationship_type=data.relationship_type,
        created_by=data.created_by,
        metadata_=data.metadata,
    )
    session.add(rel)

    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise ValueError(
            f"Relationship ({data.source_id} --[{data.relationship_type}]--> "
            f"{data.target_id}) already exists"
        ) from exc

    await session.refresh(rel)
    return _relationship_to_read(rel, source_stub=source.stub, target_stub=target.stub)


async def delete_relationship(
    relationship_id: uuid.UUID,
    session: AsyncSession,
) -> None:
    """Delete a relationship by ID.

    Raises MemoryNotFoundError if the relationship does not exist.
    """
    stmt = select(MemoryRelationship).where(MemoryRelationship.id == relationship_id)
    result = await session.execute(stmt)
    rel = result.scalar_one_or_none()

    if rel is None:
        raise RelationshipNotFoundError(relationship_id)

    await session.delete(rel)
    await session.commit()


async def get_relationships(
    node_id: uuid.UUID,
    session: AsyncSession,
    relationship_type: str | None = None,
    direction: str = "both",
) -> list[RelationshipRead]:
    """Return all relationships for a node, with optional type and direction filters.

    direction: "outgoing" (source=node), "incoming" (target=node), or "both".
    """
    await _fetch_current_node(node_id, session)

    if direction == "outgoing":
        direction_filter = MemoryRelationship.source_id == node_id
    elif direction == "incoming":
        direction_filter = MemoryRelationship.target_id == node_id
    else:
        direction_filter = or_(
            MemoryRelationship.source_id == node_id,
            MemoryRelationship.target_id == node_id,
        )

    filters = [direction_filter]
    if relationship_type is not None:
        filters.append(MemoryRelationship.relationship_type == relationship_type)

    stmt = select(MemoryRelationship).where(and_(*filters))
    result = await session.execute(stmt)
    rels = result.scalars().all()

    if not rels:
        return []

    # Drop edges where either endpoint references a deleted memory.
    # The starting node was already verified live by _fetch_current_node above,
    # so this filter only excludes edges to dangling deleted neighbors.
    referenced_ids = {r.source_id for r in rels} | {r.target_id for r in rels}
    alive_ids = await _alive_node_ids(referenced_ids, session)
    rels = [r for r in rels if r.source_id in alive_ids and r.target_id in alive_ids]

    if not rels:
        return []

    stubs = await _load_stubs(referenced_ids, session)

    return [
        _relationship_to_read(r, source_stub=stubs.get(r.source_id), target_stub=stubs.get(r.target_id))
        for r in rels
    ]


async def get_subtree(
    node_id: uuid.UUID,
    session: AsyncSession,
    max_depth: int = 5,
) -> dict:
    """Return a node and all its parent_id-based descendants up to max_depth.

    Uses iterative level-by-level ORM queries (portable across PostgreSQL and
    SQLite) rather than a raw recursive CTE. For our shallow trees (3-4 levels
    max), this is equally efficient and avoids UUID format issues across backends.

    Returns:
      {"node": MemoryNodeRead, "children": [...], "total_nodes": int}
    """
    max_depth = min(max_depth, _MAX_DEPTH_CAP)

    # Verify the root exists
    root = await _fetch_current_node(node_id, session)

    # Collect all descendant nodes level by level
    nodes_by_id: dict[uuid.UUID, MemoryNode] = {root.id: root}
    depth_by_id: dict[uuid.UUID, int] = {root.id: 0}
    frontier = [root.id]

    for depth in range(1, max_depth + 1):
        if not frontier:
            break
        stmt = select(MemoryNode).where(
            and_(
                MemoryNode.parent_id.in_(frontier),
                MemoryNode.is_current.is_(True),
                MemoryNode.deleted_at.is_(None),
            )
        )
        result = await session.execute(stmt)
        children = result.scalars().all()
        frontier = []
        for child in children:
            nodes_by_id[child.id] = child
            depth_by_id[child.id] = depth
            frontier.append(child.id)

    # Build parent → children mapping
    children_by_parent: dict[uuid.UUID, list[uuid.UUID]] = {}
    for nid, node in nodes_by_id.items():
        if node.parent_id in nodes_by_id:
            children_by_parent.setdefault(node.parent_id, []).append(nid)

    def _build_subtree(nid: uuid.UUID) -> dict:
        node = nodes_by_id[nid]
        child_ids = children_by_parent.get(nid, [])
        has_rationale = any(
            nodes_by_id[c].branch_type == "rationale" for c in child_ids if c in nodes_by_id
        )
        node_read = node_to_read(node, has_children=bool(child_ids), has_rationale=has_rationale)
        child_entries = [_build_subtree(c) for c in child_ids if c in nodes_by_id]
        return {"node": node_read, "children": child_entries, "depth": depth_by_id[nid]}

    root_children = children_by_parent.get(node_id, [])
    has_rationale_root = any(
        nodes_by_id[c].branch_type == "rationale" for c in root_children if c in nodes_by_id
    )
    root_read = node_to_read(root, has_children=bool(root_children), has_rationale=has_rationale_root)

    return {
        "node": root_read,
        "children": [_build_subtree(c) for c in root_children if c in nodes_by_id],
        "total_nodes": len(nodes_by_id),
    }


async def trace_provenance(
    node_id: uuid.UUID,
    session: AsyncSession,
    max_hops: int = 10,
) -> list[dict]:
    """Follow derived_from edges backward from a node to trace its provenance.

    Edge convention: source=derived → target=origin. We follow source_id matches
    outward to target_id (the origin) at each hop.

    Returns a list of steps ordered by hop (ascending):
      [{"node": MemoryNodeRead, "relationship": RelationshipRead, "hop": int}]

    Stops when no more derived_from edges are found or max_hops is reached.
    """
    # Verify the starting node exists
    await _fetch_current_node(node_id, session)

    steps: list[dict] = []
    visited: set[uuid.UUID] = {node_id}
    current_id = node_id

    for hop in range(1, max_hops + 1):
        # Look for a derived_from edge where the current node is the source (derived side)
        stmt = select(MemoryRelationship).where(
            and_(
                MemoryRelationship.source_id == current_id,
                MemoryRelationship.relationship_type == "derived_from",
            )
        )
        result = await session.execute(stmt)
        rel = result.scalars().first()

        if rel is None:
            break

        # Follow the edge to the origin (target)
        origin_id = rel.target_id
        if origin_id in visited:
            break

        origin_node = await _fetch_node_by_id(origin_id, session)
        if origin_node is None:
            break

        visited.add(origin_id)
        origin_read = node_to_read(origin_node, has_children=False, has_rationale=False)
        rel_read = _relationship_to_read(rel, target_stub=origin_node.stub)

        steps.append({"node": origin_read, "relationship": rel_read, "hop": hop})
        current_id = origin_id

    return steps


async def find_related(
    node_id: uuid.UUID,
    session: AsyncSession,
    max_hops: int = 2,
    relationship_types: list[str] | None = None,
) -> list[dict]:
    """BFS traversal from node_id following edges up to max_hops.

    Returns:
      [{"node": MemoryNodeRead, "path": list[RelationshipRead], "distance": int}]

    Visited nodes are deduplicated; the starting node is not included in results.
    """
    max_hops = min(max_hops, _MAX_HOPS_CAP)

    # Verify root exists
    await _fetch_current_node(node_id, session)

    visited: set[uuid.UUID] = {node_id}
    # Queue entries: (current_node_id, path_so_far, distance)
    queue: deque[tuple[uuid.UUID, list[RelationshipRead], int]] = deque()
    queue.append((node_id, [], 0))
    results: list[dict] = []

    while queue:
        current_id, path, distance = queue.popleft()

        if distance >= max_hops:
            continue

        # Fetch all edges from/to current node
        filters = [
            or_(
                MemoryRelationship.source_id == current_id,
                MemoryRelationship.target_id == current_id,
            )
        ]
        if relationship_types:
            filters.append(MemoryRelationship.relationship_type.in_(relationship_types))

        stmt = select(MemoryRelationship).where(and_(*filters))
        rel_result = await session.execute(stmt)
        rels = rel_result.scalars().all()

        for rel in rels:
            neighbor_id = rel.target_id if rel.source_id == current_id else rel.source_id
            if neighbor_id in visited:
                continue

            visited.add(neighbor_id)
            neighbor_node = await _fetch_node_by_id(neighbor_id, session)
            if neighbor_node is None:
                continue

            neighbor_read = node_to_read(neighbor_node, has_children=False, has_rationale=False)
            rel_read = _relationship_to_read(
                rel,
                source_stub=neighbor_node.stub if rel.target_id == neighbor_id else None,
                target_stub=neighbor_node.stub if rel.source_id == neighbor_id else None,
            )
            new_path = path + [rel_read]
            results.append({"node": neighbor_read, "path": new_path, "distance": distance + 1})
            queue.append((neighbor_id, new_path, distance + 1))

    return results


# -- Internal helpers --


def _relationship_to_read(
    rel: MemoryRelationship,
    source_stub: str | None = None,
    target_stub: str | None = None,
) -> RelationshipRead:
    """Convert a MemoryRelationship ORM instance to a RelationshipRead schema."""
    return RelationshipRead(
        id=rel.id,
        source_id=rel.source_id,
        target_id=rel.target_id,
        relationship_type=rel.relationship_type,
        metadata_=rel.metadata_,
        created_at=rel.created_at,
        created_by=rel.created_by,
        source_stub=source_stub,
        target_stub=target_stub,
    )


async def _fetch_current_node(node_id: uuid.UUID, session: AsyncSession) -> MemoryNode:
    """Load a memory node by ID, requiring it to be current and not deleted.

    Raises MemoryNotFoundError if missing, superseded, or soft-deleted.
    """
    stmt = select(MemoryNode).where(
        and_(
            MemoryNode.id == node_id,
            MemoryNode.is_current.is_(True),
            MemoryNode.deleted_at.is_(None),
        )
    )
    result = await session.execute(stmt)
    node = result.scalar_one_or_none()
    if node is None:
        raise MemoryNotFoundError(node_id)
    return node


async def _fetch_node_by_id(node_id: uuid.UUID, session: AsyncSession) -> MemoryNode | None:
    """Load a memory node by ID regardless of is_current status, but excluding deleted.

    Returns None for missing or soft-deleted nodes. Used by traversal helpers
    (trace_provenance, find_related) where hitting a deleted memory should
    gracefully terminate the walk rather than raise.
    """
    stmt = select(MemoryNode).where(
        MemoryNode.id == node_id,
        MemoryNode.deleted_at.is_(None),
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def _fetch_both_nodes(
    source_id: uuid.UUID,
    target_id: uuid.UUID,
    session: AsyncSession,
) -> tuple[MemoryNode, MemoryNode]:
    """Load source and target nodes together; both must be current and not deleted."""
    stmt = select(MemoryNode).where(
        and_(
            MemoryNode.id.in_([source_id, target_id]),
            MemoryNode.is_current.is_(True),
            MemoryNode.deleted_at.is_(None),
        )
    )
    result = await session.execute(stmt)
    nodes = {n.id: n for n in result.scalars().all()}

    if source_id not in nodes:
        raise MemoryNotFoundError(source_id)
    if target_id not in nodes:
        raise MemoryNotFoundError(target_id)

    return nodes[source_id], nodes[target_id]


async def _load_stubs(
    node_ids: set[uuid.UUID],
    session: AsyncSession,
) -> dict[uuid.UUID, str]:
    """Return a mapping of node_id -> stub for the given IDs (excluding deleted)."""
    if not node_ids:
        return {}
    stmt = select(MemoryNode.id, MemoryNode.stub).where(
        MemoryNode.id.in_(node_ids),
        MemoryNode.deleted_at.is_(None),
    )
    result = await session.execute(stmt)
    return {row.id: row.stub for row in result.all()}


async def _alive_node_ids(
    node_ids: set[uuid.UUID],
    session: AsyncSession,
) -> set[uuid.UUID]:
    """Return the subset of node_ids that exist and are not deleted.

    Used by graph queries to drop edges that reference deleted memories.
    Edges to deleted memories are filtered out of relationship results so
    callers don't see broken pointers.
    """
    if not node_ids:
        return set()
    stmt = select(MemoryNode.id).where(
        MemoryNode.id.in_(node_ids),
        MemoryNode.deleted_at.is_(None),
    )
    result = await session.execute(stmt)
    return {row[0] for row in result.all()}

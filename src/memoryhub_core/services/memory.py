"""Core memory service — CRUD, versioning, search, and contradiction reporting.

This module sits between the MCP tools and the database. All methods are async
and receive an explicit AsyncSession (no hidden global state).
"""

from __future__ import annotations

import logging
import math
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import Integer, and_, func, or_, select, update
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from memoryhub_core.config import AppSettings
from memoryhub_core.models.contradiction import ContradictionReport
from memoryhub_core.models.memory import MemoryNode
from memoryhub_core.models.schemas import (
    MemoryNodeCreate,
    MemoryNodeRead,
    MemoryNodeStub,
    MemoryNodeUpdate,
    MemoryVersionInfo,
)
from memoryhub_core.models.utils import generate_stub
from memoryhub_core.services.curation.pipeline import run_curation_pipeline
from memoryhub_core.services.embeddings import EmbeddingService
from memoryhub_core.services.exceptions import (
    ContradictionNotFoundError,
    MemoryAlreadyDeletedError,
    MemoryNotCurrentError,
    MemoryNotFoundError,
)
from memoryhub_core.services.pattern import PatternSignal, detect_patterns
from memoryhub_core.services.rerank import (
    RERANK_POOL_SIZE,
    RerankerService,
    batched_rerank,
)
from memoryhub_core.storage.chunker import semantic_chunk
from memoryhub_core.storage.s3 import S3StorageAdapter

logger = logging.getLogger(__name__)


# Default RRF constant -- standard "k=60" from the original RRF paper.
# Used by both the production search path and the benchmark harness so
# the empirical and production behaviors stay aligned.
RRF_K = 60

# Default cosine distance threshold for the pivot signal. Cosine
# distance ranges 0..2; the design's research file recommended 0.55
# as a starting threshold. Surfaced as a parameter on
# search_memories_with_focus so callers can tune empirically without
# touching service code.
DEFAULT_PIVOT_THRESHOLD = 0.55

VALID_SIGNAL_NAMES = frozenset({"reranker", "focus", "keyword", "domain", "graph"})


async def create_memory(
    data: MemoryNodeCreate,
    session: AsyncSession,
    embedding_service: EmbeddingService,
    *,
    tenant_id: str,
    skip_curation: bool = False,
    force: bool = False,
    s3_adapter: S3StorageAdapter | None = None,
) -> tuple[MemoryNodeRead | None, dict]:
    """Create a new memory node.

    Generates the stub and embedding, runs the curation pipeline, and (if
    allowed) persists the node. Returns a ``(memory, curation_result)`` tuple:

    - If curation blocks the write: ``memory`` is ``None`` and
      ``curation_result["blocked"]`` is ``True``.
    - If the write is allowed: ``memory`` is the created ``MemoryNodeRead`` and
      ``curation_result["blocked"]`` is ``False``.

    Set ``skip_curation=True`` to bypass the pipeline entirely (used for
    downstream writes from merge operations).

    Set ``force=True`` to bypass similarity gate checks (near-duplicate and
    exact-duplicate). Tier 1 regex checks (secrets, PII) are still enforced.
    Use when the caller has already confirmed the write with the user after a
    gated response.

    ``tenant_id`` is a required keyword argument -- tool-layer callers must
    pass the caller's tenant (from JWT claims) explicitly so every insert is
    stamped with the correct tenant. Phase 2's authorize_write already
    verified the caller is allowed to write into this tenant; this function
    just persists that decision onto the row.

    Content exceeding the embedding model's context window is chunked into
    child nodes (``branch_type="chunk"``) for fine-grained search, and the
    parent embedding is truncated to fit the model's input limit. Chunks are
    search infrastructure: they help FIND the right memory, but search returns
    the parent (full content or stub), never raw chunks.

    Storage is independent: content exceeding ``s3_threshold_bytes`` goes to
    S3 (if configured), otherwise stays inline in PostgreSQL.
    """
    app_settings = AppSettings()
    content_bytes = len(data.content.encode("utf-8"))
    embedding_max_chars = app_settings.embedding_max_tokens * 4
    needs_chunking = len(data.content) > embedding_max_chars
    use_s3 = content_bytes > app_settings.s3_threshold_bytes and s3_adapter is not None

    embed_text = data.content[:embedding_max_chars] if needs_chunking else data.content
    embedding = await embedding_service.embed(embed_text)

    stub = generate_stub(
        content=data.content,
        scope=data.scope,
        weight=data.weight,
        branch_count=0,
        has_rationale=False,
    )

    if not skip_curation:
        curation_result = await run_curation_pipeline(
            content=data.content,
            embedding=embedding,
            owner_id=data.owner_id,
            scope=data.scope,
            session=session,
            tenant_id=tenant_id,
            force=force,
        )
        if curation_result["blocked"]:
            return None, curation_result
    else:
        curation_result = {
            "blocked": False,
            "reason": None,
            "detail": None,
            "similar_count": 0,
            "nearest_id": None,
            "nearest_score": None,
            "flags": [],
        }

    now = datetime.now(UTC)
    memory_id = uuid.uuid4()

    # Upload to S3 before DB commit so a failed upload doesn't leave a
    # dangling row. If the DB commit later fails, the S3 object becomes
    # orphaned (acceptable; cleaned up by periodic reaper).
    if use_s3:
        content_ref = await s3_adapter.put_content(
            tenant_id, memory_id, memory_id, data.content,
        )
        db_content = data.content[:app_settings.s3_prefix_chars]
        storage_type = "s3"
    else:
        content_ref = None
        db_content = data.content
        storage_type = "inline"

    # Mark extraction pending before commit so the status is visible immediately
    node_metadata = data.metadata
    if (
        app_settings.entity_extraction_enabled
        and data.scope != "entity"
    ):
        node_metadata = dict(node_metadata or {})
        node_metadata["extraction_status"] = "pending"

    node = MemoryNode(
        id=memory_id,
        content=db_content,
        stub=stub,
        scope=data.scope,
        scope_id=data.scope_id,
        weight=data.weight,
        owner_id=data.owner_id,
        actor_id=data.actor_id,
        driver_id=data.driver_id,
        tenant_id=tenant_id,
        parent_id=data.parent_id,
        branch_type=data.branch_type,
        metadata_=node_metadata,
        domains=data.domains,
        content_type=data.content_type,
        relevant_until=data.relevant_until,
        embedding=embedding,
        is_current=True,
        version=1,
        storage_type=storage_type,
        content_ref=content_ref,
        created_at=now,
        updated_at=now,
    )

    # Run temporal classifier when caller didn't set relevant_until explicitly.
    if node.relevant_until is None:
        from memoryhub_core.services.temporal import classify_temporal

        node.relevant_until = classify_temporal(data.content, now)

    session.add(node)
    await session.commit()
    await session.refresh(node)

    # Create semantic chunks for oversized memories so each section is
    # independently searchable via its own embedding. The parent is
    # already committed — if chunk creation fails, the memory still
    # exists (searchable via its prefix embedding) but without chunk
    # granularity.
    has_children = False
    if needs_chunking:
        try:
            has_children = await _create_chunk_children(
                content=data.content,
                parent_id=memory_id,
                scope=data.scope,
                scope_id=data.scope_id,
                owner_id=data.owner_id,
                tenant_id=tenant_id,
                domains=data.domains,
                embedding_service=embedding_service,
                session=session,
                now=now,
            )
        except Exception:
            logger.warning(
                "Failed to create chunks for oversized memory %s; "
                "memory is saved but only prefix is searchable",
                memory_id,
                exc_info=True,
            )

    # Trigger async entity extraction after the write is committed (#170 Phase 2)
    if (
        app_settings.entity_extraction_enabled
        and data.scope != "entity"
    ):
        from memoryhub_core.services.extraction_runner import trigger_extraction

        await trigger_extraction(
            memory_id=memory_id,
            content=data.content,
            tenant_id=tenant_id,
            owner_id=data.owner_id,
            embedding_service=embedding_service,
        )

    memory = node_to_read(node, has_children=has_children, has_rationale=False)
    return memory, curation_result


async def _create_chunk_children(
    *,
    content: str,
    parent_id: uuid.UUID,
    scope: str,
    scope_id: str | None,
    owner_id: str,
    tenant_id: str,
    domains: list[str] | None,
    embedding_service: EmbeddingService,
    session: AsyncSession,
    now: datetime,
) -> bool:
    """Create semantic chunk children for an oversized memory.

    Returns True if chunks were created, False if the content produced
    only a single chunk (not worth splitting).
    """
    chunks = semantic_chunk(content)
    if len(chunks) <= 1:
        return False

    chunk_embeddings = await embedding_service.embed_batch(chunks)
    for i, (chunk_text, chunk_emb) in enumerate(
        zip(chunks, chunk_embeddings, strict=True)
    ):
        chunk_stub = generate_stub(
            content=chunk_text,
            scope=scope,
            weight=0.0,
            branch_count=0,
            has_rationale=False,
        )
        chunk_node = MemoryNode(
            id=uuid.uuid4(),
            content=chunk_text,
            stub=chunk_stub,
            scope=scope,
            scope_id=scope_id,
            weight=0.0,
            owner_id=owner_id,
            tenant_id=tenant_id,
            parent_id=parent_id,
            branch_type="chunk",
            metadata_={"chunk_index": i, "total_chunks": len(chunks)},
            domains=domains,
            embedding=chunk_emb,
            is_current=True,
            version=1,
            storage_type="inline",
            created_at=now,
            updated_at=now,
        )
        session.add(chunk_node)
    await session.commit()
    return True


async def read_memory(
    memory_id: uuid.UUID,
    session: AsyncSession,
    *,
    tenant_id: str,
) -> MemoryNodeRead:
    """Read a memory node by ID.

    Returns the node with branch_count populated via a single COUNT query.
    Branches are no longer loaded inline -- callers that need branch contents
    should query them explicitly via search_memory or follow-up read_memory
    calls. When the requested node is a historical (non-current) version,
    populates current_version_id by walking the version chain forward, so
    callers can pivot to the live version in a single round-trip.
    Raises MemoryNotFoundError if the node does not exist.

    Tenant isolation: ``tenant_id`` is a required keyword argument. The
    query filters on it at the SQL level, and a cross-tenant lookup
    returns the same ``MemoryNotFoundError`` as a nonexistent row so
    callers can never distinguish "does not exist" from "exists in
    another tenant." This mirrors the authz layer's per-row behavior.
    """
    stmt = select(MemoryNode).where(
        MemoryNode.id == memory_id,
        MemoryNode.deleted_at.is_(None),
        MemoryNode.tenant_id == tenant_id,
        # Non-admin read: only active memories are visible.
        # Quarantined and soft_deleted require admin_memory tool.
        MemoryNode.status == "active",
    )
    result = await session.execute(stmt)
    node = result.scalar_one_or_none()

    if node is None:
        # Cross-tenant hits, quarantined, and soft_deleted all land here
        # indistinguishably from nonexistent rows. Do NOT log the mismatch
        # at WARNING or higher -- anything above debug leaks existence
        # through log aggregation.
        raise MemoryNotFoundError(memory_id)

    has_children, has_rationale, branch_count = await _compute_branch_flags(node, session)

    current_version_id: uuid.UUID | None = None
    if not node.is_current:
        # Walk the full chain (both directions) and pick the current node.
        # _walk_version_chain is the same helper used by get_memory_history
        # and delete_memory; it handles the case where the caller passed a
        # middle version ID. There is at most one is_current=true node in a
        # well-formed chain; if none exists (e.g., the chain has been fully
        # superseded but not yet pruned), leave the pointer as None.
        chain = await _walk_version_chain(node, session)
        for n in chain:
            if n.is_current and n.deleted_at is None:
                current_version_id = n.id
                break

    return node_to_read(
        node,
        has_children=has_children,
        has_rationale=has_rationale,
        branch_count=branch_count,
        current_version_id=current_version_id,
    )


async def update_memory(
    memory_id: uuid.UUID,
    data: MemoryNodeUpdate,
    session: AsyncSession,
    embedding_service: EmbeddingService,
    s3_adapter: S3StorageAdapter | None = None,
    actor_id: str | None = None,
    driver_id: str | None = None,
) -> MemoryNodeRead:
    """Create a new version of a memory node.

    Marks the old version as not-current and creates a new node with
    incremented version and previous_version_id pointing to the old.
    Raises MemoryNotFoundError or MemoryNotCurrentError as appropriate.

    Tenant isolation: the new version inherits ``tenant_id`` from the
    existing row. Tenant is a property of the memory, not of the update
    call -- the tool layer's authorize_write has already verified that the
    caller shares the memory's tenant before we get here (it passes
    ``existing.tenant_id``). Deep-copied child branches also inherit their
    parent's tenant.

    When updated content exceeds the S3 threshold, fresh semantic chunks are
    always created for fine-grained search. If ``s3_adapter`` is provided,
    the full content is also uploaded to MinIO; otherwise it remains inline.
    Old chunk children are retired (not deep-copied) since they reflect
    the previous content.
    """
    stmt = select(MemoryNode).where(MemoryNode.id == memory_id)
    result = await session.execute(stmt)
    old_node = result.scalar_one_or_none()

    if old_node is None:
        raise MemoryNotFoundError(memory_id)

    if not old_node.is_current:
        # Find the current version to include in the error
        current_stmt = (
            select(MemoryNode)
            .where(
                MemoryNode.owner_id == old_node.owner_id,
                MemoryNode.scope == old_node.scope,
                MemoryNode.is_current.is_(True),
            )
            .where(
                MemoryNode.id != memory_id,
            )
        )
        current_result = await session.execute(current_stmt)
        current_node = current_result.scalars().first()
        current_id = current_node.id if current_node else memory_id
        raise MemoryNotCurrentError(memory_id, current_id)

    # Apply updates
    content_changed = data.content is not None
    new_content = data.content if content_changed else old_node.content
    new_weight = data.weight if data.weight is not None else old_node.weight
    new_metadata = data.metadata if data.metadata is not None else old_node.metadata_
    new_domains = data.domains if data.domains is not None else old_node.domains

    app_settings = AppSettings()

    # Determine storage and chunking strategy for the new version
    if content_changed:
        content_bytes = len(new_content.encode("utf-8"))
        embedding_max_chars = app_settings.embedding_max_tokens * 4
        needs_chunking = len(new_content) > embedding_max_chars
        use_s3 = content_bytes > app_settings.s3_threshold_bytes and s3_adapter is not None
        embed_text = new_content[:embedding_max_chars] if needs_chunking else new_content
    else:
        needs_chunking = False
        use_s3 = old_node.storage_type == "s3" and s3_adapter is not None
        embed_text = new_content

    embedding = await embedding_service.embed(embed_text)
    stub = generate_stub(
        content=new_content,
        scope=old_node.scope,
        weight=new_weight,
        branch_count=0,
        has_rationale=False,
    )

    now = datetime.now(UTC)
    new_id = uuid.uuid4()

    # Handle S3 storage for the new version
    if content_changed and use_s3:
        content_ref = await s3_adapter.put_content(
            old_node.tenant_id, new_id, new_id, new_content,
        )
        db_content = new_content[:app_settings.s3_prefix_chars]
        storage_type = "s3"
    elif content_changed:
        # Content changed but fits inline (or no S3 adapter)
        content_ref = None
        db_content = new_content
        storage_type = "inline"
    else:
        # Content unchanged — inherit storage from old node
        content_ref = old_node.content_ref
        db_content = old_node.content
        storage_type = old_node.storage_type

    # Recompute relevant_until when content changes; inherit from old node otherwise.
    if content_changed:
        from memoryhub_core.services.temporal import classify_temporal

        new_relevant_until = classify_temporal(new_content, now)
    else:
        new_relevant_until = old_node.relevant_until

    new_node = MemoryNode(
        id=new_id,
        content=db_content,
        stub=stub,
        scope=old_node.scope,
        scope_id=old_node.scope_id,
        weight=new_weight,
        owner_id=old_node.owner_id,
        actor_id=actor_id,
        driver_id=driver_id,
        tenant_id=old_node.tenant_id,
        parent_id=old_node.parent_id,
        branch_type=old_node.branch_type,
        metadata_=new_metadata,
        domains=new_domains,
        relevant_until=new_relevant_until,
        embedding=embedding,
        is_current=True,
        version=old_node.version + 1,
        previous_version_id=old_node.id,
        storage_type=storage_type,
        content_ref=content_ref,
        created_at=now,
        updated_at=now,
    )

    # Set TTL on the old version
    old_node.is_current = False
    old_node.expires_at = now + timedelta(days=app_settings.version_retention_days)

    session.add(new_node)

    # Deep-copy one level of child branches from old node to new node.
    # Chunk branches are skipped when content changed (they reflect old
    # content and will be replaced by fresh chunks below).
    children_stmt = select(MemoryNode).where(MemoryNode.parent_id == old_node.id)
    children_result = await session.execute(children_stmt)
    old_children = children_result.scalars().all()

    copied_count = 0
    for child in old_children:
        if child.branch_type == "chunk" and content_changed:
            # Retire old chunk — new chunks will be created below
            child.is_current = False
            child.expires_at = now + timedelta(days=app_settings.version_retention_days)
            continue

        # Deep copy non-chunk branch to new parent
        copied_child = MemoryNode(
            id=uuid.uuid4(),
            content=child.content,
            stub=child.stub,
            scope=child.scope,
            weight=child.weight,
            owner_id=child.owner_id,
            tenant_id=child.tenant_id,
            parent_id=new_node.id,
            branch_type=child.branch_type,
            metadata_=child.metadata_,
            domains=child.domains,
            embedding=list(child.embedding) if child.embedding is not None else None,
            is_current=True,
            version=child.version,
            previous_version_id=None,
            storage_type=child.storage_type,
            content_ref=child.content_ref,
            created_at=child.created_at,
            updated_at=now,
        )
        session.add(copied_child)
        copied_count += 1

        # Retire old branch — deep copy is the canonical version now
        child.is_current = False
        child.expires_at = now + timedelta(days=app_settings.version_retention_days)

    await session.commit()

    # Create fresh semantic chunks if the new content is oversized.
    # Uses the same _create_chunk_children helper as create_memory.
    chunk_created = False
    if content_changed and needs_chunking:
        try:
            chunk_created = await _create_chunk_children(
                content=new_content,
                parent_id=new_id,
                scope=old_node.scope,
                scope_id=old_node.scope_id,
                owner_id=old_node.owner_id,
                tenant_id=old_node.tenant_id,
                domains=new_domains,
                embedding_service=embedding_service,
                session=session,
                now=now,
            )
        except Exception:
            logger.warning(
                "Failed to create chunks for updated memory %s; "
                "memory is saved but only prefix is searchable",
                new_id,
                exc_info=True,
            )

    await session.refresh(new_node)

    has_children = copied_count > 0 or chunk_created
    non_chunk_children = [c for c in old_children if c.branch_type != "chunk"]
    has_rationale = any(c.branch_type == "rationale" for c in non_chunk_children)
    return node_to_read(
        new_node,
        has_children=has_children,
        has_rationale=has_rationale,
        branch_count=copied_count,
    )


async def delete_memory(
    memory_id: uuid.UUID,
    session: AsyncSession,
    s3_adapter: S3StorageAdapter | None = None,
) -> dict:
    """Soft-delete a memory and its entire version chain.

    Marks the target node and all nodes in its version chain with
    deleted_at = now. Relationships are left intact (they reference
    deleted nodes, which are filtered from queries). Returns a summary
    dict with the count of deleted versions.

    When ``s3_adapter`` is provided, also removes S3 objects for any
    versions that used external storage.

    Raises MemoryNotFoundError if the node doesn't exist, or
    MemoryAlreadyDeletedError if already soft-deleted.
    """
    stmt = select(MemoryNode).where(MemoryNode.id == memory_id)
    result = await session.execute(stmt)
    node = result.scalar_one_or_none()

    if node is None:
        raise MemoryNotFoundError(memory_id)

    if node.deleted_at is not None:
        raise MemoryAlreadyDeletedError(memory_id)

    now = datetime.now(UTC)

    chain_nodes = await _walk_version_chain(node, session)
    version_ids: set[uuid.UUID] = {n.id for n in chain_nodes}

    # Also delete child branches of all versions in the chain
    child_stmt = select(MemoryNode).where(MemoryNode.parent_id.in_(list(version_ids)))
    child_result = await session.execute(child_stmt)
    child_ids = {child.id for child in child_result.scalars().all()}
    all_ids = version_ids | child_ids

    # Collect S3 content_refs before soft-delete so we can clean up objects
    s3_refs: list[str] = []
    if s3_adapter is not None:
        s3_refs_stmt = (
            select(MemoryNode.content_ref)
            .where(
                MemoryNode.id.in_(list(all_ids)),
                MemoryNode.storage_type == "s3",
                MemoryNode.content_ref.isnot(None),
            )
        )
        s3_result = await session.execute(s3_refs_stmt)
        s3_refs = [row[0] for row in s3_result.all()]

    # Bulk soft-delete
    await session.execute(
        update(MemoryNode)
        .where(MemoryNode.id.in_(list(all_ids)))
        .values(deleted_at=now, is_current=False)
    )

    await session.commit()

    # Clean up S3 objects after successful DB commit
    if s3_refs:
        await s3_adapter.delete_contents(s3_refs)

    return {
        "deleted_id": str(memory_id),
        "versions_deleted": len(version_ids),
        "branches_deleted": len(child_ids),
        "total_deleted": len(all_ids),
    }


def _build_search_filters(
    scope: str | None,
    owner_id: str | None,
    current_only: bool,
    authorized_scopes: dict[str, str | None] | None,
    tenant_id: str,
    campaign_ids: set[str] | None = None,
    project_ids: set[str] | None = None,
    role_names: set[str] | None = None,
    entity_names: list[str] | None = None,
    content_type: str | None = None,
    temporal_status: str | None = None,
    include_statuses: list[str] | None = None,
) -> list | None:
    """Build the SQL filter list shared by search_memories and count_search_matches.

    Returns None if authorized_scopes was provided but empty (callers should
    short-circuit to "no results"). This avoids duplicating the filter logic
    between the search query and the count query that backs has_more.

    ``tenant_id`` is required and applied unconditionally -- tenant
    filtering is always-on at the SQL level. Cross-tenant rows are
    invisible to the query, mirroring the authz layer's per-row behavior.
    """
    filters = [
        MemoryNode.deleted_at.is_(None),
        MemoryNode.tenant_id == tenant_id,
    ]
    # Status filter: default to active-only so quarantined and
    # soft_deleted memories are invisible to regular queries.
    # Admin callers pass include_statuses to widen visibility.
    if include_statuses:
        filters.append(MemoryNode.status.in_(include_statuses))
    else:
        filters.append(MemoryNode.status == "active")
    if current_only:
        filters.append(MemoryNode.is_current.is_(True))
    if scope is not None:
        filters.append(MemoryNode.scope == scope)
    else:
        # Entity nodes are infrastructure (extracted entities, not agent-written
        # memories). Exclude them from normal search unless the caller explicitly
        # requests scope="entity".
        filters.append(MemoryNode.scope != "entity")
    if owner_id is not None:
        filters.append(MemoryNode.owner_id == owner_id)

    if authorized_scopes is not None:
        if not authorized_scopes:
            return None  # no authorized scopes → no results
        scope_conditions = []
        for scope_name, required_owner in authorized_scopes.items():
            if scope_name == "campaign":
                # Campaign-scoped memories are only visible when the
                # caller's project is enrolled in the campaign. The
                # memory's owner_id holds the campaign UUID.
                if campaign_ids:
                    scope_conditions.append(
                        and_(
                            MemoryNode.scope == "campaign",
                            MemoryNode.owner_id.in_(campaign_ids),
                        )
                    )
                # If campaign_ids is empty/None, skip — no campaign
                # memories are visible to this caller.
                continue
            if scope_name == "project":
                # Use explicitly-passed project_ids when available (may
                # be a narrower filter, e.g. single project_id from the
                # tool parameter). Fall back to the authorized_scopes
                # value when it carries a list of project IDs from the
                # claims pipeline (#64).
                effective_project_ids = project_ids
                if not effective_project_ids and isinstance(required_owner, list):
                    effective_project_ids = set(required_owner)
                if effective_project_ids:
                    scope_conditions.append(
                        and_(
                            MemoryNode.scope == "project",
                            MemoryNode.scope_id.in_(effective_project_ids),
                        )
                    )
                # If no project IDs from either source, skip — no project
                # memories are visible to this caller.
                continue
            if scope_name == "role":
                if role_names:
                    scope_conditions.append(
                        and_(
                            MemoryNode.scope == "role",
                            MemoryNode.scope_id.in_(role_names),
                        )
                    )
                # If role_names is empty/None, skip — no role
                # memories are visible to this caller.
                continue
            if required_owner is not None:
                scope_conditions.append(
                    and_(
                        MemoryNode.scope == scope_name,
                        MemoryNode.owner_id == required_owner,
                    )
                )
            else:
                scope_conditions.append(MemoryNode.scope == scope_name)
        if scope_conditions:
            filters.append(or_(*scope_conditions))
        else:
            # All authorized scopes were skipped (e.g., campaign-only
            # caller with no campaign_ids). No scope matches → no results.
            return None

    if entity_names:
        from memoryhub_core.models.memory import MemoryRelationship
        entity_subq = (
            select(MemoryRelationship.source_id)
            .join(
                MemoryNode,
                and_(
                    MemoryNode.id == MemoryRelationship.target_id,
                    MemoryNode.scope == "entity",
                    func.lower(MemoryNode.content).in_([n.lower() for n in entity_names]),
                    MemoryNode.tenant_id == tenant_id,
                    MemoryNode.deleted_at.is_(None),
                ),
            )
            .where(
                MemoryRelationship.relationship_type == "mentions",
                MemoryRelationship.valid_until.is_(None),
                MemoryRelationship.tenant_id == tenant_id,
            )
        )
        filters.append(MemoryNode.id.in_(entity_subq))

    if content_type is not None:
        filters.append(MemoryNode.content_type == content_type)

    # Temporal status filter: restrict results by relevant_until semantics.
    if temporal_status is not None and temporal_status != "all":
        now_expr = func.now()
        if temporal_status == "current":
            # NULL (evergreen/version-bound) or future
            filters.append(
                or_(
                    MemoryNode.relevant_until.is_(None),
                    MemoryNode.relevant_until > now_expr,
                )
            )
        elif temporal_status == "expired":
            filters.append(
                and_(
                    MemoryNode.relevant_until.isnot(None),
                    MemoryNode.relevant_until <= now_expr,
                )
            )
        elif temporal_status == "expiring_soon":
            seven_days = now_expr + timedelta(days=7)
            filters.append(
                and_(
                    MemoryNode.relevant_until.isnot(None),
                    MemoryNode.relevant_until > now_expr,
                    MemoryNode.relevant_until <= seven_days,
                )
            )

    return filters


async def count_search_matches(
    session: AsyncSession,
    *,
    tenant_id: str,
    scope: str | None = None,
    owner_id: str | None = None,
    current_only: bool = True,
    authorized_scopes: dict[str, str | None] | None = None,
    campaign_ids: set[str] | None = None,
    project_ids: set[str] | None = None,
    role_names: set[str] | None = None,
    entity_names: list[str] | None = None,
    content_type: str | None = None,
    temporal_status: str | None = None,
) -> int:
    """Count memories matching the same filter set used by search_memories.

    Used by the search_memory tool to compute has_more for pagination, since
    search_memories itself only returns a single page of results. The query
    parameter and weight_threshold are intentionally absent: total_matching
    is independent of the embedding similarity ranking.

    ``tenant_id`` is required -- every count is scoped to a single tenant
    so cross-tenant rows never contribute to ``total_matching`` or
    ``has_more``.
    """
    filters = _build_search_filters(
        scope, owner_id, current_only, authorized_scopes, tenant_id,
        campaign_ids=campaign_ids,
        project_ids=project_ids,
        role_names=role_names,
        entity_names=entity_names,
        content_type=content_type,
        temporal_status=temporal_status,
    )
    if filters is None:
        return 0
    stmt = select(func.count()).select_from(MemoryNode).where(*filters)
    return (await session.execute(stmt)).scalar() or 0


async def _expand_chunks_to_parents(
    scored_nodes: list[tuple[MemoryNode, float]],
    session: AsyncSession,
) -> list[tuple[MemoryNode, float]]:
    """Replace chunk hits with their parent memories, keeping best scores.

    Chunks are search infrastructure, not retrieval units. When a chunk
    matches a query, the caller wants the parent memory (full content or
    stub), not the chunk text. This function:
    1. Identifies chunk hits (branch_type='chunk' with a parent_id)
    2. Bulk-loads their parents
    3. Replaces each chunk with its parent, preserving the chunk's score
    4. Deduplicates: if the same parent appears via multiple chunks or
       as both a direct hit and a chunk expansion, keeps the best score
    """
    chunk_parent_ids: set[uuid.UUID] = set()
    for node, _ in scored_nodes:
        if node.branch_type == "chunk" and node.parent_id is not None:
            chunk_parent_ids.add(node.parent_id)

    if not chunk_parent_ids:
        return scored_nodes

    parent_stmt = (
        select(MemoryNode)
        .where(
            MemoryNode.id.in_(chunk_parent_ids),
            MemoryNode.deleted_at.is_(None),
        )
    )
    parent_result = await session.execute(parent_stmt)
    parents_by_id: dict[uuid.UUID, MemoryNode] = {
        p.id: p for p in parent_result.scalars().all()
    }

    best_scores: dict[uuid.UUID, tuple[MemoryNode, float]] = {}
    for node, score in scored_nodes:
        if node.branch_type == "chunk" and node.parent_id is not None:
            parent = parents_by_id.get(node.parent_id)
            if parent is None:
                continue
            effective_id = parent.id
            effective_node = parent
        else:
            effective_id = node.id
            effective_node = node

        existing = best_scores.get(effective_id)
        if existing is None or score > existing[1]:
            best_scores[effective_id] = (effective_node, score)

    result = sorted(best_scores.values(), key=lambda pair: pair[1], reverse=True)
    return result


async def search_memories(
    query: str,
    session: AsyncSession,
    embedding_service: EmbeddingService,
    *,
    tenant_id: str,
    scope: str | None = None,
    owner_id: str | None = None,
    weight_threshold: float = 0.8,
    max_results: int = 20,
    current_only: bool = True,
    authorized_scopes: dict[str, str | None] | None = None,
    campaign_ids: set[str] | None = None,
    project_ids: set[str] | None = None,
    role_names: set[str] | None = None,
    entity_names: list[str] | None = None,
    content_type: str | None = None,
    temporal_status: str | None = None,
    keyword_boost_weight: float = 0.15,
    disabled_signals: set[str] | None = None,
) -> list[tuple[MemoryNodeRead | MemoryNodeStub, float]]:
    """Search memories using pgvector cosine similarity with optional keyword recall.

    Returns a list of (result, relevance_score) tuples. High-weight results
    are MemoryNodeRead, low-weight results are MemoryNodeStub.

    When keyword recall is active (default), the relevance score is an RRF
    blend of cosine and keyword ranks. When keyword is disabled, scoring
    falls back to cosine-rank-only RRF (equivalent to the previous behavior).

    Falls back to weight-based ordering with synthetic scores when pgvector
    is not available (e.g., SQLite in tests).

    When authorized_scopes is provided, results are filtered to only include
    memories the caller is authorized to read. The dict maps scope names to
    required owner_id values (None means no owner filter for that scope).

    ``tenant_id`` is a required keyword argument -- the query is unconditionally
    filtered to that tenant at the SQL level. Cross-tenant rows are invisible;
    a search that would otherwise match them simply returns fewer results.
    """
    _disabled = disabled_signals or set()
    query_embedding = await embedding_service.embed(query)

    filters = _build_search_filters(
        scope, owner_id, current_only, authorized_scopes, tenant_id,
        campaign_ids=campaign_ids,
        project_ids=project_ids,
        role_names=role_names,
        entity_names=entity_names,
        content_type=content_type,
        temporal_status=temporal_status,
    )
    if filters is None:
        return []

    # Fetch a larger recall pool to compensate for chunk-to-parent collapse.
    # After expansion, multiple chunk hits from the same parent merge into
    # one result, so the pre-expansion pool must be larger than max_results.
    chunk_expansion_headroom = 5
    k_recall = max(RERANK_POOL_SIZE, max_results * chunk_expansion_headroom)

    use_pgvector = True
    try:
        distance_expr = MemoryNode.embedding.cosine_distance(query_embedding)
        stmt = (
            select(MemoryNode, distance_expr.label("distance"))
            .where(*filters)
            .order_by(distance_expr)
            .limit(k_recall)
        )
    except Exception:
        use_pgvector = False
        stmt = select(MemoryNode).where(*filters).order_by(MemoryNode.weight.desc()).limit(max_results)

    result = await session.execute(stmt)

    if use_pgvector:
        rows = result.all()
        candidate_nodes = [row[0] for row in rows]
        rank_cosine: dict[uuid.UUID, int] = {
            node.id: idx for idx, node in enumerate(candidate_nodes, start=1)
        }
    else:
        candidate_nodes = list(result.scalars().all())
        total = len(candidate_nodes) if candidate_nodes else 1
        results: list[tuple[MemoryNodeRead | MemoryNodeStub, float]] = []
        node_ids = [n.id for n in candidate_nodes]
        branch_flags = await _bulk_branch_flags(node_ids, session)
        for i, node in enumerate(candidate_nodes):
            score = 1.0 - (i / total)
            has_children, has_rationale, branch_count = branch_flags.get(
                node.id, (False, False, 0)
            )
            if node.weight >= weight_threshold:
                results.append((node_to_read(
                    node, has_children=has_children,
                    has_rationale=has_rationale, branch_count=branch_count,
                ), score))
            else:
                results.append((MemoryNodeStub(
                    id=node.id, parent_id=node.parent_id, stub=node.stub,
                    scope=node.scope, weight=node.weight,
                    branch_type=node.branch_type, has_children=has_children,
                    has_rationale=has_rationale,
                    content_type=node.content_type, created_at=node.created_at,
                ), score))
        return results

    if not candidate_nodes:
        return []

    # Keyword recall: tsvector query to find candidates that match query
    # keywords but may have been missed by vector recall.
    use_keyword = (
        keyword_boost_weight > 0.0
        and use_pgvector
        and "keyword" not in _disabled
    )
    rank_keyword: dict[uuid.UUID, int] = {}
    if use_keyword:
        try:
            tsquery = func.plainto_tsquery("english", query)
            keyword_stmt = (
                select(
                    MemoryNode,
                    func.ts_rank(MemoryNode.search_vector, tsquery).label("kw_rank"),
                )
                .where(*filters, MemoryNode.search_vector.op("@@")(tsquery))
                .order_by(sa_text("kw_rank DESC"))
                .limit(k_recall)
            )
            kw_result = await session.execute(keyword_stmt)
            kw_rows = kw_result.all()

            existing_ids = {node.id for node in candidate_nodes}
            for rank_idx, row in enumerate(kw_rows, start=1):
                kw_node = row[0]
                rank_keyword[kw_node.id] = rank_idx
                if kw_node.id not in existing_ids:
                    candidate_nodes.append(kw_node)
                    existing_ids.add(kw_node.id)
        except Exception as exc:
            logger.warning("keyword recall failed, skipping: %s", exc)
            use_keyword = False

    # RRF blend: cosine rank + keyword rank (when active).
    weight_k = keyword_boost_weight if use_keyword else 0.0
    weight_q = 1.0 - weight_k
    miss_rank = k_recall + 1

    scored: list[tuple[MemoryNode, float]] = []
    for node in candidate_nodes:
        score_q = weight_q / (RRF_K + rank_cosine.get(node.id, miss_rank))
        score_k = (
            weight_k / (RRF_K + rank_keyword.get(node.id, miss_rank))
            if use_keyword
            else 0.0
        )
        scored.append((node, score_q + score_k))
    scored.sort(key=lambda pair: pair[1], reverse=True)
    scored = await _expand_chunks_to_parents(scored, session)

    top_nodes = scored[:max_results]

    node_ids = [n.id for n, _ in top_nodes]
    branch_flags = await _bulk_branch_flags(node_ids, session)

    results: list[tuple[MemoryNodeRead | MemoryNodeStub, float]] = []
    for node, rrf_score in top_nodes:
        has_children, has_rationale, branch_count = branch_flags.get(
            node.id, (False, False, 0)
        )
        if node.weight >= weight_threshold:
            results.append((node_to_read(
                node, has_children=has_children,
                has_rationale=has_rationale, branch_count=branch_count,
            ), rrf_score))
        else:
            results.append((MemoryNodeStub(
                id=node.id, parent_id=node.parent_id, stub=node.stub,
                scope=node.scope, weight=node.weight,
                branch_type=node.branch_type, has_children=has_children,
                has_rationale=has_rationale,
                content_type=node.content_type, created_at=node.created_at,
            ), rrf_score))
    return results


async def list_memories(
    session: AsyncSession,
    *,
    tenant_id: str,
    scope: str | None = None,
    owner_id: str | None = None,
    max_results: int = 100,
    cursor: str | None = None,
    current_only: bool = True,
    authorized_scopes: dict[str, str | None] | None = None,
    campaign_ids: set[str] | None = None,
    project_ids: set[str] | None = None,
    role_names: set[str] | None = None,
    content_type: str | None = None,
    temporal_status: str | None = None,
) -> tuple[list[MemoryNodeRead | MemoryNodeStub], str | None]:
    """Enumerate memories without semantic ranking.

    Returns (results, next_cursor). Ordered by created_at DESC for
    deterministic pagination. No embedding cost. RBAC filters are
    identical to search_memories.
    """
    filters = _build_search_filters(
        scope, owner_id, current_only, authorized_scopes, tenant_id,
        campaign_ids=campaign_ids,
        project_ids=project_ids,
        role_names=role_names,
        content_type=content_type,
        temporal_status=temporal_status,
    )
    if filters is None:
        return [], None

    if cursor is not None:
        try:
            cursor_dt = datetime.fromisoformat(cursor).replace(tzinfo=UTC)
            filters.append(MemoryNode.created_at < cursor_dt)
        except (ValueError, TypeError):
            pass

    stmt = (
        select(MemoryNode)
        .where(*filters)
        .order_by(MemoryNode.created_at.desc())
        .limit(max_results + 1)
    )
    rows = (await session.execute(stmt)).scalars().all()

    has_more = len(rows) > max_results
    nodes = rows[:max_results]

    if not nodes:
        return [], None

    node_ids = [n.id for n in nodes]
    branch_flags = await _bulk_branch_flags(node_ids, session)

    results: list[MemoryNodeRead | MemoryNodeStub] = []
    for node in nodes:
        has_children, has_rationale, branch_count = branch_flags.get(
            node.id, (False, False, 0)
        )
        results.append(
            node_to_read(
                node,
                has_children=has_children,
                has_rationale=has_rationale,
                branch_count=branch_count,
            )
        )

    next_cursor = None
    if has_more:
        next_cursor = nodes[-1].created_at.isoformat()

    return results, next_cursor


# ---- Two-vector retrieval (#58, NEW-1 RRF blend) -----------------------


@dataclass
class FocusedSearchResult:
    """Output of search_memories_with_focus.

    The `results` list has the same shape as search_memories' return
    value (list of (item, relevance_score) tuples) so MCP tool code
    can format both paths uniformly. The pivot_* fields surface the
    embedding distance from the query to the focus vector and a
    boolean threshold flag; only set when a focus was provided.
    """

    results: list[tuple[MemoryNodeRead | MemoryNodeStub, float]] = field(
        default_factory=list
    )
    pivot_suggested: bool = False
    pivot_distance: float | None = None
    pivot_threshold: float | None = None
    pivot_reason: str | None = None
    used_reranker: bool = False
    fallback_reason: str | None = None
    graph_neighbors_added: int = 0
    graph_fallback_reason: str | None = None
    keyword_matches: int = 0
    pattern_signals: list[PatternSignal] = field(default_factory=list)
    disabled_signals: set[str] = field(default_factory=set)


def _cosine_distance(a: list[float], b: list[float]) -> float:
    """Cosine distance for two vectors. Range [0, 2]; 0 = identical.

    Always returns a Python float, even when the input lists contain
    numpy.float32 elements (pgvector returns numpy arrays in production).
    pydantic_core.to_jsonable_python rejects numpy scalars, so any numpy
    leakage into the response dict breaks FastMCP's structured-output
    serialization with a confusing "outputSchema defined but no structured
    output returned" error.
    """
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b, strict=True):
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0 or nb <= 0:
        return 1.0
    sim = dot / (math.sqrt(na) * math.sqrt(nb))
    # Clamp to handle floating-point drift outside [-1, 1].
    sim = max(-1.0, min(1.0, sim))
    return float(1.0 - sim)


async def search_memories_with_focus(
    query: str,
    session: AsyncSession,
    embedding_service: EmbeddingService,
    *,
    tenant_id: str,
    focus_string: str,
    session_focus_weight: float = 0.4,
    reranker: RerankerService | None = None,
    pivot_threshold: float = DEFAULT_PIVOT_THRESHOLD,
    scope: str | None = None,
    owner_id: str | None = None,
    weight_threshold: float = 0.8,
    max_results: int = 20,
    current_only: bool = True,
    authorized_scopes: dict[str, str | None] | None = None,
    campaign_ids: set[str] | None = None,
    project_ids: set[str] | None = None,
    role_names: set[str] | None = None,
    domains: list[str] | None = None,
    domain_boost_weight: float = 0.3,
    graph_depth: int = 0,
    graph_relationship_types: list[str] | None = None,
    graph_boost_weight: float = 0.2,
    entity_names: list[str] | None = None,
    content_type: str | None = None,
    temporal_status: str | None = None,
    keyword_boost_weight: float = 0.15,
    disabled_signals: set[str] | None = None,
) -> FocusedSearchResult:
    """Two-vector retrieval with session focus bias.

    Pipeline (NEW-1 from research/two-vector-retrieval.md):

        pgvector cosine recall (top-K_recall by query)
            ↓
        cross-encoder rerank by query.text (when reranker available)
            ↓
        RRF blend (rerank ranks, focus cosine ranks)
            ↓
        top max_results

    The focus string is embedded once per call and used both as the
    bias vector for the RRF blend and as the basis for pivot detection.

    When `session_focus_weight <= 0` or `focus_string` is empty, this
    function falls through to the same code path as `search_memories`
    -- it accepts the call shape for caller convenience but does no
    additional work.

    When the reranker is None, not configured, or fails at call time,
    the rerank stage is skipped and the RRF blend operates on cosine
    ranks instead. The fallback path is logged via the returned
    ``fallback_reason`` so the MCP tool can surface it for debugging.

    Returns a FocusedSearchResult dataclass; see its docstring for
    field semantics.
    """
    _disabled = disabled_signals or set()

    if not focus_string or session_focus_weight <= 0.0:
        # No-focus short-circuit. Skips both the focus embed and the
        # rerank network call. Mirrors the production-tuning rule
        # from the benchmark: when there's no focus signal, the
        # cross-encoder doesn't help, so don't pay for it.
        plain = await search_memories(
            query=query,
            session=session,
            embedding_service=embedding_service,
            tenant_id=tenant_id,
            scope=scope,
            owner_id=owner_id,
            weight_threshold=weight_threshold,
            max_results=max_results,
            current_only=current_only,
            authorized_scopes=authorized_scopes,
            campaign_ids=campaign_ids,
            project_ids=project_ids,
            role_names=role_names,
            entity_names=entity_names,
            content_type=content_type,
            temporal_status=temporal_status,
        )
        return FocusedSearchResult(results=plain)

    query_embedding = await embedding_service.embed(query)
    focus_embedding = await embedding_service.embed(focus_string)

    pivot_distance = _cosine_distance(query_embedding, focus_embedding)
    pivot_suggested = pivot_distance > pivot_threshold
    pivot_reason: str | None = None
    if pivot_suggested:
        pivot_reason = (
            f"query vector distance from session focus is "
            f"{pivot_distance:.3f} (threshold {pivot_threshold:.2f})"
        )

    filters = _build_search_filters(
        scope, owner_id, current_only, authorized_scopes, tenant_id,
        campaign_ids=campaign_ids,
        project_ids=project_ids,
        role_names=role_names,
        entity_names=entity_names,
        content_type=content_type,
        temporal_status=temporal_status,
    )
    if filters is None:
        return FocusedSearchResult(
            pivot_suggested=pivot_suggested,
            pivot_distance=pivot_distance,
            pivot_threshold=pivot_threshold,
            pivot_reason=pivot_reason,
        )

    # Recall pool: large enough to survive chunk-to-parent collapse.
    chunk_expansion_headroom = 5
    k_recall = max(RERANK_POOL_SIZE, max_results * chunk_expansion_headroom)

    use_pgvector = True
    try:
        distance_expr = MemoryNode.embedding.cosine_distance(query_embedding)
        stmt = (
            select(MemoryNode, distance_expr.label("distance"))
            .where(*filters)
            .order_by(distance_expr)
            .limit(k_recall)
        )
    except Exception:
        use_pgvector = False
        stmt = (
            select(MemoryNode)
            .where(*filters)
            .order_by(MemoryNode.weight.desc())
            .limit(k_recall)
        )

    db_result = await session.execute(stmt)

    if use_pgvector:
        rows = db_result.all()
        candidate_nodes: list[MemoryNode] = [row[0] for row in rows]
    else:
        candidate_nodes = list(db_result.scalars().all())

    if not candidate_nodes:
        return FocusedSearchResult(
            pivot_suggested=pivot_suggested,
            pivot_distance=pivot_distance,
            pivot_threshold=pivot_threshold,
            pivot_reason=pivot_reason,
        )

    # Graph traversal: when graph_depth > 0, expand the candidate pool
    # with nodes reachable from the vector-recall seeds via the graph.
    graph_neighbors_added = 0
    graph_fallback_reason: str | None = None
    graph_neighbor_map: dict[uuid.UUID, int] = {}  # node_id -> hop_distance
    if graph_depth > 0 and "graph" not in _disabled:
        from memoryhub_core.services.graph import collect_graph_neighbors

        seed_ids = [node.id for node in candidate_nodes]
        graph_neighbor_map = await collect_graph_neighbors(
            seed_ids=seed_ids,
            session=session,
            tenant_id=tenant_id,
            max_depth=graph_depth,
            relationship_types=graph_relationship_types,
        )
        if not graph_neighbor_map:
            graph_fallback_reason = (
                "no graph neighbors found for seed nodes"
            )
        else:
            # Fetch neighbor nodes not already in the candidate set.
            existing_ids = {node.id for node in candidate_nodes}
            new_neighbor_ids = [
                nid for nid in graph_neighbor_map if nid not in existing_ids
            ]
            if new_neighbor_ids:
                neighbor_stmt = (
                    select(MemoryNode)
                    .where(*filters, MemoryNode.id.in_(new_neighbor_ids))
                )
                neighbor_result = await session.execute(neighbor_stmt)
                new_nodes = list(neighbor_result.scalars().all())
                candidate_nodes = candidate_nodes + new_nodes
                graph_neighbors_added = len(new_nodes)

    # Cosine ranks of the recall pool by query (already in this
    # order from pgvector). 1-based ranks.
    rank_query: dict[uuid.UUID, int] = {
        node.id: idx + 1 for idx, node in enumerate(candidate_nodes)
    }

    # Cross-encoder rerank stage (top RERANK_POOL_SIZE candidates).
    used_reranker = False
    fallback_reason: str | None = None
    if reranker is not None and getattr(reranker, "is_configured", True) and "reranker" not in _disabled:
        rerank_pool = candidate_nodes[:RERANK_POOL_SIZE]
        try:
            order = await batched_rerank(
                reranker, query, [n.content for n in rerank_pool]
            )
            # Replace the query-cosine ranks for the reranked subset
            # with cross-encoder ranks. Items beyond RERANK_POOL_SIZE
            # keep their cosine rank.
            for new_rank, original_idx in enumerate(order, start=1):
                node = rerank_pool[original_idx]
                rank_query[node.id] = new_rank
            # Items at positions [RERANK_POOL_SIZE..k_recall) need
            # ranks shifted to live after the reranked block.
            for idx in range(len(rerank_pool), len(candidate_nodes)):
                rank_query[candidate_nodes[idx].id] = idx + 1
            used_reranker = True
        except Exception as exc:  # pragma: no cover - network error
            fallback_reason = (
                f"reranker call failed ({type(exc).__name__}); "
                "falling back to cosine rank"
            )
            logger.warning(
                "search_memories_with_focus reranker fallback: %s", exc
            )
    elif reranker is None:
        fallback_reason = (
            "no reranker configured; using cosine rank for query stage"
        )
    else:
        fallback_reason = (
            "reranker not configured (is_configured=False); using cosine rank"
        )

    # Focus cosine ranks across the candidate pool. Distance from the
    # focus vector ascending = best focus match first.
    use_focus = "focus" not in _disabled
    rank_focus: dict[uuid.UUID, int] = {}
    if use_focus:
        focus_scored = sorted(
            candidate_nodes,
            key=lambda n: _cosine_distance(focus_embedding, list(n.embedding))
            if n.embedding is not None
            else 1.0,
        )
        rank_focus = {
            node.id: idx + 1 for idx, node in enumerate(focus_scored)
        }

    # Domain ranks: when domain tags are provided, rank candidates by
    # overlap count (more matching domains = better rank). This becomes
    # a third RRF signal alongside query and focus.
    use_domain_boost = bool(domains) and domain_boost_weight > 0.0 and "domain" not in _disabled
    rank_domain: dict[uuid.UUID, int] = {}
    if use_domain_boost:
        domain_set = {d.lower() for d in domains}
        domain_scored = sorted(
            candidate_nodes,
            key=lambda n: len(
                domain_set & {d.lower() for d in (n.domains or [])}
            ),
            reverse=True,
        )
        rank_domain = {
            node.id: idx + 1 for idx, node in enumerate(domain_scored)
        }

    # Graph ranks: when graph neighbors were found, rank candidates by
    # hop distance (hop 1 = rank 1, hop 2 = rank N+1, etc.). Seeds
    # that appear in graph_neighbor_map also receive a graph rank.
    # Nodes not reachable via the graph get the miss rank.
    use_graph_boost = graph_depth > 0 and bool(graph_neighbor_map) and "graph" not in _disabled
    rank_graph: dict[uuid.UUID, int] = {}
    if use_graph_boost:
        # Group nodes by hop distance and assign sequential ranks,
        # closest hop first.
        max_hop = max(graph_neighbor_map.values())
        rank_counter = 1
        for hop in range(1, max_hop + 1):
            for nid, dist in graph_neighbor_map.items():
                if dist == hop:
                    rank_graph[nid] = rank_counter
                    rank_counter += 1

    # Keyword recall: run a parallel tsvector query to find candidates
    # that match query keywords but may have been missed by vector
    # recall (e.g., exact CLI commands, config keys, acronyms).
    use_keyword_boost = keyword_boost_weight > 0.0 and use_pgvector and "keyword" not in _disabled
    rank_keyword: dict[uuid.UUID, int] = {}
    if use_keyword_boost:
        try:
            tsquery = func.plainto_tsquery("english", query)
            keyword_stmt = (
                select(
                    MemoryNode,
                    func.ts_rank(MemoryNode.search_vector, tsquery).label("kw_rank"),
                )
                .where(*filters, MemoryNode.search_vector.op("@@")(tsquery))
                .order_by(sa_text("kw_rank DESC"))
                .limit(k_recall)
            )
            kw_result = await session.execute(keyword_stmt)
            kw_rows = kw_result.all()

            existing_ids = {node.id for node in candidate_nodes}
            for rank_idx, row in enumerate(kw_rows, start=1):
                kw_node = row[0]
                rank_keyword[kw_node.id] = rank_idx
                if kw_node.id not in existing_ids:
                    candidate_nodes.append(kw_node)
                    existing_ids.add(kw_node.id)
        except Exception as exc:
            logger.warning("keyword recall failed, skipping: %s", exc)
            use_keyword_boost = False

    # RRF blend: rank_query carries the cross-encoder ranks (or
    # cosine fallback ranks); rank_focus carries the focus-cosine
    # ranks; rank_domain carries domain-overlap ranks (when active);
    # rank_graph carries graph proximity ranks (when active);
    # rank_keyword carries keyword match ranks (when active).
    # Boost weights are carved proportionally from query and focus
    # so all weights always sum to 1.0.
    effective_focus_weight = session_focus_weight if use_focus else 0.0
    base_q = 1.0 - effective_focus_weight
    weight_d = domain_boost_weight if use_domain_boost else 0.0
    weight_g = graph_boost_weight if use_graph_boost else 0.0
    weight_k = keyword_boost_weight if use_keyword_boost else 0.0
    carve_total = weight_d + weight_g + weight_k
    remaining = 1.0 - carve_total
    weight_q = remaining * base_q
    weight_f = remaining * effective_focus_weight

    blended_scores: list[tuple[MemoryNode, float]] = []
    for node in candidate_nodes:
        score_q = weight_q / (RRF_K + rank_query.get(node.id, k_recall + 1))
        score_f = weight_f / (
            RRF_K + rank_focus.get(node.id, k_recall + 1)
        )
        score_d = (
            weight_d / (RRF_K + rank_domain.get(node.id, k_recall + 1))
            if use_domain_boost
            else 0.0
        )
        score_g = (
            weight_g / (RRF_K + rank_graph.get(node.id, k_recall + 1))
            if use_graph_boost
            else 0.0
        )
        score_k = (
            weight_k / (RRF_K + rank_keyword.get(node.id, k_recall + 1))
            if use_keyword_boost
            else 0.0
        )
        blended_scores.append((node, score_q + score_f + score_d + score_g + score_k))
    blended_scores.sort(key=lambda pair: pair[1], reverse=True)
    blended_scores = await _expand_chunks_to_parents(blended_scores, session)

    top_nodes = [node for node, _ in blended_scores[:max_results]]
    if not top_nodes:
        return FocusedSearchResult(
            pivot_suggested=pivot_suggested,
            pivot_distance=pivot_distance,
            pivot_threshold=pivot_threshold,
            pivot_reason=pivot_reason,
            used_reranker=used_reranker,
            fallback_reason=fallback_reason,
        )

    # Bulk-query branch flags for the final result set.
    branch_flags = await _bulk_branch_flags([n.id for n in top_nodes], session)

    # Compute relevance_score from the original query cosine distance
    # so existing MCP-tool formatting (which prints relevance_score
    # rounded to 4 decimals) shows a meaningful number even when the
    # rerank reordered the list. relevance_score reflects raw query
    # affinity, not the RRF-blended rank.
    if use_pgvector:
        # Recompute query cosine distance per node for the relevance
        # score. The values were available in the original SQL row
        # tuples but we discarded them above; recomputing here keeps
        # the data flow simple and the cost is negligible (top-N
        # nodes only, in-process).
        query_dist_by_id: dict[uuid.UUID, float] = {}
        for node in top_nodes:
            if node.embedding is not None:
                query_dist_by_id[node.id] = _cosine_distance(
                    query_embedding, list(node.embedding)
                )
            else:
                query_dist_by_id[node.id] = 1.0
    else:
        # SQLite fallback: synthetic rank-based scores like search_memories.
        query_dist_by_id = {
            node.id: idx / max(1, len(top_nodes))
            for idx, node in enumerate(top_nodes)
        }

    formatted: list[tuple[MemoryNodeRead | MemoryNodeStub, float]] = []
    for node in top_nodes:
        relevance_score = max(0.0, 1.0 - query_dist_by_id[node.id])
        has_children, has_rationale, branch_count = branch_flags.get(
            node.id, (False, False, 0)
        )
        if node.weight >= weight_threshold:
            formatted.append(
                (
                    node_to_read(
                        node,
                        has_children=has_children,
                        has_rationale=has_rationale,
                        branch_count=branch_count,
                    ),
                    relevance_score,
                )
            )
        else:
            formatted.append(
                (
                    MemoryNodeStub(
                        id=node.id,
                        parent_id=node.parent_id,
                        stub=node.stub,
                        scope=node.scope,
                        weight=node.weight,
                        branch_type=node.branch_type,
                        has_children=has_children,
                        has_rationale=has_rationale,
                        content_type=node.content_type,
                        created_at=node.created_at,
                    ),
                    relevance_score,
                )
            )

    # Pattern detection: check for within-user topic clusters.
    # Only runs when owner_id is available (can't cluster without
    # knowing whose memories to check).
    pattern_signals: list[PatternSignal] = []
    if owner_id and use_pgvector:
        try:  # noqa: SIM105 -- suppress() can't capture the awaited result
            pattern_signals = await detect_patterns(
                query_embedding,
                session,
                owner_id=owner_id,
                tenant_id=tenant_id,
            )
        except Exception:
            pass  # pattern detection is best-effort

    return FocusedSearchResult(
        results=formatted,
        pivot_suggested=pivot_suggested,
        pivot_distance=pivot_distance,
        pivot_threshold=pivot_threshold,
        pivot_reason=pivot_reason,
        used_reranker=used_reranker,
        fallback_reason=fallback_reason,
        graph_neighbors_added=graph_neighbors_added,
        graph_fallback_reason=graph_fallback_reason,
        keyword_matches=len(rank_keyword),
        pattern_signals=pattern_signals,
        disabled_signals=_disabled,
    )


async def get_memory_history(
    memory_id: uuid.UUID,
    session: AsyncSession,
    *,
    tenant_id: str,
    max_versions: int = 20,
    offset: int = 0,
) -> dict:
    """Build a paginated version history for a memory.

    Walks the version chain in both directions from `memory_id`, so callers
    can pass any version ID (oldest, newest, or middle) and get back the
    full chain. Returns a dict with:
      - versions: list[MemoryVersionInfo] (newest-first, paginated)
      - total_versions: int (total count in the chain)
      - has_more: bool (whether more versions exist beyond this page)
      - offset: int (the offset used)

    Tenant isolation: ``tenant_id`` is required. The version chain is
    tenant-bound (Phase 3 inherits tenant from the existing row on
    update, so all versions share the same tenant), but the entry-point
    lookup still filters by tenant so a cross-tenant caller cannot
    discover a history chain they have no business seeing. Cross-tenant
    requests raise ``MemoryNotFoundError`` -- the same semantics as a
    nonexistent row.
    """
    stmt = select(MemoryNode).where(
        MemoryNode.id == memory_id,
        MemoryNode.tenant_id == tenant_id,
    )
    result = await session.execute(stmt)
    node = result.scalar_one_or_none()

    if node is None:
        raise MemoryNotFoundError(memory_id)

    chain_nodes = await _walk_version_chain(node, session)
    all_versions: list[MemoryVersionInfo] = [
        MemoryVersionInfo(
            id=n.id,
            version=n.version,
            is_current=n.is_current,
            created_at=n.created_at,
            stub=n.stub,
            content=n.content,
            expires_at=n.expires_at,
        )
        for n in chain_nodes
    ]

    # Newest first (highest version number first)
    all_versions.sort(key=lambda v: v.version, reverse=True)

    total_versions = len(all_versions)
    page = all_versions[offset : offset + max_versions]
    has_more = (offset + max_versions) < total_versions

    return {
        "versions": page,
        "total_versions": total_versions,
        "has_more": has_more,
        "offset": offset,
    }


async def report_contradiction(
    memory_id: uuid.UUID,
    observed_behavior: str,
    confidence: float,
    reporter: str,
    session: AsyncSession,
) -> int:
    """Record a contradiction against a memory node.

    Inserts a row into contradiction_reports and returns the count of
    unresolved contradictions for this memory.

    Tenant isolation: the report inherits ``tenant_id`` from the
    contradicted memory. Cross-tenant contradiction reports are impossible
    by construction -- the tool layer calls ``authorize_read`` on the
    target memory before invoking this service, and ``authorize_read``
    rejects cross-tenant callers before they can load the memory. If the
    memory exists and is reachable, its tenant is the caller's tenant.
    """
    # Verify the memory exists and is not deleted. Reporting a contradiction
    # against a deleted memory is meaningless — there's no current version
    # for the curator to revise. Load the tenant_id off the row so we can
    # stamp it onto the contradiction report.
    stmt = select(MemoryNode.id, MemoryNode.tenant_id).where(
        MemoryNode.id == memory_id,
        MemoryNode.deleted_at.is_(None),
    )
    result = await session.execute(stmt)
    row = result.one_or_none()
    if row is None:
        raise MemoryNotFoundError(memory_id)
    memory_tenant_id = row.tenant_id

    # Insert the contradiction report
    report = ContradictionReport(
        memory_id=memory_id,
        observed_behavior=observed_behavior,
        confidence=confidence,
        reporter=reporter,
        tenant_id=memory_tenant_id,
    )
    session.add(report)
    await session.flush()

    # Count unresolved contradictions for this memory
    count_stmt = (
        select(func.count())
        .select_from(ContradictionReport)
        .where(
            ContradictionReport.memory_id == memory_id,
            ContradictionReport.resolved == False,  # noqa: E712
        )
    )
    count_result = await session.execute(count_stmt)
    count = count_result.scalar_one()

    await session.commit()
    return count


VALID_RESOLUTION_ACTIONS = frozenset({
    "accept_new", "keep_old", "mark_both_invalid", "manual_merge",
})


async def resolve_contradiction(
    contradiction_id: uuid.UUID,
    session: AsyncSession,
    *,
    resolution_action: str | None = None,
    actor_id: str | None = None,
) -> ContradictionReport:
    """Mark a contradiction report as resolved with an optional disposition.

    Args:
        contradiction_id: The report to resolve.
        session: Database session.
        resolution_action: One of accept_new, keep_old, mark_both_invalid,
            manual_merge. Optional for backward compatibility.
        actor_id: Identity of the resolver. Optional.

    Returns the updated ContradictionReport. Raises ContradictionNotFoundError
    if the ID doesn't exist, or ValueError if already resolved or if
    resolution_action is invalid.
    """
    if resolution_action is not None and resolution_action not in VALID_RESOLUTION_ACTIONS:
        raise ValueError(
            f"Invalid resolution_action '{resolution_action}'. "
            f"Must be one of: {', '.join(sorted(VALID_RESOLUTION_ACTIONS))}"
        )

    stmt = select(ContradictionReport).where(ContradictionReport.id == contradiction_id)
    result = await session.execute(stmt)
    report = result.scalar_one_or_none()

    if report is None:
        raise ContradictionNotFoundError(contradiction_id)

    if report.resolved:
        raise ValueError(f"Contradiction {contradiction_id} is already resolved")

    report.resolved = True
    report.resolved_at = datetime.now(UTC)
    report.resolution_action = resolution_action
    report.resolved_by = actor_id

    await session.commit()
    return report


# -- Internal helpers --


async def _walk_version_chain(
    start: MemoryNode,
    session: AsyncSession,
) -> list[MemoryNode]:
    """Return every node in `start`'s version chain (both directions).

    Walks `previous_version_id` backward from `start`, then iteratively
    walks forward via reverse-pointers (nodes whose previous_version_id
    is in the visited set) until the chain is closed. The result is
    deduplicated and order-independent; callers that need ordering should
    sort by `version`.

    Used by `delete_memory` (so an old version ID still soft-deletes the
    whole chain) and `get_memory_history` (so an agent can pass any
    version ID and get the full history). Pre-#49 the two used divergent
    walkers; this helper is the single source of truth.
    """
    visited: dict[uuid.UUID, MemoryNode] = {}
    current: MemoryNode | None = start

    # Backward walk along previous_version_id
    while current is not None and current.id not in visited:
        visited[current.id] = current
        if current.previous_version_id is not None:
            prev_stmt = select(MemoryNode).where(
                MemoryNode.id == current.previous_version_id
            )
            current = (await session.execute(prev_stmt)).scalar_one_or_none()
        else:
            current = None

    # Forward walk: pull in any node whose previous_version_id points at
    # something we've already visited. Repeat until no new nodes appear.
    changed = True
    while changed:
        changed = False
        fwd_stmt = select(MemoryNode).where(
            MemoryNode.previous_version_id.in_(list(visited.keys())),
            ~MemoryNode.id.in_(list(visited.keys())),
        )
        for fwd_node in (await session.execute(fwd_stmt)).scalars().all():
            visited[fwd_node.id] = fwd_node
            changed = True

    return list(visited.values())


async def _bulk_branch_flags(
    parent_ids: list[uuid.UUID],
    session: AsyncSession,
) -> dict[uuid.UUID, tuple[bool, bool, int]]:
    """Compute has_children, has_rationale, and branch_count for multiple parents.

    Returns a dict mapping parent_id -> (has_children, has_rationale, branch_count).
    Parents with no children are absent from the dict.
    """
    if not parent_ids:
        return {}

    stmt = (
        select(
            MemoryNode.parent_id,
            func.count(MemoryNode.id).label("child_count"),
            func.sum(func.cast(MemoryNode.branch_type == "rationale", Integer)).label("rationale_count"),
        )
        .where(MemoryNode.parent_id.in_(parent_ids), MemoryNode.deleted_at.is_(None))
        .group_by(MemoryNode.parent_id)
    )
    result = await session.execute(stmt)
    rows = result.all()

    return {
        row.parent_id: (
            row.child_count > 0,
            (row.rationale_count or 0) > 0,
            int(row.child_count or 0),
        )
        for row in rows
    }


async def _compute_branch_flags(
    node: MemoryNode,
    session: AsyncSession,
) -> tuple[bool, bool, int]:
    """Determine has_children, has_rationale, and branch_count for a node.

    Runs a single query for the count + rationale-presence flag instead of
    loading the child rows themselves -- read_memory no longer expands
    branches inline.
    """
    children_stmt = select(MemoryNode.branch_type).where(
        MemoryNode.parent_id == node.id, MemoryNode.deleted_at.is_(None)
    )
    children_result = await session.execute(children_stmt)
    rows = children_result.all()
    branch_count = len(rows)
    has_children = branch_count > 0
    has_rationale = any(row.branch_type == "rationale" for row in rows)
    return has_children, has_rationale, branch_count


def node_to_read(
    node: MemoryNode,
    has_children: bool,
    has_rationale: bool,
    branch_count: int = 0,
    current_version_id: uuid.UUID | None = None,
) -> MemoryNodeRead:
    """Convert a MemoryNode ORM instance to a MemoryNodeRead schema."""
    from memoryhub_core.services.temporal import compute_temporal_status

    relevant_until = getattr(node, "relevant_until", None)

    is_s3 = node.storage_type == "s3"
    content_truncated = is_s3
    full_available = is_s3 and bool(node.content_ref)

    return MemoryNodeRead(
        id=node.id,
        parent_id=node.parent_id,
        content=node.content,
        stub=node.stub,
        storage_type=node.storage_type,
        content_ref=node.content_ref,
        weight=node.weight,
        scope=node.scope,
        scope_id=node.scope_id,
        branch_type=node.branch_type,
        owner_id=node.owner_id,
        tenant_id=node.tenant_id,
        domains=node.domains,
        content_type=node.content_type,
        content_hash=getattr(node, 'content_hash', None),
        is_current=node.is_current,
        version=node.version,
        previous_version_id=node.previous_version_id,
        metadata_=node.metadata_,
        created_at=node.created_at,
        updated_at=node.updated_at,
        expires_at=node.expires_at,
        relevant_until=relevant_until,
        temporal_status=compute_temporal_status(relevant_until),
        has_children=has_children,
        has_rationale=has_rationale,
        branch_count=branch_count,
        current_version_id=current_version_id,
        content_truncated=content_truncated,
        full_available=full_available,
    )

"""One filter contract for the Memory browser: table, graph, timeline and export.

The page sends the same URL filters to every view. Building the SQL in one
place keeps the views consistent: a memory that a filter keeps in the table
is the memory the graph and the timeline draw.

Visibility comes first and filters only narrow it. Content filters (text,
semantic, domain, entity, near-duplicate) test only rows whose content the
viewer may read, so a filter never reveals what a hidden memory says.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta
from functools import lru_cache
from typing import Annotated, Literal

from fastapi import Depends, HTTPException, Query
from memoryhub_core.models.contradiction import ContradictionReport
from memoryhub_core.models.memory import MemoryNode, MemoryRelationship
from memoryhub_core.services.embeddings import HttpEmbeddingService
from sqlalchemy import String, and_, case, cast, false, func, literal, or_, select
from sqlalchemy.orm import aliased

from src.authorization import Access
from src.config import Settings, get_settings

logger = logging.getLogger(__name__)

Tab = Literal["current", "all", "quarantined", "deleted"]
Mode = Literal["semantic", "text", "metadata"]
FLAGS = frozenset({"contradicted", "has_branches", "near_duplicate"})

# Cosine similarity at or above which two current memories count as near
# duplicates. Curation flags at 0.80 and rejects higher; the browser flag is
# for the clear cases a person should merge or delete.
NEAR_DUPLICATE_SIMILARITY = 0.90
# Semantic browse keeps memories at least this similar to the query (or that
# match its text). Below it, MiniLM-class embeddings are mostly noise.
SEMANTIC_MIN_SIMILARITY = 0.30
# The near-duplicate facet compares every pair; above this many embedded rows
# the count is skipped (None) rather than slowing every page load.
NEAR_DUPLICATE_FACET_LIMIT = 2000


@lru_cache(maxsize=4)
def cached_embedding_service(url: str) -> HttpEmbeddingService:
    return HttpEmbeddingService(url)


def get_optional_embedding(
    settings: Annotated[Settings, Depends(get_settings)],
) -> HttpEmbeddingService | None:
    """Semantic browse degrades to text when no embedding service is configured."""
    return cached_embedding_service(settings.embedding_url) if settings.embedding_url else None


OptionalEmbeddingDep = Annotated[HttpEmbeddingService | None, Depends(get_optional_embedding)]


@dataclass
class BrowseQuery:
    tab: Tab = "current"
    q: str | None = None
    mode: Mode = "semantic"
    scope: list[str] = field(default_factory=list)
    actor: list[str] = field(default_factory=list)
    project: str | None = None
    domain: list[str] = field(default_factory=list)
    min_weight: float | None = None
    max_weight: float | None = None
    created_from: date | None = None
    created_to: date | None = None
    branch_type: str | None = None
    flag: list[str] = field(default_factory=list)
    entity: uuid.UUID | None = None

    def __post_init__(self) -> None:
        self.q = (self.q or "").strip() or None
        if (self.min_weight is not None and self.max_weight is not None
                and self.min_weight > self.max_weight):
            raise HTTPException(status_code=422, detail="Invalid weight range")
        if any(value not in FLAGS for value in self.flag):
            raise HTTPException(status_code=422, detail="Unsupported flag filter")


def browse_query(
    tab: Tab = "current",
    q: str | None = None,
    mode: Mode = "semantic",
    scope: list[str] | None = Query(None),
    actor: list[str] | None = Query(None),
    project: str | None = None,
    domain: list[str] | None = Query(None),
    min_weight: float | None = Query(None, ge=0, le=1),
    max_weight: float | None = Query(None, ge=0, le=1),
    created_from: date | None = None,
    created_to: date | None = None,
    branch_type: str | None = None,
    flag: list[str] | None = Query(None),
    entity: uuid.UUID | None = None,
) -> BrowseQuery:
    return BrowseQuery(
        tab=tab, q=q, mode=mode, scope=scope or [], actor=actor or [], project=project,
        domain=domain or [], min_weight=min_weight, max_weight=max_weight,
        created_from=created_from, created_to=created_to, branch_type=branch_type,
        flag=flag or [], entity=entity,
    )


BrowseQueryDep = Annotated[BrowseQuery, Depends(browse_query)]


@dataclass
class SearchPlan:
    """How the text box is applied: the mode actually used and the query vector."""
    mode: Literal["none", "semantic", "text", "metadata"] = "none"
    pattern: str | None = None
    vector: list[float] | None = None

    def distance(self, model=MemoryNode):
        return model.embedding.cosine_distance(self.vector) if self.vector is not None else None


async def plan_search(query: BrowseQuery, embedding: HttpEmbeddingService | None) -> SearchPlan:
    """Embed the query for semantic mode; fall back to text when that is not possible."""
    if not query.q:
        return SearchPlan()
    pattern = f"%{query.q}%"
    if query.mode == "metadata":
        return SearchPlan("metadata", pattern)
    if query.mode == "semantic" and embedding is not None:
        try:
            vector = await embedding.embed(query.q)
        except Exception:  # noqa: BLE001 - any embedding failure degrades to text
            logger.warning("Semantic browse fell back to text: embedding failed", exc_info=True)
        else:
            return SearchPlan("semantic", pattern, list(vector))
    return SearchPlan("text", pattern)


# --- visibility ----------------------------------------------------------

def _own_writes(access: Access, model=MemoryNode):
    """A person's own writes: personal memories and project memories they or their agents wrote."""
    authored = or_(model.owner_id.in_(access.identities), model.actor_id.in_(access.identities))
    return or_(
        and_(model.scope == "user", model.owner_id.in_(access.identities)),
        and_(model.scope == "project", model.scope_id.in_(access.human_projects), authored),
    )


def _restorable(access: Access, model=MemoryNode):
    """SQL twin of Access.can_delete: who deleted it may bring it back."""
    tenant = model.tenant_id == access.principal.tenant_id
    authored = or_(model.owner_id.in_(access.identities), model.actor_id.in_(access.identities))
    project_admin = and_(model.scope == "project", model.scope_id.in_(access.human_project_admins))
    if access.principal.role == "user":
        allowed = or_(
            and_(model.scope == "user", model.owner_id.in_(access.identities)),
            and_(model.scope == "project", model.scope_id.in_(access.human_projects),
                 or_(authored, project_admin)),
        )
        return and_(tenant, model.status == "active", allowed)
    allowed = []
    if "project" in access.moderation_scopes:
        allowed.append(and_(model.scope == "project", model.scope_id.in_(access.human_projects),
                            or_(authored, project_admin)))
    if "campaign" in access.moderation_scopes:
        allowed.append(and_(model.scope == "campaign", model.owner_id.in_(access.human_campaigns), authored))
    if "role" in access.moderation_scopes:
        allowed.append(and_(model.scope == "role", model.scope_id.in_(access.human_roles), authored))
    if "organizational" in access.moderation_scopes:
        allowed.append(and_(model.scope == "organizational", authored))
    return and_(tenant, model.status == "active", or_(*allowed) if allowed else false())


def can_restore(access: Access, node: MemoryNode) -> bool:
    """Python twin of _restorable for a deleted row."""
    return node.deleted_at is not None and node.tenant_id == access.principal.tenant_id and access.can_delete(node)


def _readable(access: Access, model=MemoryNode):
    """Active memories whose content this person reads (the user clause of the BFF)."""
    return and_(model.deleted_at.is_(None), access.clause(model)) if access.principal.role == "user" \
        else model.tenant_id == access.principal.tenant_id


def deleted_head(model=MemoryNode):
    """One row per delete: the newest version, not a branch deleted together with its parent."""
    newer = aliased(MemoryNode)
    parent = aliased(MemoryNode)
    return and_(
        ~select(newer.id).where(newer.previous_version_id == model.id).exists(),
        ~select(parent.id).where(
            parent.id == model.parent_id, parent.deleted_at == model.deleted_at,
        ).exists(),
    )


def tab_conditions(tab: str, model=MemoryNode) -> list:
    if tab == "current":
        return [model.deleted_at.is_(None), model.is_current.is_(True), model.status == "active"]
    if tab == "all":
        return [model.deleted_at.is_(None)]
    if tab == "quarantined":
        return [model.deleted_at.is_(None), model.status == "quarantined"]
    if tab == "deleted":
        return [model.deleted_at.is_not(None), deleted_head(model)]
    raise HTTPException(status_code=422, detail="Invalid memory state")


def state_clause(access: Access, tab: str, model=MemoryNode):
    """Rows this person may list in a tab.

    Admins list every tenant row (personal ones as metadata). A user lists
    what they read, their own quarantined writes, and deletes they may undo.
    """
    tenant = model.tenant_id == access.principal.tenant_id
    if access.principal.role != "user":
        return tenant
    if tab == "quarantined":
        return and_(tenant, model.deleted_at.is_(None), model.status == "quarantined", _own_writes(access, model))
    if tab == "deleted":
        return and_(tenant, model.deleted_at.is_not(None), _restorable(access, model))
    return and_(tenant, _readable(access, model))


def content_clause(access: Access, tab: str, model=MemoryNode):
    """Rows whose content a filter may test: never a redacted row."""
    if access.principal.role == "user":
        return state_clause(access, tab, model)
    return and_(access.content_clause(model), model.deleted_at.is_(None))


def can_see_content(access: Access, node: MemoryNode) -> bool:
    """Python twin of content_clause for one listed row."""
    if node.tenant_id != access.principal.tenant_id:
        return False
    if access.principal.role == "user":
        if node.deleted_at is not None:
            return can_restore(access, node)
        if node.status == "quarantined":
            authored = node.owner_id in access.identities or node.actor_id in access.identities
            return (node.scope == "user" and node.owner_id in access.identities) or (
                node.scope == "project" and node.scope_id in access.human_projects and authored)
        return access.can_read(node)
    return node.deleted_at is None and not access.hides_content(node) and (
        (node.scope == "organizational" and "organizational" in access.moderation_scopes)
        or (node.scope == "project" and node.scope_id in access.human_projects
            and "project" in access.moderation_scopes)
        or (node.scope == "role" and node.scope_id in access.human_roles
            and "role" in access.moderation_scopes)
        or (node.scope == "campaign" and node.owner_id in access.human_campaigns
            and "campaign" in access.moderation_scopes)
    )


def can_list(access: Access, node: MemoryNode) -> bool:
    """A row that passed state_clause in SQL, checked again in Python before it leaves."""
    if node.tenant_id != access.principal.tenant_id:
        return False
    return access.principal.role == "admin" or can_see_content(access, node)


# --- near duplicates -----------------------------------------------------

def _comparable(access: Access, model):
    """What a memory is compared with: current, active memories the viewer reads."""
    return and_(model.is_current.is_(True), model.status == "active", model.deleted_at.is_(None),
                model.embedding.is_not(None), content_clause(access, "current", model))


def near_duplicate_exists(access: Access, tab: str, model=MemoryNode):
    other = aliased(MemoryNode)
    return and_(
        model.embedding.is_not(None), content_clause(access, tab, model),
        select(other.id).where(
            other.id != model.id, _comparable(access, other),
            other.embedding.cosine_distance(model.embedding) <= 1 - NEAR_DUPLICATE_SIMILARITY,
        ).exists(),
    )


def nearest_similarity(access: Access, node_id: uuid.UUID, node_embedding):
    """Scalar subquery: the highest similarity of one memory to another comparable one."""
    other = aliased(MemoryNode)
    return select(func.max(1 - other.embedding.cosine_distance(node_embedding))).where(
        other.id != node_id, _comparable(access, other),
    ).scalar_subquery()


# --- the filter set ------------------------------------------------------

def conditions(access: Access, query: BrowseQuery, plan: SearchPlan, model=MemoryNode) -> list:
    """Visibility, tab and every URL filter, in SQL."""
    tenant = access.principal.tenant_id
    where = [model.tenant_id == tenant, state_clause(access, query.tab, model),
             *tab_conditions(query.tab, model)]
    content = content_clause(access, query.tab, model)
    if query.scope:
        where.append(model.scope.in_(query.scope))
    if query.actor:
        where.append(model.actor_id.in_(query.actor))
    if query.project:
        where += [model.scope == "project", model.scope_id == query.project]
    if query.domain:
        where += [content, model.domains.overlap(query.domain)]
    if query.min_weight is not None:
        where.append(model.weight >= query.min_weight)
    if query.max_weight is not None:
        where.append(model.weight <= query.max_weight)
    if query.created_from:
        where.append(model.created_at >= query.created_from)
    if query.created_to:
        where.append(model.created_at < query.created_to + timedelta(days=1))
    if query.branch_type:
        child = aliased(MemoryNode)
        where.append(select(child.id).where(
            child.parent_id == model.id, child.tenant_id == tenant,
            child.branch_type == query.branch_type, child.deleted_at.is_(None),
            access.clause(child),
        ).exists())
    if "contradicted" in query.flag:
        where += [content, select(ContradictionReport.id).where(
            ContradictionReport.memory_id == model.id,
            ContradictionReport.tenant_id == tenant,
            ContradictionReport.resolved.is_(False),
        ).exists()]
    if "has_branches" in query.flag:
        child = aliased(MemoryNode)
        where.append(select(child.id).where(
            child.parent_id == model.id, child.tenant_id == tenant,
            child.deleted_at.is_(None), access.clause(child),
        ).exists())
    if "near_duplicate" in query.flag:
        where.append(near_duplicate_exists(access, query.tab, model))
    if query.entity:
        where += [content, select(MemoryRelationship.id).where(
            MemoryRelationship.source_id == model.id,
            MemoryRelationship.target_id == query.entity,
            MemoryRelationship.tenant_id == tenant,
            MemoryRelationship.relationship_type == "mentions",
            MemoryRelationship.valid_until.is_(None),
        ).exists()]
    if plan.mode != "none":
        metadata = or_(cast(model.id, String).ilike(plan.pattern), model.owner_id.ilike(plan.pattern))
        text = and_(content, or_(model.content.ilike(plan.pattern), model.stub.ilike(plan.pattern)))
        if plan.mode == "metadata":
            where.append(metadata)
        elif plan.mode == "text":
            where.append(or_(metadata, text))
        else:
            semantic = and_(content, model.embedding.is_not(None),
                            plan.distance(model) <= 1 - SEMANTIC_MIN_SIMILARITY)
            where.append(or_(metadata, text, semantic))
    return where


def relevance_order(plan: SearchPlan, model=MemoryNode) -> list:
    """Best match first: semantic distance, or a match in the summary before one in the body."""
    if plan.mode == "semantic":
        return [plan.distance(model).asc().nulls_last(), model.updated_at.desc()]
    if plan.mode in ("text", "metadata"):
        return [case((model.stub.ilike(plan.pattern), 0), else_=1).asc(), model.updated_at.desc()]
    return [model.updated_at.desc()]


def similarity_column(plan: SearchPlan, access: Access, tab: str, model=MemoryNode):
    """The score shown per row: similarity to the query, only where content is readable."""
    if plan.mode != "semantic":
        return literal(None)
    return case((content_clause(access, tab, model), 1 - plan.distance(model)), else_=None)

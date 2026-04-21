"""Consolidated graph management tool.

Replaces create_relationship, get_relationships, and get_similar_memories with
a single action-dispatched tool following the manage_project pattern.
"""

import logging
import uuid
from types import SimpleNamespace
from typing import Annotated, Any

from fastmcp import Context
from fastmcp.exceptions import ToolError
from pydantic import Field, ValidationError

from src.core.app import mcp
from src.core.authz import (
    AuthenticationError,
    authorize_read,
    get_claims_from_context,
    get_tenant_filter,
)
from src.tools._deps import get_db_session, release_db_session

from memoryhub_core.models.schemas import RelationshipCreate, RelationshipType
from memoryhub_core.services.campaign import get_campaigns_for_project
from memoryhub_core.services.curation.similarity import get_similar_memories as get_similar_memories_service
from memoryhub_core.services.exceptions import MemoryNotFoundError
from memoryhub_core.services.graph import (
    create_relationship as create_relationship_service,
    get_relationships as get_relationships_service,
    trace_provenance,
)
from memoryhub_core.services.memory import read_memory as read_memory_service
from memoryhub_core.services.project import get_projects_for_user
from memoryhub_core.services.role import get_roles_for_user

logger = logging.getLogger(__name__)

_VALID_TYPES = [t.value for t in RelationshipType]
_VALID_DIRECTIONS = ("outgoing", "incoming", "both")
_VALID_ACTIONS = {"create_relationship", "get_relationships", "get_similar"}


def _require_param(action: str, name: str, value: str | None) -> str:
    """Validate that a required string parameter is present for the given action."""
    if not value or not value.strip():
        raise ToolError(
            f"action='{action}' requires {name}. "
            f"Example: manage_graph(action='{action}', {name}='...')"
        )
    return value.strip()


@mcp.tool(
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    }
)
async def manage_graph(
    action: Annotated[
        str,
        Field(
            description=(
                "The graph operation to perform. One of: "
                "'create_relationship' (link two memory nodes with a typed edge), "
                "'get_relationships' (query edges for a node, with optional provenance tracing), "
                "'get_similar' (find near-duplicate memories by cosine similarity)."
            ),
        ),
    ],
    # ── create_relationship params ───────────────────────────────────────────
    source_id: Annotated[
        str | None,
        Field(
            description=(
                "action='create_relationship': UUID of the source memory node "
                "(the 'from' end of the edge). Required for create_relationship."
            ),
        ),
    ] = None,
    target_id: Annotated[
        str | None,
        Field(
            description=(
                "action='create_relationship': UUID of the target memory node "
                "(the 'to' end of the edge). Required for create_relationship."
            ),
        ),
    ] = None,
    relationship_type: Annotated[
        str | None,
        Field(
            description=(
                "action='create_relationship': Type of relationship. Must be one of: "
                "derived_from, supersedes, conflicts_with, related_to. "
                "Required for create_relationship. "
                "action='get_relationships': Filter by this type; omit to return all types."
            ),
        ),
    ] = None,
    metadata: Annotated[
        dict[str, Any] | None,
        Field(
            description=(
                "action='create_relationship': Optional key-value pairs to attach "
                "to the relationship edge. To suggest a merge, pass "
                "relationship_type='conflicts_with' with "
                "metadata={'merge_suggested': true, 'reasoning': '...'}."
            ),
        ),
    ] = None,
    # ── get_relationships params ─────────────────────────────────────────────
    node_id: Annotated[
        str | None,
        Field(
            description=(
                "action='get_relationships': UUID of the memory node to query "
                "relationships for. Required for get_relationships."
            ),
        ),
    ] = None,
    direction: Annotated[
        str,
        Field(
            description=(
                "action='get_relationships': Which edges to return — "
                "'outgoing' (this node is the source), "
                "'incoming' (this node is the target), or 'both'. Default: 'both'."
            ),
        ),
    ] = "both",
    include_provenance: Annotated[
        bool,
        Field(
            description=(
                "action='get_relationships': If true, follows derived_from edges "
                "backward from this node to build a provenance chain showing which "
                "source memories this node was derived from."
            ),
        ),
    ] = False,
    # ── get_similar params ───────────────────────────────────────────────────
    memory_id: Annotated[
        str | None,
        Field(
            description=(
                "action='get_similar': UUID of the memory to find similar memories "
                "for. Required for get_similar."
            ),
        ),
    ] = None,
    threshold: Annotated[
        float,
        Field(
            description=(
                "action='get_similar': Minimum cosine similarity (0.0–1.0). "
                "Default: 0.80."
            ),
            ge=0.0,
            le=1.0,
        ),
    ] = 0.80,
    max_results: Annotated[
        int,
        Field(
            description="action='get_similar': Maximum results per page. Default: 10.",
            ge=1,
            le=50,
        ),
    ] = 10,
    offset: Annotated[
        int,
        Field(
            description="action='get_similar': Pagination offset. Default: 0.",
            ge=0,
        ),
    ] = 0,
    # ── shared params ────────────────────────────────────────────────────────
    project_id: Annotated[
        str | None,
        Field(
            description=(
                "Your project identifier. Required when any memory node involved "
                "has campaign scope — used to verify your project is enrolled in "
                "the campaign."
            ),
        ),
    ] = None,
    ctx: Context = None,
) -> dict[str, Any]:
    """Manage memory graph relationships and similarity.

    Three actions in one tool:

    create_relationship — Link two memory nodes with a typed directed edge.
      Requires: source_id, target_id, relationship_type.
      Optional: metadata, project_id (when either node is campaign-scoped).
      Relationships are immutable (create or delete only).
      Edge direction for derived_from: source is the derived node, target is
      the origin. To suggest a merge, use relationship_type='conflicts_with'
      with metadata={'merge_suggested': true, 'reasoning': '...'}.
      Returns the created relationship with its ID, timestamps, and node stubs.

    get_relationships — Query all edges for a memory node.
      Requires: node_id.
      Optional: relationship_type (filter), direction, include_provenance,
        project_id (when any related node is campaign-scoped).
      With include_provenance=true, also returns a provenance_chain tracing
      derived_from ancestry backward. Inaccessible related nodes are omitted
      and counted in omitted_count.
      Returns: relationships list, count, optional provenance_chain.

    get_similar — Find near-duplicate memories by cosine similarity.
      Requires: memory_id.
      Optional: threshold (default 0.80), max_results (default 10), offset,
        project_id (when the source memory is campaign-scoped).
      Use this when write_memory reports similar_count > 0. Page through
      results with offset to avoid context bloat.
      Returns: paged results with memory stubs and similarity scores.
    """
    if action not in _VALID_ACTIONS:
        raise ToolError(
            f"Invalid action '{action}'. Must be one of: "
            f"{', '.join(sorted(_VALID_ACTIONS))}."
        )

    try:
        claims = get_claims_from_context()
    except AuthenticationError as exc:
        raise ToolError(str(exc)) from exc
    tenant = get_tenant_filter(claims)

    gen = None
    try:
        session, gen = await get_db_session()

        if action == "create_relationship":
            return await _handle_create_relationship(
                ctx, claims, tenant, session,
                source_id, target_id, relationship_type, metadata, project_id,
            )
        elif action == "get_relationships":
            return await _handle_get_relationships(
                ctx, claims, tenant, session,
                node_id, relationship_type, direction, include_provenance, project_id,
            )
        else:  # get_similar
            return await _handle_get_similar(
                ctx, claims, tenant, session,
                memory_id, threshold, max_results, offset, project_id,
            )

    except ToolError:
        raise
    except Exception as exc:
        logger.error("manage_graph(%s) failed: %s", action, exc, exc_info=True)
        raise ToolError(
            f"Failed to execute action '{action}'. See server logs for details."
        ) from exc
    finally:
        if gen is not None:
            await release_db_session(gen)


# ── action handlers ──────────────────────────────────────────────────────────

async def _handle_create_relationship(
    ctx: Context | None,
    claims: dict[str, Any],
    tenant: str,
    session: Any,
    source_id: str | None,
    target_id: str | None,
    relationship_type: str | None,
    metadata: dict[str, Any] | None,
    project_id: str | None,
) -> dict[str, Any]:
    """Create a directed relationship between two memory nodes."""
    source_id = _require_param("create_relationship", "source_id", source_id)
    target_id = _require_param("create_relationship", "target_id", target_id)
    relationship_type = _require_param(
        "create_relationship", "relationship_type", relationship_type
    )

    if relationship_type not in _VALID_TYPES:
        raise ToolError(
            f"Invalid relationship_type {relationship_type!r}. "
            f"Must be one of: {', '.join(_VALID_TYPES)}."
        )

    try:
        parsed_source_id = uuid.UUID(source_id)
    except ValueError:
        raise ToolError(
            f"Invalid source_id format: {source_id!r}. Must be a valid UUID."
        )

    try:
        parsed_target_id = uuid.UUID(target_id)
    except ValueError:
        raise ToolError(
            f"Invalid target_id format: {target_id!r}. Must be a valid UUID."
        )

    if parsed_source_id == parsed_target_id:
        raise ToolError(
            "source_id and target_id must be different — self-referential edges are not allowed."
        )

    if ctx:
        await ctx.info(
            f"Creating {relationship_type!r} relationship {source_id} -> {target_id}"
        )

    # Resolve campaign membership once — used for both nodes if either is
    # campaign-scoped.
    campaign_ids: set[str] | None = None

    # Verify read access to both nodes. The tenant filter on read_memory makes
    # a cross-tenant ID indistinguishable from a nonexistent row, so a
    # cross-tenant attempt is rejected as "not found" rather than leaking
    # tenant information in the error message.
    for node_id_parsed, label in [
        (parsed_source_id, "source_id"),
        (parsed_target_id, "target_id"),
    ]:
        try:
            node = await read_memory_service(node_id_parsed, session, tenant_id=tenant)
        except MemoryNotFoundError:
            raise ToolError(f"Memory node {node_id_parsed} not found.")
        if node.scope == "campaign" and campaign_ids is None:
            if not project_id:
                raise ToolError(
                    f"project_id is required when {label} is a campaign-scoped memory. "
                    "Set it to your project identifier so enrollment can be verified."
                )
            campaign_ids = await get_campaigns_for_project(session, project_id, tenant)
        if not authorize_read(claims, node, campaign_ids=campaign_ids):
            raise ToolError(f"Not authorized to access {label} ({node_id_parsed}).")

    try:
        rel_create = RelationshipCreate(
            source_id=parsed_source_id,
            target_id=parsed_target_id,
            relationship_type=relationship_type,
            created_by=claims["sub"],
            metadata=metadata,
        )
    except ValidationError as exc:
        errors = exc.errors()
        messages = [f"  - {e['loc'][-1]}: {e['msg']}" for e in errors]
        raise ToolError("Parameter validation failed:\n" + "\n".join(messages)) from exc

    result = await create_relationship_service(rel_create, session)
    return result.model_dump(mode="json")


async def _handle_get_relationships(
    ctx: Context | None,
    claims: dict[str, Any],
    tenant: str,
    session: Any,
    node_id: str | None,
    relationship_type: str | None,
    direction: str,
    include_provenance: bool,
    project_id: str | None,
) -> dict[str, Any]:
    """Return graph edges for a memory node, with optional provenance tracing."""
    node_id = _require_param("get_relationships", "node_id", node_id)

    try:
        parsed_node_id = uuid.UUID(node_id)
    except ValueError:
        raise ToolError(
            f"Invalid node_id format: {node_id!r}. Must be a valid UUID."
        )

    if direction not in _VALID_DIRECTIONS:
        raise ToolError(
            f"Invalid direction {direction!r}. "
            f"Must be one of: {', '.join(_VALID_DIRECTIONS)}."
        )

    if relationship_type is not None and relationship_type not in _VALID_TYPES:
        raise ToolError(
            f"Invalid relationship_type {relationship_type!r}. "
            f"Must be one of: {', '.join(_VALID_TYPES)}."
        )

    if ctx:
        await ctx.info(f"Getting {direction} relationships for {node_id}")

    try:
        rels = await get_relationships_service(
            parsed_node_id,
            session,
            tenant_id=tenant,
            relationship_type=relationship_type,
            direction=direction,
        )
    except MemoryNotFoundError:
        raise ToolError(f"Memory node {node_id} not found.")

    result: dict[str, Any] = {
        "relationships": [r.model_dump(mode="json") for r in rels],
        "count": len(rels),
    }

    # Resolve RBAC contexts once for post-fetch filtering.
    campaign_ids: set[str] | None = None
    if project_id:
        campaign_ids = await get_campaigns_for_project(session, project_id, tenant)

    project_ids: set[str] = await get_projects_for_user(session, claims["sub"])
    role_names: set[str] = await get_roles_for_user(
        session, claims["sub"], tenant, claims=claims,
    )

    # Post-fetch RBAC filter: drop relationships where the caller cannot read
    # either endpoint.
    original_rels = result["relationships"]
    accessible_rels = []
    for rel in original_rels:
        for node_key in ("source_node", "target_node"):
            node_data = rel.get(node_key)
            if node_data and isinstance(node_data, dict):
                proxy = SimpleNamespace(
                    scope=node_data.get("scope", "user"),
                    owner_id=node_data.get("owner_id", ""),
                    tenant_id=node_data.get("tenant_id", "default"),
                )
                if not authorize_read(
                    claims, proxy,
                    campaign_ids=campaign_ids,
                    project_ids=project_ids,
                    role_names=role_names,
                ):
                    break
        else:
            accessible_rels.append(rel)

    omitted = len(original_rels) - len(accessible_rels)
    result["relationships"] = accessible_rels
    result["count"] = len(accessible_rels)
    if omitted > 0:
        result["omitted_count"] = omitted

    if include_provenance:
        provenance_steps = await trace_provenance(parsed_node_id, session)
        accessible_steps = []
        for step in provenance_steps:
            node_dump = step["node"].model_dump(mode="json")
            proxy = SimpleNamespace(
                scope=node_dump.get("scope", "user"),
                owner_id=node_dump.get("owner_id", ""),
                tenant_id=node_dump.get("tenant_id", "default"),
            )
            if authorize_read(
                claims, proxy,
                campaign_ids=campaign_ids,
                project_ids=project_ids,
                role_names=role_names,
            ):
                accessible_steps.append({
                    "hop": step["hop"],
                    "node": node_dump,
                    "relationship": step["relationship"].model_dump(mode="json"),
                })
        result["provenance_chain"] = accessible_steps

    return result


async def _handle_get_similar(
    ctx: Context | None,
    claims: dict[str, Any],
    tenant: str,
    session: Any,
    memory_id: str | None,
    threshold: float,
    max_results: int,
    offset: int,
    project_id: str | None,
) -> dict[str, Any]:
    """Find near-duplicate memories by cosine similarity."""
    memory_id = _require_param("get_similar", "memory_id", memory_id)

    try:
        parsed_memory_id = uuid.UUID(memory_id)
    except ValueError:
        raise ToolError(
            f"Invalid memory_id format: {memory_id!r}. Must be a valid UUID."
        )

    if ctx:
        await ctx.info(f"Finding memories similar to {memory_id}")

    # Authorize caller against the source memory. The similarity service
    # restricts results to the same (owner_id, scope, tenant_id) as the
    # source, so authorizing the source is sufficient for all results.
    try:
        source = await read_memory_service(parsed_memory_id, session, tenant_id=tenant)
    except MemoryNotFoundError:
        raise ToolError(f"Memory {memory_id} not found.")

    campaign_ids: set[str] | None = None
    if source.scope == "campaign":
        if not project_id:
            raise ToolError(
                "project_id is required when finding similar memories for a "
                "campaign-scoped memory. Set it to your project identifier "
                "so enrollment can be verified."
            )
        campaign_ids = await get_campaigns_for_project(session, project_id, tenant)

    project_ids: set[str] | None = None
    if source.scope == "project":
        project_ids = await get_projects_for_user(session, claims["sub"])

    role_names: set[str] | None = None
    if source.scope == "role":
        role_names = await get_roles_for_user(
            session, claims["sub"], tenant, claims=claims,
        )

    if not authorize_read(
        claims, source,
        campaign_ids=campaign_ids,
        project_ids=project_ids,
        role_names=role_names,
    ):
        raise ToolError(f"Not authorized to read memory {memory_id}.")

    result = await get_similar_memories_service(
        parsed_memory_id,
        session,
        tenant_id=tenant,
        threshold=threshold,
        max_results=max_results,
        offset=offset,
    )

    # Serialize UUIDs in results for JSON.
    for item in result.get("results", []):
        if "id" in item:
            item["id"] = str(item["id"])

    return result

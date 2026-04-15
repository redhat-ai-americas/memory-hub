"""Create a new memory node or branch in the memory tree."""

import logging
import uuid
from typing import Annotated, Any

from fastmcp import Context
from fastmcp.exceptions import ToolError
from pydantic import Field, ValidationError

logger = logging.getLogger(__name__)

from src.core.app import mcp
from src.core.authz import (
    AuthenticationError,
    PROJECT_ISOLATION_ENABLED,
    ROLE_ISOLATION_ENABLED,
    authorize_write,
    get_claims_from_context,
    get_tenant_filter,
)
from src.tools._deps import (
    get_db_session,
    get_embedding_service,
    get_s3_adapter,
    release_db_session,
)
from src.tools._push_helpers import broadcast_after_write

from memoryhub_core.models.schemas import MemoryNodeCreate
from memoryhub_core.services.campaign import get_campaigns_for_project
from memoryhub_core.services.project import get_projects_for_user
from memoryhub_core.services.role import get_roles_for_user
from memoryhub_core.services.exceptions import MemoryAccessDeniedError, MemoryNotFoundError
from memoryhub_core.services.memory import create_memory
from memoryhub_core.services.push_broadcast import build_uri_only_notification


async def _get_cache_impact(tenant_id: str, owner_id: str) -> dict:
    """Read compilation state to estimate the cache cost of a forced write."""
    from memoryhub_core.services.compilation import CompilationEpoch
    from memoryhub_core.services.valkey_client import ValkeyUnavailableError

    try:
        from memoryhub_core.services.valkey_client import get_valkey_client
        valkey = get_valkey_client()
        data = await valkey.read_compilation(tenant_id, owner_id)
        if data is None:
            return {"compiled_count": 0, "will_recompile": True}
        epoch = CompilationEpoch.from_dict(data)
        return {"compiled_count": len(epoch.ordered_ids), "will_recompile": True}
    except (ValkeyUnavailableError, Exception):
        return {"compiled_count": None, "will_recompile": True}


@mcp.tool(
    annotations={
        "readOnlyHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    }
)
async def write_memory(
    content: Annotated[
        str,
        Field(description="The memory text. Should be clear and self-contained."),
    ],
    scope: Annotated[
        str,
        Field(
            description=(
                "One of: user, project, campaign, role, organizational, enterprise. "
                "Most agent-created memories are 'user' scope. "
                "For campaign scope, set owner_id to the campaign UUID and "
                "provide project_id for enrollment verification."
            ),
        ),
    ],
    owner_id: Annotated[
        str | None,
        Field(
            description=(
                "The user, project, or org this memory belongs to. "
                "For user-scope, this is the user ID. "
                "Omit to use your authenticated user_id (requires register_session)."
            ),
        ),
    ] = None,
    weight: Annotated[
        float,
        Field(
            description=(
                "Injection priority from 0.0 to 1.0. High-weight (0.8-1.0) "
                "memories get full content injected. Default 0.7."
            ),
        ),
    ] = 0.7,
    parent_id: Annotated[
        str | None,
        Field(
            description=(
                "UUID of the parent memory node when creating a branch. "
                "Omit for root-level memories."
            ),
        ),
    ] = None,
    branch_type: Annotated[
        str | None,
        Field(
            description=(
                "Required when parent_id is set. Common types: rationale, "
                "provenance, description, evidence, approval."
            ),
        ),
    ] = None,
    metadata: Annotated[
        dict[str, Any] | None,
        Field(
            description="Arbitrary key-value pairs for tags, source references, etc.",
        ),
    ] = None,
    domains: Annotated[
        list[str] | None,
        Field(
            description=(
                "Crosscutting knowledge domain tags (e.g., 'React', 'Spring Boot', "
                "'CORS'). Improves retrieval for domain-relevant queries. Optional "
                "at any scope."
            ),
        ),
    ] = None,
    project_id: Annotated[
        str | None,
        Field(
            description=(
                "Your project identifier. Required when scope is 'project' or "
                "'campaign'. For project scope, the memory is tagged to this project "
                "and only project members can read it. For campaign scope, used to "
                "verify your project is enrolled in the campaign."
            ),
        ),
    ] = None,
    force: Annotated[
        bool,
        Field(
            description=(
                "When True, bypass near-duplicate and exact-duplicate similarity "
                "gates and write the memory regardless of similarity to existing "
                "memories. Regex rules (secrets, PII) are never bypassed. Use when "
                "you have confirmed the new memory provides value beyond the "
                "existing one."
            ),
        ),
    ] = False,
    ctx: Context = None,
) -> dict[str, Any]:
    """Create a new memory node or branch in the memory tree.

    Records preferences, facts, project context, rationale, and other knowledge.
    For user-scope memories, the write happens immediately. For higher scopes
    (organizational, enterprise), the write is queued for curator review.

    Returns the created memory node with its generated ID, stub text, and timestamp,
    along with curation metadata. If curation detects a near-duplicate or exact
    duplicate, the memory is NOT written and the response has memory=null with
    curation.gated=true, including the existing memory's ID, stub, and cache
    impact information. To override, retry with force=true.

    If the write is blocked by a regex curation rule (e.g., secrets detected),
    a ToolError is raised with a message starting with "Curation rule blocked".
    """
    if ctx:
        await ctx.info("Creating memory node")

    try:
        claims = get_claims_from_context()
    except AuthenticationError as exc:
        raise ToolError(str(exc)) from exc

    if owner_id is None:
        owner_id = claims["sub"]

    # Tool-layer writes always create new memories in the caller's own
    # tenant. Phase 2 wired this into authorize_write; Phase 3 plumbs the
    # same tenant_id through the service-layer insert so every row is
    # stamped explicitly (rather than relying on the column's
    # server_default of "default").
    write_tenant_id = get_tenant_filter(claims)

    # Resolve campaign membership when writing to campaign scope.
    campaign_ids: set[str] | None = None
    if scope == "campaign":
        if not project_id:
            raise ToolError(
                "project_id is required when scope is 'campaign'. "
                "Set it to your project identifier so enrollment can be verified."
            )
        session_for_campaign, gen_for_campaign = await get_db_session()
        try:
            campaign_ids = await get_campaigns_for_project(
                session_for_campaign, project_id, write_tenant_id,
            )
        finally:
            await release_db_session(gen_for_campaign)

    # Resolve project membership when writing to project scope.
    project_ids: set[str] | None = None
    scope_id_value: str | None = None
    if scope == "project":
        if not project_id:
            raise ToolError(
                "project_id is required when scope is 'project'. "
                "Set it to your project identifier from your agent configuration."
            )
        scope_id_value = project_id
        if PROJECT_ISOLATION_ENABLED:
            session_for_project, gen_for_project = await get_db_session()
            try:
                project_ids = await get_projects_for_user(
                    session_for_project, claims["sub"],
                )
            finally:
                await release_db_session(gen_for_project)
            if not project_ids or project_id not in project_ids:
                raise ToolError(
                    f"Not a member of project '{project_id}'. "
                    "You can only write project-scoped memories for projects you belong to."
                )

    # Resolve role assignments when writing to role scope.
    # Role writes require service identity (checked by authorize_write).
    # TODO: Add a role_name parameter when the curator agent is built;
    # for now role-scope writes set scope_id via the curator's own logic.
    role_names: set[str] | None = None
    if scope == "role" and ROLE_ISOLATION_ENABLED:
        session_for_roles, gen_for_roles = await get_db_session()
        try:
            role_names = await get_roles_for_user(
                session_for_roles, claims["sub"], write_tenant_id, claims=claims,
            )
        finally:
            await release_db_session(gen_for_roles)

    if not authorize_write(
        claims, scope, owner_id, write_tenant_id,
        campaign_ids=campaign_ids,
        project_ids=project_ids,
        role_names=role_names,
        scope_id=scope_id_value,
    ):
        raise ToolError(
            f"Not authorized to write {scope}-scope memory for owner '{owner_id}'."
        )

    # Validate branch_type / parent_id pairing in both directions:
    # - parent_id without branch_type: branch with no kind label
    # - branch_type without parent_id: orphan branch with no parent to attach to
    if parent_id is not None and branch_type is None:
        raise ToolError(
            "branch_type is required when parent_id is set. "
            "Common types: rationale, provenance, description, evidence."
        )
    if branch_type is not None and parent_id is None:
        raise ToolError(
            "parent_id is required when branch_type is set. "
            "A branch must attach to a parent memory; omit branch_type "
            "to create a root-level memory instead."
        )

    # Parse parent_id to UUID if provided
    parsed_parent_id: uuid.UUID | None = None
    if parent_id is not None:
        try:
            parsed_parent_id = uuid.UUID(parent_id)
        except ValueError:
            raise ToolError(
                f"Invalid parent_id format: '{parent_id}'. Must be a valid UUID."
            )

    # Build the create schema with validation
    try:
        node_create = MemoryNodeCreate(
            content=content,
            scope=scope,
            weight=weight,
            owner_id=owner_id,
            parent_id=parsed_parent_id,
            branch_type=branch_type,
            metadata=metadata,
            domains=domains,
            scope_id=scope_id_value,
        )
    except ValidationError as exc:
        errors = exc.errors()
        messages = [f"  - {e['loc'][-1]}: {e['msg']}" for e in errors]
        raise ToolError(
            "Parameter validation failed:\n" + "\n".join(messages)
        ) from exc

    session = None
    gen = None
    try:
        session, gen = await get_db_session()
        embedding_service = get_embedding_service()

        memory, curation_result = await create_memory(
            node_create,
            session,
            embedding_service,
            tenant_id=write_tenant_id,
            s3_adapter=get_s3_adapter(),
            force=force,
        )

        if curation_result["blocked"]:
            if curation_result.get("gated"):
                # Similarity gate fired — return structured response so the
                # caller can decide to update_memory or retry with force=True.
                cache_impact = await _get_cache_impact(write_tenant_id, owner_id)
                return {
                    "memory": None,
                    "curation": {
                        "blocked": True,
                        "gated": True,
                        "reason": curation_result["reason"],
                        "detail": curation_result.get("detail"),
                        "similar_count": curation_result["similar_count"],
                        "nearest_id": (
                            str(curation_result["nearest_id"])
                            if curation_result["nearest_id"]
                            else None
                        ),
                        "nearest_score": curation_result["nearest_score"],
                        "existing_memory_id": curation_result.get("existing_memory_id"),
                        "existing_memory_stub": curation_result.get("existing_memory_stub"),
                        "recommendation": curation_result.get("recommendation"),
                        "cache_impact": cache_impact,
                        "flags": curation_result.get("flags", []),
                    },
                }
            # Hard block (regex: secrets, PII) — still a ToolError.
            raise ToolError(
                f"Curation rule blocked write: {curation_result['reason']}"
            )

        # Pattern E (#62): broadcast to other connected agents post-commit.
        # Non-fatal — broadcast failures never roll back the write.
        await broadcast_after_write(
            memory_id=str(memory.id),
            notification=build_uri_only_notification(str(memory.id)),
            claims=claims,
            content_for_filter=memory.content,
            embedding_service=embedding_service,
        )

        return {
            "memory": memory.model_dump(mode="json"),
            "curation": {
                "blocked": False,
                "similar_count": curation_result["similar_count"],
                "nearest_id": str(curation_result["nearest_id"]) if curation_result["nearest_id"] else None,
                "nearest_score": curation_result["nearest_score"],
                "flags": curation_result["flags"],
            },
        }

    except ToolError:
        raise
    except MemoryNotFoundError:
        raise ToolError(
            f"Parent memory {parent_id} not found. Check the parent_id — "
            "it may have been deleted or you may not have access to it."
        )
    except MemoryAccessDeniedError as exc:
        raise ToolError(f"Access denied: {exc.reason}") from exc
    except Exception as exc:
        logger.error("Failed to create memory: %s", exc, exc_info=True)
        raise ToolError("Failed to create memory. See server logs for details.") from exc
    finally:
        if gen is not None:
            await release_db_session(gen)

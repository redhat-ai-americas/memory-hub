"""Create a new version of an existing memory.

The old version is preserved (isCurrent=false); the new version becomes
current. This maintains full history for forensics while allowing memories
to evolve over time.
"""

import uuid
from typing import Annotated, Any

from fastmcp import Context
from fastmcp.exceptions import ToolError
from pydantic import Field

from memoryhub_core.models.schemas import MemoryNodeUpdate
from memoryhub_core.services.campaign import get_campaigns_for_project
from memoryhub_core.services.project import get_projects_for_user
from memoryhub_core.services.role import get_roles_for_user
from memoryhub_core.services.exceptions import (
    MemoryAccessDeniedError,
    MemoryNotCurrentError,
    MemoryNotFoundError,
)
from memoryhub_core.services.memory import read_memory as _read_memory
from memoryhub_core.services.memory import update_memory as svc_update_memory
from memoryhub_core.services.push_broadcast import build_uri_only_notification
from src.core.app import mcp
from src.core.authz import (
    AuthenticationError,
    authorize_write,
    get_claims_from_context,
    get_tenant_filter,
)
from src.tools._deps import get_db_session, get_embedding_service, get_s3_adapter, release_db_session
from src.tools._push_helpers import broadcast_after_write


@mcp.tool(
    annotations={
        "readOnlyHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    }
)
async def update_memory(
    memory_id: Annotated[
        str,
        Field(
            description="ID of the current memory to update. Must be a current (isCurrent=true) version."
        ),
    ],
    content: Annotated[
        str | None,
        Field(
            description="New content text. Omit to keep existing content (useful for weight-only updates)."
        ),
    ] = None,
    weight: Annotated[
        float | None,
        Field(
            description="New injection priority (0.0-1.0). Omit to inherit from previous version.",
            ge=0.0,
            le=1.0,
        ),
    ] = None,
    metadata: Annotated[
        dict[str, Any] | None,
        Field(
            description="New metadata to merge with existing metadata. Omit to keep existing."
        ),
    ] = None,
    domains: Annotated[
        list[str] | None,
        Field(
            description=(
                "New domain tags to replace existing ones. "
                "Omit to keep existing domains."
            ),
        ),
    ] = None,
    project_id: Annotated[
        str | None,
        Field(
            description=(
                "Your project identifier. Required when updating a campaign-scoped "
                "memory — used to verify enrollment."
            ),
        ),
    ] = None,
    ctx: Context = None,
) -> dict[str, Any]:
    """Create a new version of an existing memory, preserving the old version for history.

    Use this when a preference changes, information is corrected, or a memory
    needs refinement. The old version stays accessible via get_memory_history.
    At least one of content, weight, or metadata must be provided.
    """
    if content is None and weight is None and metadata is None and domains is None:
        raise ToolError(
            "No changes provided. Include at least one of: content, weight, metadata, domains."
        )

    try:
        parsed_id = uuid.UUID(memory_id)
    except ValueError:
        raise ToolError(
            f"Invalid memory_id format: '{memory_id}'. Expected a UUID string."
        )

    update_data = MemoryNodeUpdate(
        content=content,
        weight=weight,
        metadata=metadata,
        domains=domains,
    )

    try:
        claims = get_claims_from_context()
    except AuthenticationError as exc:
        raise ToolError(str(exc))
    tenant = get_tenant_filter(claims)

    session, gen = await get_db_session()
    try:
        # Fetch existing memory to check authorization. The tenant filter
        # on read_memory makes a cross-tenant ID indistinguishable from
        # a nonexistent row; the follow-up authorize_write (which also
        # checks tenant) is defense in depth.
        existing = await _read_memory(parsed_id, session, tenant_id=tenant)

        # Resolve campaign membership for campaign-scoped memories.
        campaign_ids: set[str] | None = None
        if existing.scope == "campaign":
            if not project_id:
                raise ToolError(
                    "project_id is required when updating a campaign-scoped memory. "
                    "Set it to your project identifier so enrollment can be verified."
                )
            campaign_ids = await get_campaigns_for_project(
                session, project_id, tenant,
            )

        # Resolve project membership for project-scoped memories.
        project_ids: set[str] | None = None
        if existing.scope == "project":
            project_ids = await get_projects_for_user(session, claims["sub"])

        # Resolve role assignments for role-scoped memories.
        role_names: set[str] | None = None
        if existing.scope == "role":
            role_names = await get_roles_for_user(
                session, claims["sub"], tenant, claims=claims,
            )

        if not authorize_write(
            claims, existing.scope, existing.owner_id, existing.tenant_id,
            campaign_ids=campaign_ids,
            project_ids=project_ids,
            role_names=role_names,
            scope_id=existing.scope_id,
        ):
            raise ToolError(
                f"Not authorized to update this {existing.scope}-scope memory."
            )

        if ctx:
            await ctx.info(f"Updating memory {memory_id}")

        embedding_service = get_embedding_service()
        new_version = await svc_update_memory(
            memory_id=parsed_id,
            data=update_data,
            session=session,
            embedding_service=embedding_service,
            s3_adapter=get_s3_adapter(),
        )

        # Pattern E (#62): broadcast to other connected agents post-commit.
        await broadcast_after_write(
            memory_id=str(new_version.id),
            notification=build_uri_only_notification(str(new_version.id)),
            claims=claims,
            content_for_filter=new_version.content,
            embedding_service=embedding_service,
        )

        result = new_version.model_dump(mode="json")
        result["previous_version_id"] = str(new_version.previous_version_id)
        return result

    except MemoryNotFoundError:
        raise ToolError(f"Memory {memory_id} not found.")
    except MemoryNotCurrentError as exc:
        raise ToolError(
            f"Memory {memory_id} is not current. "
            f"Current version is {exc.current_id}. Update that instead."
        )
    except MemoryAccessDeniedError as exc:
        raise ToolError(f"Access denied: {exc.reason}")
    finally:
        await release_db_session(gen)

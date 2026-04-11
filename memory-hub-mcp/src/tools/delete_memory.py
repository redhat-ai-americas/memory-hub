"""Soft-delete a memory and its entire version chain.

Marks the memory and all related versions as deleted via a deleted_at
timestamp; child branches go with the chain. Deleted memories are
excluded from search, read, and graph queries — from an agent's
perspective the deletion is final, and there is no MCP-exposed undelete.
A deleted_at row remains in the database for compliance/audit but only
out-of-band admin tooling can recover it. Only the memory owner or
memory:admin can delete. This is a destructive operation.
"""

import uuid
from typing import Annotated, Any

from fastmcp import Context
from fastmcp.exceptions import ToolError
from pydantic import Field

from memoryhub_core.services.campaign import get_campaigns_for_project
from memoryhub_core.services.project import get_projects_for_user
from memoryhub_core.services.role import get_roles_for_user
from memoryhub_core.services.exceptions import (
    MemoryAccessDeniedError,
    MemoryAlreadyDeletedError,
    MemoryNotFoundError,
)
from memoryhub_core.services.memory import delete_memory as svc_delete_memory
from memoryhub_core.services.memory import read_memory as _read_memory
from memoryhub_core.services.push_broadcast import build_uri_only_notification

from src.core.app import mcp
from src.core.authz import (
    AuthenticationError,
    authorize_write,
    get_claims_from_context,
    get_tenant_filter,
)
from src.tools._deps import get_db_session, get_s3_adapter, release_db_session
from src.tools._push_helpers import broadcast_after_write


@mcp.tool(
    annotations={
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": False,
    }
)
async def delete_memory(
    memory_id: Annotated[
        str,
        Field(
            description=(
                "ID of any version of the memory to delete. The entire version "
                "chain (older + newer versions) plus child branches will be "
                "soft-deleted. You can pass any version ID — the tool walks "
                "the chain in both directions."
            )
        ),
    ],
    project_id: Annotated[
        str | None,
        Field(
            description=(
                "Your project identifier. Required when deleting a campaign-scoped "
                "memory — used to verify your project is enrolled in the campaign."
            ),
        ),
    ] = None,
    ctx: Context = None,
) -> dict[str, Any]:
    """Soft-delete a memory and its entire version chain.

    Marks the memory and every node in its version chain as deleted via a
    `deleted_at` timestamp. Child branches (rationale, provenance, etc.)
    attached to any version in the chain are also deleted. Deleted memories
    are excluded from search, read, and graph queries — from an agent's
    perspective the deletion is final. The row remains in the database for
    compliance/audit, but recovery requires out-of-band admin tooling.

    Authorization: caller must either own the memory (via memory:write
    for the memory's scope) or hold the memory:admin scope. The owner check
    follows the same rules as update_memory.

    Args:
        memory_id: ID of any version of the memory to delete. The tool
            walks the version chain in both directions, so passing an old
            version ID still removes the entire chain.
        ctx: FastMCP context for logging.

    Returns:
        A dict with deletion counts:
            - deleted_id: the memory_id passed in (echoed back)
            - versions_deleted: number of version-chain nodes soft-deleted
            - branches_deleted: number of child branch nodes soft-deleted
            - total_deleted: sum of versions + branches

    Raises:
        ToolError: For invalid UUID format, missing/inaccessible memory,
            already-deleted memory, or insufficient authorization.
    """
    try:
        parsed_id = uuid.UUID(memory_id)
    except ValueError:
        raise ToolError(
            f"Invalid memory_id format: '{memory_id}'. Expected a UUID string."
        )

    try:
        claims = get_claims_from_context()
    except AuthenticationError as exc:
        raise ToolError(str(exc))
    tenant = get_tenant_filter(claims)

    session, gen = await get_db_session()
    try:
        # Read the existing memory to check authorization. read_memory
        # already filters deleted_at IS NULL, so an already-deleted memory
        # will surface as "not found" here — that's the right behavior:
        # we don't want to leak existence of deleted memories to callers
        # who couldn't see them. The tenant filter also makes a
        # cross-tenant ID indistinguishable from a nonexistent row.
        # The MemoryAlreadyDeletedError path below is reached only if
        # the row's deleted_at gets set between this read and the
        # service call (race condition).
        existing = await _read_memory(parsed_id, session, tenant_id=tenant)

        # Resolve campaign membership when deleting a campaign-scoped memory.
        campaign_ids: set[str] | None = None
        if existing.scope == "campaign":
            if not project_id:
                raise ToolError(
                    "project_id is required when deleting a campaign-scoped memory. "
                    "Set it to your project identifier so enrollment can be verified."
                )
            campaign_ids = await get_campaigns_for_project(session, project_id, tenant)

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

        is_owner = authorize_write(
            claims, existing.scope, existing.owner_id, existing.tenant_id,
            campaign_ids=campaign_ids,
            project_ids=project_ids,
            role_names=role_names,
            scope_id=existing.scope_id,
        )
        is_admin = "memory:admin" in claims.get("scopes", [])
        if not (is_owner or is_admin):
            raise ToolError(
                f"Not authorized to delete this {existing.scope}-scope memory. "
                "You need either ownership of the memory or the memory:admin scope."
            )

        if ctx:
            await ctx.info(f"Deleting memory {memory_id}")

        result = await svc_delete_memory(
            memory_id=parsed_id,
            session=session,
            s3_adapter=get_s3_adapter(),
        )

        # Pattern E (#62): broadcast to other connected agents post-commit.
        # Deletes don't carry an embedding — pass None to skip the focus
        # filter so every active session learns the memory is gone, even
        # subscribers whose declared focus was unrelated to the deleted
        # memory's topic. Deletion is rare enough that the cross-topic
        # spam tradeoff is acceptable.
        await broadcast_after_write(
            memory_id=memory_id,
            notification=build_uri_only_notification(memory_id),
            claims=claims,
            content_for_filter=None,
            embedding_service=None,
        )

        return result

    except MemoryNotFoundError:
        raise ToolError(
            f"Memory {memory_id} not found. It may have already been "
            "deleted, or you may not have read access to its scope."
        )
    except MemoryAlreadyDeletedError:
        # Reachable only via race condition: between our read_memory call
        # (which filters deleted_at IS NULL) and the service call, another
        # caller deleted the same memory. The non-race "already deleted"
        # case surfaces as MemoryNotFoundError above, which is the right
        # behavior — we don't want to leak deleted-memory existence to
        # callers who couldn't see them.
        raise ToolError(
            f"Memory {memory_id} was deleted by another caller during this "
            "operation. No further action needed."
        )
    except MemoryAccessDeniedError as exc:
        raise ToolError(f"Access denied: {exc.reason}")
    finally:
        await release_db_session(gen)

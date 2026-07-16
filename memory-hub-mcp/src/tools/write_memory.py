"""Create a new memory node or branch in the memory tree."""

import asyncio
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

import yaml
from fastmcp import Context
from fastmcp.exceptions import ToolError
from pydantic import BaseModel, Field, ValidationError

from memoryhub_core.config import AppSettings
from memoryhub_core.models.schemas import MemoryNodeCreate
from memoryhub_core.services.campaign import get_campaigns_for_project
from memoryhub_core.services.exceptions import (
    EmbeddingContentTooLargeError,
    EmbeddingServiceError,
    EmbeddingServiceUnavailableError,
    MemoryAccessDeniedError,
    MemoryNotFoundError,
    ProjectInviteOnlyError,
)
from memoryhub_core.services.memory import create_fact_children, create_memory
from memoryhub_core.services.project import ensure_project_membership
from memoryhub_core.services.push_broadcast import build_uri_only_notification
from memoryhub_core.services.role import get_roles_for_user
from src.core.app import mcp
from src.core.audit import record_event
from src.core.authz import (
    PROJECT_ISOLATION_ENABLED,
    ROLE_ISOLATION_ENABLED,
    AuthenticationError,
    authorize_write,
    get_claims_from_context,
    resolve_tenant,
)
from src.tools._deps import (
    get_db_session,
    get_embedding_service,
    get_s3_adapter,
    release_db_session,
    resolve_driver_id,
)
from src.tools._push_helpers import broadcast_after_write

logger = logging.getLogger(__name__)

FACT_EXTRACTION_TIMEOUT = 15.0
_PROMPT_DIR = Path(__file__).resolve().parents[3] / "prompts"
# Fallback for container deployments where the prompt is co-located
_PROMPT_DIR_CONTAINER = Path("/opt/app-root/src/prompts")


class ExtractedFact(BaseModel):
    content: str
    weight: float = 0.7
    domains: list[str] = []


class FactExtractionResult(BaseModel):
    facts: list[ExtractedFact]


def _load_extraction_prompt() -> dict:
    """Load the fact extraction prompt from YAML."""
    path = _PROMPT_DIR / "fact_extraction.yaml"
    if not path.exists():
        path = _PROMPT_DIR_CONTAINER / "fact_extraction.yaml"
    with open(path) as f:
        return yaml.safe_load(f)


async def _extract_facts_via_sampling(
    ctx: Context,
    content: str,
    parent_id: uuid.UUID,
    scope: str,
    scope_id: str | None,
    owner_id: str,
    tenant_id: str,
    domains: list[str] | None,
    embedding_service: Any,
    session: Any,
) -> int | str:
    """Run fact extraction via MCP sampling. Returns fact count or "deferred"."""
    try:
        prompt_config = _load_extraction_prompt()
    except Exception as exc:
        logger.warning("Failed to load extraction prompt: %s", exc)
        return "deferred"

    prompt_text = prompt_config["system_prompt"] + "\n\n" + content

    try:
        result = await asyncio.wait_for(
            ctx.sample(
                messages=prompt_text,
                result_type=FactExtractionResult,
                temperature=0.0,
                max_tokens=4000,
            ),
            timeout=FACT_EXTRACTION_TIMEOUT,
        )
    except asyncio.TimeoutError:
        logger.warning("Fact extraction timed out for parent %s", parent_id)
        return "deferred"
    except Exception as exc:
        logger.warning("Fact extraction sampling failed for parent %s: %s", parent_id, exc)
        return "deferred"

    if not result.result or not result.result.facts:
        return 0

    prompt_version = prompt_config.get("version", "unknown")
    extraction_run_id = f"eager:{prompt_version}:{datetime.now(UTC).isoformat()}"

    facts = [f.model_dump() for f in result.result.facts]
    try:
        count = await create_fact_children(
            facts=facts,
            parent_id=parent_id,
            scope=scope,
            scope_id=scope_id,
            owner_id=owner_id,
            tenant_id=tenant_id,
            domains=domains,
            extraction_run_id=extraction_run_id,
            embedding_service=embedding_service,
            session=session,
        )
        return count
    except Exception as exc:
        logger.warning("Failed to create fact children for %s: %s", parent_id, exc)
        return "deferred"


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
            default="user",
            description=(
                "One of: user, project, campaign, role, organizational, enterprise. "
                "Defaults to 'user' -- most agent-created memories are user-scoped. "
                "For campaign scope, set owner_id to the campaign UUID and "
                "provide project_id for enrollment verification."
            ),
        ),
    ] = "user",
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
    project_description: Annotated[
        str | None,
        Field(
            description=(
                "Description for the project when auto-creating it on first "
                "project-scoped write. Ignored if the project already exists. "
                "Helps other agents understand what the project is about in "
                "manage_project output."
            ),
        ),
    ] = None,
    force: Annotated[
        bool,
        Field(
            description=(
                "(Advanced) Bypass near-duplicate similarity gates. Regex rules "
                "(secrets, PII) are never bypassed."
            ),
        ),
    ] = False,
    content_type: Annotated[
        str | None,
        Field(
            description=(
                "(Advanced) Memory content type. Defaults to 'experiential' "
                "(agent-created memories). Use 'declarative' for facts and "
                "preferences, 'behavioral' for demonstrated patterns and "
                "successful approaches. Behavioral memories are not injected "
                "by default -- use the reconstruct action to retrieve them."
            ),
        ),
    ] = None,
    driver_id: Annotated[
        str | None,
        Field(
            description=(
                "Identity of the upstream human or system driving this write. "
                "Omit to use the session default (set at register_session time) "
                "or the authenticated actor_id if no default is set."
            ),
        ),
    ] = None,
    relevant_until: Annotated[
        str | None,
        Field(
            description=(
                "ISO 8601 timestamp for semantic expiry (e.g. '2026-12-31T23:59:59Z'). "
                "When set, indicates when this memory's content becomes stale. "
                "Distinct from storage lifecycle (expires_at). Omit to let the "
                "temporal classifier auto-detect from content."
            ),
        ),
    ] = None,
    tenant_id: Annotated[
        str | None,
        Field(
            description=(
                "Target tenant for this write. Omit to use the session's "
                "own tenant. Must be a tenant the caller is authorized for."
            ),
        ),
    ] = None,
    chunk_target_tokens: Annotated[
        int | None,
        Field(
            description=(
                "(Advanced) Target tokens per chunk for oversized content. "
                "Omit to use the server default (256). Smaller values "
                "produce more focused chunks; larger values preserve more context."
            ),
        ),
    ] = None,
    chunk_overlap_tokens: Annotated[
        int | None,
        Field(
            description=(
                "(Advanced) Overlap tokens between consecutive chunks. "
                "Omit to use the server default (0). Overlap preserves "
                "context at chunk boundaries for better retrieval."
            ),
        ),
    ] = None,
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

    write_tenant_id = resolve_tenant(claims, tenant_id)

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
    # Auto-enrolls the user if the project is open (or creates it).
    project_ids: set[str] | None = None
    scope_id_value: str | None = None
    was_auto_enrolled = False
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
                project_ids, was_auto_enrolled = await ensure_project_membership(
                    session_for_project, project_id, claims["sub"], write_tenant_id,
                    description=project_description,
                )
                await session_for_project.commit()
            except ProjectInviteOnlyError as exc:
                raise ToolError(str(exc)) from exc
            finally:
                await release_db_session(gen_for_project)

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
        record_event(
            event_type="memory.write",
            actor_id=claims["sub"],
            driver_id=resolve_driver_id(driver_id, claims),
            scope=scope,
            owner_id=owner_id,
            memory_id=None,
            decision="denied",
        )
        raise ToolError(
            f"Not authorized to write {scope}-scope memory for owner '{owner_id}'."
        )

    # Resolve actor/driver identity for audit trail.
    actor_id = claims["sub"]
    resolved_driver = resolve_driver_id(driver_id, claims)

    record_event(
        event_type="memory.write",
        actor_id=actor_id,
        driver_id=resolved_driver,
        scope=scope,
        owner_id=owner_id,
        memory_id=None,
        decision="allowed",
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
            ) from None

    # Parse relevant_until string to datetime if provided.
    parsed_relevant_until = None
    if relevant_until is not None:
        from datetime import UTC as _UTC
        from datetime import datetime as dt

        try:
            parsed_relevant_until = dt.fromisoformat(relevant_until)
            # Ensure timezone-aware
            if parsed_relevant_until.tzinfo is None:
                parsed_relevant_until = parsed_relevant_until.replace(tzinfo=_UTC)
        except (ValueError, TypeError):
            raise ToolError(
                f"Invalid relevant_until format: '{relevant_until}'. "
                "Must be a valid ISO 8601 timestamp (e.g. '2026-12-31T23:59:59Z')."
            ) from None

    # Build the create schema with validation
    # Only pass content_type if explicitly provided; let Pydantic default apply
    create_kwargs = dict(
        content=content,
        scope=scope,
        weight=weight,
        owner_id=owner_id,
        actor_id=actor_id,
        driver_id=resolved_driver,
        parent_id=parsed_parent_id,
        branch_type=branch_type,
        metadata=metadata,
        domains=domains,
        scope_id=scope_id_value,
        relevant_until=parsed_relevant_until,
    )
    if content_type is not None:
        create_kwargs["content_type"] = content_type
    if chunk_target_tokens is not None:
        create_kwargs["chunk_target_tokens"] = chunk_target_tokens
    if chunk_overlap_tokens is not None:
        create_kwargs["chunk_overlap_tokens"] = chunk_overlap_tokens
    try:
        node_create = MemoryNodeCreate(**create_kwargs)
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

        # Eager fact extraction via MCP sampling. Same threshold as
        # chunking: content large enough to chunk is large enough to
        # extract. Non-fatal -- the write never fails on extraction failure.
        facts_extracted = None
        app_settings = AppSettings()
        embedding_max_chars = app_settings.embedding_max_tokens * 4
        is_oversized = len(content) > embedding_max_chars
        if is_oversized and ctx and branch_type is None:
            facts_extracted = await _extract_facts_via_sampling(
                ctx=ctx,
                content=content,
                parent_id=memory.id,
                scope=scope,
                scope_id=scope_id_value,
                owner_id=owner_id,
                tenant_id=write_tenant_id,
                domains=domains,
                embedding_service=embedding_service,
                session=session,
            )

        result = {
            "memory": memory.model_dump(mode="json"),
            "curation": {
                "blocked": False,
                "similar_count": curation_result["similar_count"],
                "nearest_id": str(curation_result["nearest_id"]) if curation_result["nearest_id"] else None,
                "nearest_score": curation_result["nearest_score"],
                "flags": curation_result["flags"],
            },
        }
        if facts_extracted is not None:
            result["facts_extracted"] = facts_extracted
        if was_auto_enrolled:
            result["auto_enrolled"] = {
                "project_id": project_id,
                "message": f"Auto-enrolled in project '{project_id}'.",
            }
        return result

    except ToolError:
        raise
    except MemoryNotFoundError:
        raise ToolError(
            f"Parent memory {parent_id} not found. Check the parent_id — "
            "it may have been deleted or you may not have access to it."
        ) from None
    except MemoryAccessDeniedError as exc:
        raise ToolError(f"Access denied: {exc.reason}") from exc
    except EmbeddingContentTooLargeError as exc:
        raise ToolError(
            f"Invalid content size: {exc.content_length} characters exceeds the "
            "embedding model's input limit. Shorten the content or split into "
            "smaller memories."
        ) from exc
    except EmbeddingServiceUnavailableError as exc:
        raise ToolError(
            f"Embedding service is unavailable: {exc.reason}. Memory was not saved. "
            "Retry after the embedding service recovers."
        ) from exc
    except EmbeddingServiceError as exc:
        raise ToolError(f"Embedding failed: {exc}. Memory was not saved.") from exc
    except Exception as exc:
        logger.error("Failed to create memory: %s", exc, exc_info=True)
        raise ToolError("Failed to create memory. See server logs for details.") from exc
    finally:
        if gen is not None:
            await release_db_session(gen)

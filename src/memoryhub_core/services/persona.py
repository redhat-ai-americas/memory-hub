"""Persona compilation service — WRIG-1483.

Compiles a standing user profile (synopsis node) from dreaming-extracted
behavioral facts. The synopsis is a first-class MemoryNode that is always
injected before search results at session start.

Design: MUXI synopsis pattern on MemoryHub's tree.
  Source:  scope=user, source=dreaming, content_type=behavioral, is_current=True
  Output:  scope=user, source=persona_compiler, content_type=behavioral, weight=1.0
  Version: synopsis versioned on the same logical_id across recompiles
  Provenance: derived_from edges → each source fact

Staleness: when dreaming writes a behavioral fact, the current synopsis is
marked stale (metadata_["stale"]=True). Recompile clears the flag.

User pins: user-declared facts stored as branch_type="fact" children of the
synopsis. Pins survive recompile — they are prepended to the LLM prompt as
immutable facts and carried forward as children of the new node.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import httpx
from sqlalchemy import and_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from memoryhub_core.models.memory import MemoryNode, MemoryRelationship
from memoryhub_core.models.utils import generate_stub

if TYPE_CHECKING:
    from memoryhub_core.services.embeddings import EmbeddingService

logger = logging.getLogger(__name__)

_SYNOPSIS_SOURCE = "persona_compiler"
_SYNOPSIS_CONTENT_TYPE = "behavioral"
_SYNOPSIS_SCOPE = "user"
_SYNOPSIS_WEIGHT = 1.0
_PIN_SOURCE = "user"
_PIN_BRANCH_TYPE = "fact"

_COMPILER_SYSTEM_PROMPT = """\
You are a persona compiler. Synthesize a standing user profile from the facts below.

Structure (use exactly these headers):
## Preferences
## Working Style
## Values & Constraints
## Communication
## Current Focus

Rules:
- 1-3 bullet points per section. Omit a section only if you have zero facts for it.
- Normalize tense: if a fact describes a future event whose date is past, \
rewrite in past tense (e.g. "going to X next month" → "attended X in [month]").
- When two facts contradict: the one with a more recent timestamp wins.
- USER-DECLARED facts (labeled [PINNED]) are authoritative and must be preserved \
verbatim — they override any conflicting inferred fact.
- Hard cap: respond in at most 400 tokens. Output ONLY the Markdown profile, \
no preamble or explanation.
"""

_MAX_RETRIES = 2


# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------


async def _call_synopsis_llm(
    facts: list[dict[str, Any]],
    pins: list[dict[str, Any]],
    *,
    model: str,
    url: str,
    api_key: str,
) -> str:
    """Synthesize a persona profile from facts + user-declared pins.

    Pins are prepended as authoritative, labeled [PINNED].
    Facts are ordered newest-first (caller's responsibility).
    """
    lines: list[str] = []
    for p in pins:
        lines.append(f"[PINNED] {p['content']}")
    for f in facts:
        ts = f.get("updated_at", "unknown")
        lines.append(f"[updated: {ts}] {f['content']}")

    user_msg = "Facts to synthesize:\n\n" + "\n".join(lines)

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    last_err: Exception | None = None
    async with httpx.AsyncClient(timeout=60, verify=False, headers=headers) as client:
        for attempt in range(_MAX_RETRIES + 1):
            try:
                resp = await client.post(
                    f"{url.rstrip('/')}/chat/completions",
                    json={
                        "model": model,
                        "messages": [
                            {"role": "system", "content": _COMPILER_SYSTEM_PROMPT},
                            {"role": "user", "content": user_msg},
                        ],
                        "temperature": 0.3,
                        "max_tokens": 512,
                    },
                )
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"].strip()
            except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPStatusError) as exc:
                last_err = exc
                if attempt < _MAX_RETRIES:
                    await asyncio.sleep(2 ** attempt)
    raise RuntimeError(
        f"Synopsis LLM failed after {_MAX_RETRIES + 1} attempts: {last_err}"
    )


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------


async def get_dreaming_nodes(
    user_id: str,
    tenant_id: str,
    session: AsyncSession,
    *,
    project_id: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Return current behavioral dreaming facts for the user, newest first."""
    filters = [
        MemoryNode.tenant_id == tenant_id,
        MemoryNode.owner_id == user_id,
        MemoryNode.scope == _SYNOPSIS_SCOPE,
        MemoryNode.source == "dreaming",
        MemoryNode.content_type == _SYNOPSIS_CONTENT_TYPE,
        MemoryNode.is_current.is_(True),
        MemoryNode.deleted_at.is_(None),
        MemoryNode.status == "active",
    ]
    if project_id is not None:
        filters.append(MemoryNode.scope_id == project_id)

    stmt = (
        select(MemoryNode)
        .where(and_(*filters))
        .order_by(MemoryNode.updated_at.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    nodes = result.scalars().all()
    return [
        {
            "id": str(n.id),
            "content": n.content,
            "updated_at": n.updated_at.isoformat() if n.updated_at else None,
        }
        for n in nodes
    ]


async def get_current_synopsis(
    user_id: str,
    tenant_id: str,
    session: AsyncSession,
    *,
    project_id: str | None = None,
) -> MemoryNode | None:
    """Return the current synopsis node for the user, or None."""
    filters = [
        MemoryNode.tenant_id == tenant_id,
        MemoryNode.owner_id == user_id,
        MemoryNode.scope == _SYNOPSIS_SCOPE,
        MemoryNode.source == _SYNOPSIS_SOURCE,
        MemoryNode.is_current.is_(True),
        MemoryNode.deleted_at.is_(None),
        MemoryNode.status == "active",
    ]
    if project_id is not None:
        filters.append(MemoryNode.scope_id == project_id)

    stmt = (
        select(MemoryNode)
        .where(and_(*filters))
        .order_by(MemoryNode.updated_at.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_user_pins(
    user_id: str,
    tenant_id: str,
    session: AsyncSession,
    *,
    synopsis_id: uuid.UUID | None = None,
) -> list[dict[str, Any]]:
    """Return user-declared pinned facts for a synopsis node.

    Pins are children of the synopsis node (branch_type="fact", source="user").
    When synopsis_id is None, returns global pins not tied to a specific synopsis.
    """
    filters = [
        MemoryNode.tenant_id == tenant_id,
        MemoryNode.owner_id == user_id,
        MemoryNode.scope == _SYNOPSIS_SCOPE,
        MemoryNode.source == _PIN_SOURCE,
        MemoryNode.branch_type == _PIN_BRANCH_TYPE,
        MemoryNode.is_current.is_(True),
        MemoryNode.deleted_at.is_(None),
        MemoryNode.status == "active",
    ]
    if synopsis_id is not None:
        filters.append(MemoryNode.parent_id == synopsis_id)

    stmt = (
        select(MemoryNode)
        .where(and_(*filters))
        .order_by(MemoryNode.created_at.asc())
    )
    result = await session.execute(stmt)
    nodes = result.scalars().all()
    return [
        {"id": str(n.id), "content": n.content, "created_at": n.created_at.isoformat() if n.created_at else None}
        for n in nodes
    ]


async def get_persona_status(
    user_id: str,
    tenant_id: str,
    session: AsyncSession,
    *,
    project_id: str | None = None,
) -> dict[str, Any]:
    """Return a status dict describing the current persona state."""
    synopsis = await get_current_synopsis(user_id, tenant_id, session, project_id=project_id)
    facts = await get_dreaming_nodes(user_id, tenant_id, session, project_id=project_id)

    if synopsis is None:
        return {
            "has_synopsis": False,
            "is_stale": True,
            "stale_reason": "no synopsis compiled yet",
            "source_fact_count": len(facts),
            "synopsis_id": None,
            "compiled_at": None,
            "version": None,
        }

    meta = synopsis.metadata_ or {}
    is_stale = meta.get("stale", False)
    stale_reason = "new dreaming facts since last compile" if is_stale else None

    return {
        "has_synopsis": True,
        "is_stale": is_stale,
        "stale_reason": stale_reason,
        "source_fact_count": len(facts),
        "compiled_fact_count": meta.get("source_fact_count", 0),
        "synopsis_id": str(synopsis.id),
        "compiled_at": synopsis.updated_at.isoformat() if synopsis.updated_at else None,
        "version": synopsis.version,
    }


# ---------------------------------------------------------------------------
# Staleness
# ---------------------------------------------------------------------------


async def mark_synopsis_stale(
    user_id: str,
    tenant_id: str,
    session: AsyncSession,
    *,
    project_id: str | None = None,
) -> bool:
    """Mark the current synopsis as stale (does not create a new version).

    Called by the dreaming pipeline after writing a behavioral fact.
    Non-fatal: returns False when no synopsis exists.
    """
    synopsis = await get_current_synopsis(user_id, tenant_id, session, project_id=project_id)
    if synopsis is None:
        return False

    meta = dict(synopsis.metadata_ or {})
    if meta.get("stale"):
        return True  # already stale, no-op

    meta["stale"] = True
    await session.execute(
        update(MemoryNode)
        .where(MemoryNode.id == synopsis.id)
        .values(metadata_=meta)
    )
    await session.commit()
    return True


# ---------------------------------------------------------------------------
# Provenance edges
# ---------------------------------------------------------------------------


async def _create_provenance_edges(
    synopsis_id: uuid.UUID,
    fact_ids: list[uuid.UUID],
    tenant_id: str,
    session: AsyncSession,
) -> None:
    """Create derived_from relationship edges from synopsis → each source fact.

    Skips individual edges that fail (e.g. duplicate — fact already linked
    from a previous recompile). Non-fatal throughout.
    """
    now = datetime.now(UTC)
    for fact_id in fact_ids:
        try:
            rel = MemoryRelationship(
                id=uuid.uuid4(),
                source_id=synopsis_id,
                target_id=fact_id,
                relationship_type="derived_from",
                created_by="persona_compiler",
                tenant_id=tenant_id,
                metadata_=None,
                valid_from=now,
                valid_until=None,
            )
            session.add(rel)
        except Exception as exc:
            logger.debug("Skipping provenance edge %s→%s: %s", synopsis_id, fact_id, exc)
    try:
        await session.flush()
    except Exception as exc:
        logger.debug("Some provenance edges failed to flush: %s", exc)
        await session.rollback()
        raise


# ---------------------------------------------------------------------------
# Compilation
# ---------------------------------------------------------------------------


async def compile_persona_synopsis(
    user_id: str,
    tenant_id: str,
    session: AsyncSession,
    *,
    project_id: str | None = None,
    model: str | None = None,
    url: str | None = None,
    api_key: str | None = None,
    embedding_service: "EmbeddingService | None" = None,
) -> dict[str, Any]:
    """Compile a standing persona profile and store it as a synopsis node.

    Steps:
    1. Query dreaming behavioral facts (source of truth).
    2. Query user-declared pins (immutable, prepended to LLM prompt).
    3. Call the LLM to synthesize the profile (400-token cap).
    4. Retire the old synopsis (is_current=False), preserving logical_id and version chain.
    5. Store the new synopsis (weight=1.0, source=persona_compiler).
    6. Carry user pins forward as children of the new synopsis node.
    7. Create derived_from provenance edges.
    8. Clear staleness flag.

    Raises ValueError when no dreaming facts exist or LLM is not configured.
    """
    from memoryhub_core.config import AppSettings

    settings = AppSettings()
    model = model or settings.conv_extraction_model
    url = url or settings.conv_extraction_model_url
    api_key = api_key or settings.conv_extraction_api_key

    if not model or not url:
        raise ValueError(
            "Persona compiler requires MEMORYHUB_CONV_EXTRACTION_MODEL and "
            "MEMORYHUB_CONV_EXTRACTION_MODEL_URL to be set."
        )

    facts = await get_dreaming_nodes(user_id, tenant_id, session, project_id=project_id)
    if not facts:
        raise ValueError(
            f"No behavioral dreaming facts found for user '{user_id}'. "
            "Run dreaming extraction on conversation threads first."
        )

    old_synopsis = await get_current_synopsis(user_id, tenant_id, session, project_id=project_id)

    # Gather user-declared pins from the old synopsis (carry them forward)
    pins: list[dict[str, Any]] = []
    if old_synopsis is not None:
        pins = await get_user_pins(user_id, tenant_id, session, synopsis_id=old_synopsis.id)

    synopsis_md = await _call_synopsis_llm(facts, pins, model=model, url=url, api_key=api_key)

    # Embed the synopsis so it participates in the node graph properly
    embedding = None
    if embedding_service is not None:
        try:
            embedding = await embedding_service.embed(synopsis_md)
        except Exception as exc:
            logger.warning("Failed to embed synopsis for %s: %s", user_id, exc)

    # Retire old synopsis, carry forward its logical_id and version counter
    old_synopsis_id: uuid.UUID | None = None
    new_logical_id: uuid.UUID
    new_version: int

    if old_synopsis is not None:
        old_synopsis_id = old_synopsis.id
        new_logical_id = old_synopsis.logical_id
        new_version = old_synopsis.version + 1
        old_synopsis.is_current = False
        old_synopsis.updated_at = datetime.now(UTC)
        session.add(old_synopsis)
    else:
        node_id_tmp = uuid.uuid4()
        new_logical_id = node_id_tmp
        new_version = 1

    # Create new synopsis node
    node_id = uuid.uuid4()
    now = datetime.now(UTC)
    stub = generate_stub(
        content=synopsis_md,
        scope=_SYNOPSIS_SCOPE,
        weight=_SYNOPSIS_WEIGHT,
        branch_count=0,
        has_rationale=False,
    )
    new_node = MemoryNode(
        id=node_id,
        logical_id=new_logical_id,
        content=synopsis_md,
        stub=stub,
        scope=_SYNOPSIS_SCOPE,
        scope_id=project_id,
        weight=_SYNOPSIS_WEIGHT,
        owner_id=user_id,
        actor_id="persona_compiler",
        driver_id=user_id,
        tenant_id=tenant_id,
        parent_id=None,
        branch_type=None,
        metadata_={
            "source_fact_count": len(facts),
            "pin_count": len(pins),
            "stale": False,
        },
        domains=[],
        content_type=_SYNOPSIS_CONTENT_TYPE,
        source=_SYNOPSIS_SOURCE,
        embedding=embedding,
        is_current=True,
        version=new_version,
        previous_version_id=old_synopsis_id,
        storage_type="inline",
        content_ref=None,
        created_at=now,
        updated_at=now,
    )
    session.add(new_node)
    await session.flush()  # get node_id into DB before relationship inserts

    # Carry user pins forward as children of the new synopsis
    for pin in pins:
        pin_node = await session.get(MemoryNode, uuid.UUID(pin["id"]))
        if pin_node is not None:
            pin_node.parent_id = node_id
            session.add(pin_node)

    await session.commit()

    # Provenance edges (non-fatal if they fail — e.g. facts re-linked from prior compile)
    fact_uuids = [uuid.UUID(f["id"]) for f in facts]
    try:
        await _create_provenance_edges(node_id, fact_uuids, tenant_id, session)
        await session.commit()
    except Exception as exc:
        logger.warning("Provenance edges partially failed for %s: %s", user_id, exc)

    logger.info(
        "Compiled persona synopsis v%d for user %s: %d facts + %d pins → node %s (prev=%s)",
        new_version, user_id, len(facts), len(pins), node_id, old_synopsis_id,
    )

    return {
        "synopsis_id": str(node_id),
        "user_id": user_id,
        "project_id": project_id,
        "source_fact_count": len(facts),
        "pin_count": len(pins),
        "version": new_version,
        "previous_synopsis_id": str(old_synopsis_id) if old_synopsis_id else None,
        "content": synopsis_md,
        "compiled_at": now.isoformat(),
        "is_stale": False,
    }


# ---------------------------------------------------------------------------
# User pin management
# ---------------------------------------------------------------------------


async def add_user_pin(
    user_id: str,
    tenant_id: str,
    content: str,
    session: AsyncSession,
    *,
    project_id: str | None = None,
    synopsis_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """Store a user-declared fact that survives persona recompilation.

    Pins are written as branch_type="fact" children of the current synopsis
    (or as free-standing nodes when no synopsis exists yet). They are
    prepended to the LLM prompt on the next compile, labeled [PINNED].
    """
    now = datetime.now(UTC)
    pin_id = uuid.uuid4()
    stub = generate_stub(
        content=content,
        scope=_SYNOPSIS_SCOPE,
        weight=0.9,
        branch_count=0,
        has_rationale=False,
    )

    # Anchor to current synopsis if not specified
    parent_id: uuid.UUID | None = synopsis_id
    if parent_id is None:
        current = await get_current_synopsis(user_id, tenant_id, session, project_id=project_id)
        if current is not None:
            parent_id = current.id

    pin_node = MemoryNode(
        id=pin_id,
        logical_id=pin_id,
        content=content,
        stub=stub,
        scope=_SYNOPSIS_SCOPE,
        scope_id=project_id,
        weight=0.9,
        owner_id=user_id,
        actor_id=user_id,
        driver_id=user_id,
        tenant_id=tenant_id,
        parent_id=parent_id,
        branch_type=_PIN_BRANCH_TYPE,
        metadata_={"user_declared": True},
        domains=[],
        content_type="declarative",
        source=_PIN_SOURCE,
        embedding=None,
        is_current=True,
        version=1,
        storage_type="inline",
        content_ref=None,
        created_at=now,
        updated_at=now,
    )
    session.add(pin_node)
    await session.commit()

    return {
        "pin_id": str(pin_id),
        "content": content,
        "user_id": user_id,
        "synopsis_id": str(parent_id) if parent_id else None,
        "created_at": now.isoformat(),
        "note": "This fact will be preserved as [PINNED] in all future persona compilations.",
    }

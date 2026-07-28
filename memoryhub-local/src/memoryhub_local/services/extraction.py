"""Extraction pipeline for personal edition.

Extracts facts, preferences, and decisions from conversation threads and
creates searchable memory nodes. The LLM call is injected as a callable
so the same pipeline works for MCP sampling and direct HTTP calls.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from memoryhub_local.identity import TENANT_ID, get_owner_id
from memoryhub_local.models.conversation import (
    ConversationExtraction,
    ConversationExtractionFailure,
    ConversationMessage,
    ConversationThread,
)
from memoryhub_local.models.memory import MemoryNode
from memoryhub_local.models.reconciliation import ReconciliationDecision

if TYPE_CHECKING:
    from memoryhub_local.embeddings.base import EmbeddingService
    from memoryhub_local.storage.recall import RecallBackend

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EXTRACTION_SYSTEM_PROMPT = """\
You are a memory extraction system. Given a sequence of conversation
messages, extract discrete facts, preferences, decisions, and knowledge
that are worth remembering for future conversations.

Return a JSON object with an "extractions" array. Each extraction has:
  - "content": a clear, self-contained statement of the fact or decision.
    Another agent should understand it without seeing the original conversation.
  - "weight": a float between 0.0 and 1.0 indicating importance:
    - 1.0: critical policy or hard constraint
    - 0.8-0.9: strong preference or important decision
    - 0.5-0.7: useful context or nice-to-know
    - below 0.5: trivial or ephemeral (skip these entirely)
  - "domains": an array of 0-3 short domain tags (e.g., "authentication",
    "deployment", "React") that categorize this knowledge.

Rules:
- Extract only information that would be valuable in a future conversation.
- Each extraction must be self-contained: include enough context that it
  makes sense without the surrounding conversation.
- Do not extract greetings, acknowledgments, or procedural chatter.
- Do not extract information that is purely ephemeral (e.g., "the build
  is running right now").
- Merge related facts into a single extraction rather than creating
  near-duplicates.
- Prefer concrete facts over vague summaries.
- If the conversation contains no extractable information, return
  {"extractions": []}."""

PROMPT_VERSION = "1.0"
_SKIP_THRESHOLD = 0.98
_UPDATE_THRESHOLD = 0.85
_DEFAULT_WINDOW_SIZE = 10
_MAX_RETRIES = 3
_RETRY_DELAYS = [0.0, 5.0, 15.0]

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class ExtractionItem(BaseModel):
    content: str
    weight: float = 0.7
    domains: list[str] = []


class ExtractionResult(BaseModel):
    extractions: list[ExtractionItem]


# ---------------------------------------------------------------------------
# Message formatting
# ---------------------------------------------------------------------------


def format_messages(messages: list[ConversationMessage]) -> str:
    """Format messages as ``[ROLE] (seq=N): content``, one per line."""
    lines = []
    for m in messages:
        lines.append(f"[{m.role.upper()}] (seq={m.sequence_number}): {m.content}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Windowing
# ---------------------------------------------------------------------------


def compute_windows(
    messages: list[ConversationMessage],
    window_size: int = _DEFAULT_WINDOW_SIZE,
) -> list[list[ConversationMessage]]:
    """Split messages into per-turn windows.

    A window boundary occurs when:
    - The window reaches *window_size* messages, OR
    - A ``user`` message follows an ``assistant`` message (turn boundary).

    The turn-boundary message starts the **next** window. Empty windows are
    never created.
    """
    if not messages:
        return []

    windows: list[list[ConversationMessage]] = []
    current: list[ConversationMessage] = []

    for i, msg in enumerate(messages):
        # Detect turn boundary: user message following assistant message
        if (
            current
            and msg.role == "user"
            and current[-1].role == "assistant"
        ):
            windows.append(current)
            current = []

        current.append(msg)

        # Window-size boundary
        if len(current) >= window_size:
            windows.append(current)
            current = []

    if current:
        windows.append(current)

    return windows


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------


async def reconcile_candidate(
    session: AsyncSession,
    content: str,
    weight: float,
    domains: list[str],
    embedding_service: EmbeddingService,
    recall_backend: RecallBackend,
    extraction_run_id: str,
) -> tuple[str, str | None]:
    """Similarity-based dedup against existing active memories.

    Returns ``(action, existing_id)`` where *action* is one of
    ``"create"``, ``"skip"``, or ``"update"``.
    """
    embedding = await embedding_service.embed(content)

    owner = get_owner_id()
    filters = [
        MemoryNode.tenant_id == TENANT_ID,
        MemoryNode.status == "active",
        MemoryNode.is_current.is_(True),
        MemoryNode.owner_id == owner,
    ]

    max_distance = 1.0 - _UPDATE_THRESHOLD  # 0.15
    pairs = await recall_backend.similarity_check(
        embedding, filters, max_distance, 1, session,
    )

    action: str
    existing_id: str | None = None
    similarity: float | None = None
    reason: str

    if not pairs:
        action = "create"
        reason = "no similar memory found"
    else:
        match_id, distance = pairs[0]
        similarity = 1.0 - distance
        existing_id = str(match_id)

        if similarity >= _SKIP_THRESHOLD:
            action = "skip"
            reason = f"near-duplicate (similarity={similarity:.4f})"
        elif similarity >= _UPDATE_THRESHOLD:
            action = "update"
            reason = f"similar memory found (similarity={similarity:.4f})"
        else:
            # Below UPDATE_THRESHOLD but within max_distance -- shouldn't
            # happen since max_distance filters, but handle defensively.
            action = "create"
            existing_id = None
            reason = f"similarity {similarity:.4f} below update threshold"

    decision = ReconciliationDecision(
        extraction_run_id=extraction_run_id,
        candidate_content=content[:200],
        candidate_stub=content[:100],
        nearest_match_id=uuid.UUID(existing_id) if existing_id else None,
        similarity_score=similarity,
        action=action,
        memory_id=uuid.UUID(existing_id) if existing_id else None,
        reason=reason,
        owner_id=get_owner_id(),
        tenant_id=TENANT_ID,
        scope="user",
    )
    session.add(decision)

    return action, existing_id


# ---------------------------------------------------------------------------
# Window extraction
# ---------------------------------------------------------------------------


async def extract_window(
    session: AsyncSession,
    thread: ConversationThread,
    messages: list[ConversationMessage],
    llm_fn: Callable[[str], Awaitable[list[dict[str, Any]]]],
    embedding_service: EmbeddingService,
    recall_backend: RecallBackend,
    extraction_run_id: str,
) -> list[dict[str, Any]]:
    """Extract memories from a single message window.

    Calls *llm_fn* to get candidate extractions, reconciles each against
    existing memories, and persists the results. Does **not** commit --
    the caller commits after updating the extraction cursor.
    """
    from memoryhub_local.services.memory import create_memory, update_memory

    formatted = format_messages(messages)
    raw_extractions = await llm_fn(formatted)

    prompt_hash = hashlib.sha256(
        EXTRACTION_SYSTEM_PROMPT.encode(),
    ).hexdigest()[:16]

    results: list[dict[str, Any]] = []

    for item in raw_extractions:
        content = item.get("content", "")
        if not content:
            continue

        weight = item.get("weight", 0.7)
        if weight < 0.5:
            continue
        weight = max(0.0, min(1.0, weight))

        domains = item.get("domains", [])

        action, existing_id = await reconcile_candidate(
            session,
            content,
            weight,
            domains,
            embedding_service,
            recall_backend,
            extraction_run_id,
        )

        if action == "skip":
            logger.debug("Skipping near-duplicate: %s", content[:80])
            results.append({
                "action": "skip",
                "memory_id": existing_id,
                "content": content[:100],
            })
            continue

        node: MemoryNode
        if action == "create":
            node = await create_memory(
                session,
                content,
                embedding_service,
                weight=weight,
                domains=domains,
                content_type="declarative",
                metadata={"extraction_run_id": extraction_run_id},
            )
            # create_memory hardcodes source="agent"; override for provenance
            node.source = "extraction"
            await session.flush()
        else:
            # action == "update"
            assert existing_id is not None
            node_or_none = await update_memory(
                session,
                existing_id,
                embedding_service,
                content=content,
                weight=weight,
                domains=domains,
            )
            if node_or_none is None:
                logger.warning(
                    "update_memory returned None for %s; creating new instead",
                    existing_id,
                )
                node = await create_memory(
                    session,
                    content,
                    embedding_service,
                    weight=weight,
                    domains=domains,
                    content_type="declarative",
                    metadata={"extraction_run_id": extraction_run_id},
                )
                node.source = "extraction"
                await session.flush()
            else:
                node = node_or_none

        # Record extraction provenance
        provenance = ConversationExtraction(
            memory_node_id=node.id,
            thread_id=thread.id,
            source_messages=[m.sequence_number for m in messages],
            extracted_by="personal_extraction",
            extraction_model="sampling",
            extraction_prompt_hash=prompt_hash,
            tenant_id=TENANT_ID,
        )
        session.add(provenance)

        results.append({
            "action": action,
            "memory_id": str(node.id),
            "content": content[:100],
        })

    await session.flush()
    return results


# ---------------------------------------------------------------------------
# Failure logging
# ---------------------------------------------------------------------------


async def log_failure(
    session: AsyncSession,
    thread_id: uuid.UUID | str,
    window_start: int,
    window_end: int,
    error: Exception,
) -> None:
    """Record an extraction failure for a message window."""
    failure = ConversationExtractionFailure(
        thread_id=uuid.UUID(str(thread_id)),
        window_start=window_start,
        window_end=window_end,
        attempt_count=1,
        last_error=str(error)[:2000],
        tenant_id=TENANT_ID,
    )
    session.add(failure)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


async def extract_from_thread(
    session: AsyncSession,
    thread_id: str,
    *,
    llm_fn: Callable[[str], Awaitable[list[dict[str, Any]]]],
    embedding_service: EmbeddingService,
    recall_backend: RecallBackend,
    extraction_model: str = "sampling",
    max_windows: int | None = None,
) -> dict[str, Any]:
    """Extract memories from unprocessed messages in a thread.

    This is the main entry point for the extraction pipeline. It loads
    messages past the thread's extraction cursor, splits them into windows,
    runs LLM extraction on each window, reconciles against existing
    memories, and advances the cursor.

    Parameters
    ----------
    session:
        Active database session.
    thread_id:
        UUID of the conversation thread to extract from.
    llm_fn:
        Async callable that takes formatted message text and returns a
        list of extraction dicts (content, weight, domains).
    embedding_service:
        Service for generating text embeddings.
    recall_backend:
        Storage backend for similarity checks.
    extraction_model:
        Label for the extraction model (recorded in run ID).
    max_windows:
        If set, process at most this many windows per call.

    Returns
    -------
    dict with extracted_count, cursor, failures, windows_processed,
    and extraction_run_id.
    """
    parsed_id = uuid.UUID(thread_id)

    # Load thread
    result = await session.execute(
        select(ConversationThread).where(
            ConversationThread.id == parsed_id,
            ConversationThread.tenant_id == TENANT_ID,
        )
    )
    thread = result.scalar_one_or_none()
    if thread is None:
        raise ValueError(f"Thread {thread_id} not found")

    # Load unprocessed messages
    msg_result = await session.execute(
        select(ConversationMessage)
        .where(
            ConversationMessage.thread_id == parsed_id,
            ConversationMessage.sequence_number > thread.extraction_cursor,
        )
        .order_by(ConversationMessage.sequence_number)
    )
    messages = list(msg_result.scalars().all())

    if not messages:
        return {
            "extracted_count": 0,
            "cursor": thread.extraction_cursor,
            "message": "no new messages",
        }

    # Compute windows
    windows = compute_windows(messages)

    # Build extraction run ID
    extraction_run_id = (
        f"dream:{extraction_model}:{PROMPT_VERSION}"
        f":{datetime.now(timezone.utc).isoformat()}"
    )

    extracted_count = 0
    failure_count = 0
    windows_processed = 0

    for i, window in enumerate(windows):
        if max_windows is not None and i >= max_windows:
            break

        window_start = window[0].sequence_number
        window_end = window[-1].sequence_number

        try:
            results = await extract_window(
                session,
                thread,
                window,
                llm_fn,
                embedding_service,
                recall_backend,
                extraction_run_id,
            )
            extracted_count += sum(
                1 for r in results if r["action"] in ("create", "update")
            )
        except Exception as exc:
            logger.warning(
                "Extraction failed for window %d-%d in thread %s: %s",
                window_start,
                window_end,
                thread_id,
                exc,
            )
            await log_failure(session, thread.id, window_start, window_end, exc)
            failure_count += 1

        # Advance cursor past this window regardless of success/failure
        thread.extraction_cursor = window_end
        thread.last_extracted_at = datetime.now(timezone.utc)
        windows_processed += 1

    await session.commit()

    return {
        "extracted_count": extracted_count,
        "cursor": thread.extraction_cursor,
        "failures": failure_count,
        "windows_processed": windows_processed,
        "extraction_run_id": extraction_run_id,
    }


# ---------------------------------------------------------------------------
# Pending-thread discovery
# ---------------------------------------------------------------------------


async def get_pending_threads(session: AsyncSession) -> list[dict[str, Any]]:
    """Find threads with unprocessed messages.

    Returns a list of dicts with ``id``, ``title``, and
    ``pending_count`` (number of messages past the extraction cursor).
    """
    stmt = (
        select(
            ConversationThread.id,
            ConversationThread.title,
            ConversationThread.extraction_cursor,
            func.max(ConversationMessage.sequence_number).label("max_seq"),
        )
        .join(
            ConversationMessage,
            ConversationMessage.thread_id == ConversationThread.id,
        )
        .where(
            ConversationThread.tenant_id == TENANT_ID,
            ConversationThread.status == "active",
        )
        .group_by(ConversationThread.id)
        .having(
            func.max(ConversationMessage.sequence_number)
            > ConversationThread.extraction_cursor,
        )
    )

    result = await session.execute(stmt)
    rows = result.all()

    return [
        {
            "id": str(row.id),
            "title": row.title,
            "pending_count": row.max_seq - row.extraction_cursor,
        }
        for row in rows
    ]


# ---------------------------------------------------------------------------
# HTTP LLM factory
# ---------------------------------------------------------------------------


def make_http_llm_fn(
    model: str,
    url: str,
    api_key: str | None = None,
) -> Callable[[str], Awaitable[list[dict[str, Any]]]]:
    """Return an async callable that calls an OpenAI-compatible chat endpoint.

    The callable takes formatted message text and returns a list of
    extraction dicts parsed from the LLM's JSON response.
    """

    async def _call(messages_text: str) -> list[dict[str, Any]]:
        import httpx

        headers: dict[str, str] = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
                {"role": "user", "content": messages_text},
            ],
            "temperature": 0.0,
            "max_tokens": 4000,
            "response_format": {"type": "json_object"},
        }

        last_error: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            if attempt > 0:
                await asyncio.sleep(_RETRY_DELAYS[attempt])
            try:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    resp = await client.post(
                        f"{url.rstrip('/')}/chat/completions",
                        json=body,
                        headers=headers,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    text = data["choices"][0]["message"]["content"]
                    parsed = json.loads(text)
                    return parsed.get("extractions", [])
            except (
                httpx.HTTPError,
                json.JSONDecodeError,
                KeyError,
                IndexError,
            ) as exc:
                last_error = exc
                logger.warning(
                    "LLM call attempt %d failed: %s", attempt + 1, exc,
                )

        raise RuntimeError(
            f"LLM extraction failed after {_MAX_RETRIES} attempts: {last_error}",
        )

    return _call

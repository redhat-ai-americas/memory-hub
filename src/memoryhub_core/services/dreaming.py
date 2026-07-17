"""Dreaming pipeline -- extract memories from thread messages.

Reads conversation messages via a cursor-based sliding window, sends them
to an LLM, and produces memory_nodes with full provenance tracking through
conversation_extractions records.

Three extraction modes:
  - per_turn: windows aligned to user/assistant turn boundaries (default)
  - per_session: all unextracted messages in one pass
  - per_message: window of 1 message each

Design doc: planning/memory-extraction-pipeline.md.
"""

import asyncio
import hashlib
import json
import logging
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import yaml
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from memoryhub_core.config import AppSettings
from memoryhub_core.models.conversation import (
    ConversationExtraction,
    ConversationExtractionFailure,
    ConversationMessage,
    ConversationThread,
)
from memoryhub_core.models.memory import MemoryNode
from memoryhub_core.services.reconciliation import (
    ExtractionCandidate,
    ReconciliationResult,
    reconcile_candidate,
)

logger = logging.getLogger(__name__)

_MAX_RETRIES = 4
_RETRY_DELAYS = [0.0, 30.0, 60.0, 120.0]

_prompt_cache: dict[str, tuple[str, str]] = {}


def _load_prompt() -> tuple[str, str]:
    """Load the extraction prompt and return (system_prompt, prompt_hash)."""
    if "default" in _prompt_cache:
        return _prompt_cache["default"]

    prompt_path = (
        Path(__file__).resolve().parents[3] / "prompts" / "conversation_extraction.yaml"
    )
    raw = prompt_path.read_text()
    data = yaml.safe_load(raw)
    system_prompt = data["system_prompt"]
    prompt_hash = hashlib.sha256(system_prompt.encode()).hexdigest()

    _prompt_cache["default"] = (system_prompt, prompt_hash)
    return system_prompt, prompt_hash


def _format_messages(messages: list[ConversationMessage]) -> str:
    """Format ORM message objects into a readable conversation transcript."""
    lines = []
    for msg in messages:
        role = msg.role.upper()
        content = msg.content or "[content stored in S3]"
        lines.append(f"[{role}] (seq={msg.sequence_number}): {content}")
    return "\n".join(lines)


def _parse_json_best_effort(text: str) -> dict | None:
    """Parse JSON from LLM response, stripping code fences if needed."""
    if not text:
        return None
    cleaned = re.sub(r"^```(?:json)?\s*\n?", "", text.strip())
    cleaned = re.sub(r"\n?```\s*$", "", cleaned)
    try:
        return json.loads(cleaned)
    except (json.JSONDecodeError, ValueError):
        return None


def _compute_windows(
    messages: list[ConversationMessage],
    mode: str,
    window_size: int,
) -> list[list[ConversationMessage]]:
    """Partition messages into extraction windows based on mode."""
    if not messages:
        return []

    if mode == "per_session":
        return [messages]

    if mode == "per_message":
        return [[m] for m in messages]

    # per_turn (default): windows aligned to turn boundaries
    # A turn ends when the role switches from assistant back to user
    # (or at the window_size limit).
    windows: list[list[ConversationMessage]] = []
    current: list[ConversationMessage] = []

    for msg in messages:
        current.append(msg)
        is_turn_end = msg.role == "assistant" and len(current) >= 2
        is_window_full = len(current) >= window_size

        if is_turn_end or is_window_full:
            windows.append(current)
            current = []

    if current:
        windows.append(current)

    return windows


async def _call_extraction_llm(
    formatted_messages: str,
    system_prompt: str,
    *,
    client: httpx.AsyncClient,
    model: str,
    url: str,
) -> list[dict[str, Any]]:
    """Call the extraction LLM and return parsed extractions.

    Uses OpenAI-compatible /v1/chat/completions endpoint.
    Retries: immediate once, then exponential backoff (30s, 60s, 120s).
    """
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": formatted_messages},
    ]

    last_error: Exception | None = None

    for attempt in range(_MAX_RETRIES):
        try:
            response = await client.post(
                f"{url.rstrip('/')}/chat/completions",
                json={
                    "model": model,
                    "messages": messages,
                    "temperature": 0.0,
                    "max_tokens": 4000,
                    "response_format": {"type": "json_object"},
                },
            )
            response.raise_for_status()
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            last_error = exc
            if attempt < _MAX_RETRIES - 1:
                delay = _RETRY_DELAYS[attempt]
                logger.warning(
                    "Extraction LLM connection error (attempt %d/%d): %s -- retrying in %.0fs",
                    attempt + 1, _MAX_RETRIES, exc, delay,
                )
                await asyncio.sleep(delay)
            continue
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status in (429, 502, 503, 504):
                last_error = exc
                if attempt < _MAX_RETRIES - 1:
                    delay = _RETRY_DELAYS[attempt]
                    logger.warning(
                        "Extraction LLM returned %d (attempt %d/%d) -- retrying in %.0fs",
                        status, attempt + 1, _MAX_RETRIES, delay,
                    )
                    await asyncio.sleep(delay)
                continue
            raise
        else:
            raw_content = response.json()["choices"][0]["message"]["content"]
            parsed = _parse_json_best_effort(raw_content)
            if parsed is None:
                raise ValueError(f"LLM returned non-JSON response: {raw_content[:200]}")
            return parsed.get("extractions", [])

    raise last_error or RuntimeError("Extraction LLM failed after all retries")


async def _extract_window(
    session: AsyncSession,
    *,
    thread: ConversationThread,
    messages: list[ConversationMessage],
    client: httpx.AsyncClient,
    model: str,
    url: str,
    embedding_service: Any,
    extraction_run_id: str,
    s3_adapter: Any | None = None,
    dry_run: bool = False,
) -> list[ReconciliationResult]:
    """Extract memories from a single window of messages.

    Returns list of ReconciliationResult decisions from this window.
    """
    system_prompt, prompt_hash = _load_prompt()
    formatted = _format_messages(messages)

    extractions = await _call_extraction_llm(
        formatted,
        system_prompt,
        client=client,
        model=model,
        url=url,
    )

    source_seqs = [m.sequence_number for m in messages]
    decisions: list[ReconciliationResult] = []
    committed_ids: list[uuid.UUID] = []

    for item in extractions:
        content = item.get("content", "").strip()
        if not content:
            continue

        weight = item.get("weight", 0.7)
        if not isinstance(weight, int | float) or weight < 0.5:
            continue

        weight = min(max(float(weight), 0.0), 1.0)
        domains = item.get("domains")
        if domains and not isinstance(domains, list):
            domains = None

        metadata = {
            "extraction_source": {
                "thread_id": str(thread.id),
                "source_messages": source_seqs,
            },
        }

        candidate = ExtractionCandidate(
            content=content,
            weight=weight,
            content_type=item.get("content_type", "experiential"),
            domains=domains,
            metadata=metadata,
            thread_id=thread.id,
            source_messages=source_seqs,
            extraction_model=model,
            extraction_prompt_hash=prompt_hash,
        )

        decision = await reconcile_candidate(
            candidate,
            thread.owner_id,
            thread.scope,
            thread.scope_id,
            session,
            embedding_service,
            tenant_id=thread.tenant_id,
            extraction_run_id=extraction_run_id,
            actor_id=thread.actor_id,
            s3_adapter=s3_adapter,
            dry_run=dry_run,
        )
        decisions.append(decision)

        if dry_run:
            continue

        if decision.action == "skip":
            logger.info(
                "Reconciliation skipped duplicate for thread %s (score=%.3f)",
                thread.id, decision.similarity_score or 0,
            )
            continue

        if decision.memory_id is None:
            logger.warning(
                "Reconciliation %s produced no memory for thread %s",
                decision.action, thread.id,
            )
            continue

        extraction_record = ConversationExtraction(
            id=uuid.uuid4(),
            memory_node_id=decision.memory_id,
            thread_id=thread.id,
            source_messages=source_seqs,
            extracted_by="conversation_extraction_pipeline",
            extraction_model=model,
            extraction_prompt_hash=prompt_hash,
            tenant_id=thread.tenant_id,
        )
        session.add(extraction_record)
        committed_ids.append(decision.memory_id)

    if committed_ids:
        await session.commit()

    return decisions


async def _log_failure(
    session: AsyncSession,
    *,
    thread_id: uuid.UUID,
    window_start: int,
    window_end: int,
    error: str,
    tenant_id: str,
) -> None:
    """Record an extraction failure in the database."""
    failure = ConversationExtractionFailure(
        id=uuid.uuid4(),
        thread_id=thread_id,
        window_start=window_start,
        window_end=window_end,
        attempt_count=_MAX_RETRIES,
        last_error=error[:2000],
        last_attempt_at=datetime.now(UTC),
        tenant_id=tenant_id,
    )
    session.add(failure)
    await session.commit()


def _check_circuit_breaker(
    decisions: list[ReconciliationResult],
    *,
    max_create_ratio: float = 20.0,
    min_decisions: int = 5,
    has_existing_memories: bool = True,
) -> str | None:
    """Return a reason string if the circuit breaker trips, else None.

    Trips when the create:update ratio exceeds max_create_ratio after
    at least min_decisions have been made. Skips the all-creates check
    when has_existing_memories is False (initial population is expected
    to produce only creates).
    """
    if len(decisions) < min_decisions:
        return None
    creates = sum(1 for d in decisions if d.action == "create")
    updates = sum(1 for d in decisions if d.action == "update")
    skips = sum(1 for d in decisions if d.action == "skip")

    if updates == 0 and skips == 0 and creates >= min_decisions and has_existing_memories:
        return f"all creates ({creates}), zero updates (threshold {max_create_ratio}:1)"
    if updates > 0 and creates / updates > max_create_ratio:
        return f"create:update ratio {creates}:{updates} exceeds threshold {max_create_ratio}:1"
    return None


async def extract_from_thread(
    session: AsyncSession,
    *,
    thread_id: uuid.UUID,
    tenant_id: str,
    owner_id: str,
    embedding_service: Any,
    s3_adapter: Any | None = None,
    model_override: str | None = None,
    url_override: str | None = None,
    turn_range: tuple[int, int] | None = None,
    dry_run: bool = False,
    circuit_breaker_ratio: float = 20.0,
    circuit_breaker_min: int = 5,
) -> dict[str, Any]:
    """Extract memories from a conversation thread.

    Args:
        session: Database session.
        thread_id: Thread to extract from.
        tenant_id: Tenant identifier.
        owner_id: Caller identity (for auth context, not used for memory ownership).
        embedding_service: Embedding service for create_memory.
        s3_adapter: Optional S3 adapter for large memories.
        model_override: Override the configured extraction model.
        url_override: Override the configured extraction model URL.
        turn_range: Optional (start_seq, end_seq) to extract only a specific range.
        dry_run: Produce decisions without committing writes.
        circuit_breaker_ratio: Max create:update ratio before halting.
        circuit_breaker_min: Minimum decisions before circuit breaker arms.

    Returns:
        Dict with extracted_count, cursor, failures count, extraction_run_id.
    """
    settings = AppSettings()
    model = model_override or settings.conv_extraction_model
    url = url_override or settings.conv_extraction_model_url

    if not model or not url:
        raise ValueError(
            "Extraction model and URL must be configured. "
            "Set MEMORYHUB_CONV_EXTRACTION_MODEL and MEMORYHUB_CONV_EXTRACTION_MODEL_URL, "
            "or pass model/model_url in options."
        )

    _, prompt_hash = _load_prompt()
    extraction_run_id = f"dream:{model}:{prompt_hash}:{datetime.now(UTC).isoformat()}"

    # Load thread
    stmt = select(ConversationThread).where(
        ConversationThread.id == thread_id,
        ConversationThread.tenant_id == tenant_id,
        ConversationThread.deleted_at.is_(None),
    )
    result = await session.execute(stmt)
    thread = result.scalar_one_or_none()

    if thread is None:
        from memoryhub_core.services.exceptions import ThreadNotFoundError
        raise ThreadNotFoundError(thread_id)

    # Determine extraction mode from retention_policy
    retention = thread.retention_policy or {}
    mode = retention.get("extraction_mode", "per_turn")
    if mode not in ("per_turn", "per_session", "per_message"):
        mode = "per_turn"

    # Load unextracted messages
    msg_stmt = select(ConversationMessage).where(
        ConversationMessage.thread_id == thread_id,
    )

    if turn_range is not None:
        start_seq, end_seq = turn_range
        msg_stmt = msg_stmt.where(
            ConversationMessage.sequence_number >= start_seq,
            ConversationMessage.sequence_number <= end_seq,
        )
    else:
        msg_stmt = msg_stmt.where(
            ConversationMessage.sequence_number > thread.extraction_cursor,
        )

    msg_stmt = msg_stmt.order_by(ConversationMessage.sequence_number.asc())
    msg_result = await session.execute(msg_stmt)
    messages = list(msg_result.scalars().all())

    if not messages:
        return {
            "extracted_count": 0,
            "cursor": thread.extraction_cursor,
            "failures": 0,
            "extraction_run_id": extraction_run_id,
        }

    # Build windows
    windows = _compute_windows(messages, mode, settings.conv_extraction_window_size)

    existing_count_result = await session.execute(
        select(func.count()).select_from(MemoryNode).where(
            MemoryNode.owner_id == thread.owner_id,
            MemoryNode.tenant_id == thread.tenant_id,
            MemoryNode.is_current.is_(True),
            MemoryNode.deleted_at.is_(None),
        )
    )
    has_existing_memories = existing_count_result.scalar_one() > 0

    total_extracted = 0
    total_failures = 0
    all_decisions: list[ReconciliationResult] = []
    circuit_breaker_tripped = False
    circuit_breaker_reason: str | None = None
    windows_completed = 0

    headers = {}
    if settings.conv_extraction_api_key:
        headers["Authorization"] = f"Bearer {settings.conv_extraction_api_key}"

    async with httpx.AsyncClient(
        timeout=settings.conv_extraction_timeout, verify=False, headers=headers,
    ) as client:
        for window in windows:
            window_start = window[0].sequence_number
            window_end = window[-1].sequence_number

            try:
                window_decisions = await _extract_window(
                    session,
                    thread=thread,
                    messages=window,
                    client=client,
                    model=model,
                    url=url,
                    embedding_service=embedding_service,
                    extraction_run_id=extraction_run_id,
                    s3_adapter=s3_adapter,
                    dry_run=dry_run,
                )
                all_decisions.extend(window_decisions)
                total_extracted += sum(
                    1 for d in window_decisions
                    if d.memory_id is not None and d.action != "skip"
                )
            except Exception as exc:
                logger.warning(
                    "Extraction failed for thread %s window [%d-%d]: %s",
                    thread_id, window_start, window_end, exc,
                )
                await _log_failure(
                    session,
                    thread_id=thread_id,
                    window_start=window_start,
                    window_end=window_end,
                    error=str(exc),
                    tenant_id=tenant_id,
                )
                total_failures += 1

            windows_completed += 1

            # Advance cursor past this window regardless of success/failure
            # (design doc: cursor advances past failed windows to avoid blocking)
            if turn_range is None and not dry_run:
                thread.extraction_cursor = window_end
                thread.last_extracted_at = datetime.now(UTC)
                await session.commit()

            # Circuit breaker check
            trip_reason = _check_circuit_breaker(
                all_decisions,
                max_create_ratio=circuit_breaker_ratio,
                min_decisions=circuit_breaker_min,
                has_existing_memories=has_existing_memories,
            )
            if trip_reason is not None:
                circuit_breaker_tripped = True
                circuit_breaker_reason = trip_reason
                logger.warning(
                    "Circuit breaker tripped for run %s: %s",
                    extraction_run_id, trip_reason,
                )
                break

    response: dict[str, Any] = {
        "extracted_count": total_extracted,
        "cursor": thread.extraction_cursor,
        "failures": total_failures,
        "extraction_run_id": extraction_run_id,
    }

    if dry_run:
        response["dry_run"] = True
        response["decisions"] = [d.model_dump() for d in all_decisions]

    if circuit_breaker_tripped:
        response["circuit_breaker_tripped"] = True
        response["circuit_breaker_reason"] = circuit_breaker_reason
        response["windows_completed"] = windows_completed
        response["windows_total"] = len(windows)

    return response

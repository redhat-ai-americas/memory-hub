"""Service layer for conversation thread CRUD operations."""

import asyncio
import io
import uuid
from datetime import UTC, datetime, timedelta
from functools import partial

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from memoryhub_core.config import AppSettings
from memoryhub_core.models.conversation import ConversationMessage, ConversationThread
from memoryhub_core.models.schemas import (
    ConversationMessageCreate,
    ConversationMessageRead,
    ConversationThreadCreate,
    ConversationThreadRead,
)
from memoryhub_core.services.exceptions import ThreadNotActiveError, ThreadNotFoundError
from memoryhub_core.storage.s3 import S3StorageAdapter


async def _store_message_s3(
    s3_adapter: S3StorageAdapter,
    tenant_id: str,
    thread_id: uuid.UUID,
    sequence_number: int,
    content: str,
) -> str:
    """Store message content in S3 and return the content_ref key.

    Uses the same async wrapper pattern as the S3StorageAdapter's put_content,
    but with a different key format for conversation threads.

    Key format: threads/{tenant_id}/{thread_id}/{sequence_number}
    """
    await s3_adapter.ensure_bucket()
    key = f"threads/{tenant_id}/{thread_id}/{sequence_number}"
    data = content.encode("utf-8")
    stream = io.BytesIO(data)
    # Access the private members directly to avoid rewriting the key format
    await asyncio.to_thread(
        partial(
            s3_adapter._client.put_object,
            s3_adapter._bucket,
            key,
            stream,
            length=len(data),
            content_type="text/plain; charset=utf-8",
        )
    )
    return key


async def create_thread(
    session: AsyncSession,
    *,
    tenant_id: str,
    data: ConversationThreadCreate,
    owner_id: str,
    actor_id: str | None = None,
    driver_id: str | None = None,
) -> ConversationThreadRead:
    """Create a new conversation thread.

    Args:
        session: Database session
        tenant_id: Tenant identifier
        data: Thread creation data
        owner_id: User who owns the thread
        actor_id: Actor agent identifier (optional)
        driver_id: Driver agent identifier (optional)

    Returns:
        Created thread read schema
    """
    # Build participant list: ensure owner_id is included
    participant_ids = list(data.participant_ids) if data.participant_ids else []
    if owner_id not in participant_ids:
        participant_ids.append(owner_id)

    # Resolve retention policy based on scope
    # TODO: Replace with actual policy resolution once retention policies are implemented
    if data.scope == "user":
        retention_policy = {
            "ttl_days": 90,
            "cascade_to_memories": "delete",
            "min_retention_days": 30,
            "inherited_from": "system:default",
        }
    else:  # project scope
        retention_policy = {
            "ttl_days": 365,
            "cascade_to_memories": "delete",
            "min_retention_days": 30,
            "inherited_from": "system:default",
        }

    # Compute expiration timestamp
    ttl_days = retention_policy["ttl_days"]
    created_at = datetime.now(UTC)
    expires_at = created_at + timedelta(days=ttl_days)

    # Create the thread
    thread = ConversationThread(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        scope=data.scope,
        scope_id=None,  # Not on ConversationThreadCreate yet
        owner_id=owner_id,
        actor_id=actor_id,
        driver_id=driver_id,
        participant_ids=participant_ids,
        participant_access=data.participant_access,
        title=data.title,
        a2a_context_id=data.a2a_context_id,
        metadata_=data.metadata,
        retention_policy=retention_policy,
        created_at=created_at,
        expires_at=expires_at,
        status="active",
    )

    session.add(thread)
    await session.commit()
    await session.refresh(thread)

    return ConversationThreadRead.model_validate(thread)


async def get_thread(
    session: AsyncSession,
    *,
    tenant_id: str,
    thread_id: uuid.UUID,
    include_messages: bool = True,
    limit: int = 50,
    before_sequence: int | None = None,
    s3_adapter: S3StorageAdapter | None = None,
) -> dict | None:
    """Retrieve a conversation thread with optional message history.

    Args:
        session: Database session
        tenant_id: Tenant identifier
        thread_id: Thread UUID
        include_messages: Whether to include message history
        limit: Maximum number of messages to return
        before_sequence: Return messages before this sequence number
        s3_adapter: S3 adapter for fetching S3-stored message content

    Returns:
        Dict with thread and optional messages, or None if not found
    """
    # Query thread
    stmt = select(ConversationThread).where(
        ConversationThread.id == thread_id,
        ConversationThread.tenant_id == tenant_id,
        ConversationThread.deleted_at.is_(None),
    )
    result = await session.execute(stmt)
    thread = result.scalar_one_or_none()

    if thread is None:
        return None

    # Build result with thread
    response = {"thread": ConversationThreadRead.model_validate(thread)}

    # Include messages if requested
    if include_messages:
        # Build message query
        msg_stmt = select(ConversationMessage).where(ConversationMessage.thread_id == thread_id)
        if before_sequence is not None:
            msg_stmt = msg_stmt.where(ConversationMessage.sequence_number < before_sequence)
        msg_stmt = msg_stmt.order_by(ConversationMessage.sequence_number.asc())
        msg_stmt = msg_stmt.limit(limit + 1)  # Fetch one extra to detect has_more

        msg_result = await session.execute(msg_stmt)
        messages = list(msg_result.scalars().all())

        # Check if there are more messages
        has_more = len(messages) > limit
        if has_more:
            messages.pop()  # Remove the extra row

        # Fetch S3 content if needed
        message_reads = []
        for msg in messages:
            if msg.storage_type == "s3" and s3_adapter is not None and msg.content_ref:
                # Fetch from S3
                msg.content = await s3_adapter.get_content(msg.content_ref)
            message_reads.append(ConversationMessageRead.model_validate(msg))

        response["messages"] = message_reads
        response["has_more"] = has_more

    return response


async def list_threads(
    session: AsyncSession,
    *,
    tenant_id: str,
    owner_id: str | None = None,
    scope: str | None = None,
    scope_id: str | None = None,
    status: str = "active",
    participant_id: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[ConversationThreadRead], int]:
    """List conversation threads matching filters.

    Args:
        session: Database session
        tenant_id: Tenant identifier
        owner_id: Filter by owner
        scope: Filter by scope (user/project)
        scope_id: Filter by scope_id
        status: Filter by status (default: active)
        participant_id: Filter by participant
        limit: Maximum results
        offset: Result offset for pagination

    Returns:
        Tuple of (thread list, total count)
    """
    # Build base filters
    filters = [ConversationThread.tenant_id == tenant_id]

    if owner_id is not None:
        filters.append(ConversationThread.owner_id == owner_id)
    if scope is not None:
        filters.append(ConversationThread.scope == scope)
    if scope_id is not None:
        filters.append(ConversationThread.scope_id == scope_id)
    if status is not None:
        filters.append(ConversationThread.status == status)
    if participant_id is not None:
        # PostgreSQL array contains check
        filters.append(ConversationThread.participant_ids.any(participant_id))

    # Count query
    count_stmt = select(func.count()).select_from(ConversationThread).where(*filters)
    count_result = await session.execute(count_stmt)
    total_count = count_result.scalar_one()

    # Data query
    data_stmt = (
        select(ConversationThread)
        .where(*filters)
        .order_by(ConversationThread.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    data_result = await session.execute(data_stmt)
    threads = data_result.scalars().all()

    thread_reads = [ConversationThreadRead.model_validate(t) for t in threads]
    return thread_reads, total_count


async def append_message(
    session: AsyncSession,
    *,
    tenant_id: str,
    thread_id: uuid.UUID,
    data: ConversationMessageCreate,
    s3_adapter: S3StorageAdapter | None = None,
) -> ConversationMessageRead:
    """Append a message to a conversation thread.

    Args:
        session: Database session
        tenant_id: Tenant identifier
        thread_id: Thread UUID
        data: Message creation data
        s3_adapter: S3 adapter for storing large message content

    Returns:
        Created message read schema

    Raises:
        ThreadNotFoundError: If thread does not exist
        ThreadNotActiveError: If thread is not active
    """
    # Load thread
    stmt = select(ConversationThread).where(
        ConversationThread.id == thread_id,
        ConversationThread.tenant_id == tenant_id,
        ConversationThread.deleted_at.is_(None),
    )
    result = await session.execute(stmt)
    thread = result.scalar_one_or_none()

    if thread is None:
        raise ThreadNotFoundError(thread_id)

    if thread.status != "active":
        raise ThreadNotActiveError(thread_id, thread.status)

    # Compute sequence number
    seq_stmt = select(func.coalesce(func.max(ConversationMessage.sequence_number), 0) + 1).where(
        ConversationMessage.thread_id == thread_id
    )
    seq_result = await session.execute(seq_stmt)
    sequence_number = seq_result.scalar_one()

    # Compute content size and determine storage
    content_size = len(data.content.encode("utf-8")) if data.content else None
    storage_type = "inline"
    content_ref = None
    content_to_store = data.content

    # Check if we should use S3
    app_settings = AppSettings()
    if (
        data.content is not None
        and content_size is not None
        and content_size > app_settings.conv_inline_max_bytes
        and s3_adapter is not None
    ):
        # Upload to S3
        content_ref = await _store_message_s3(s3_adapter, tenant_id, thread_id, sequence_number, data.content)
        storage_type = "s3"
        content_to_store = None  # Don't store in DB

    # Create message
    message = ConversationMessage(
        id=uuid.uuid4(),
        thread_id=thread_id,
        sequence_number=sequence_number,
        role=data.role,
        actor_id=data.actor_id,
        content=content_to_store,
        tool_call_id=data.tool_call_id,
        metadata_=data.metadata,
        storage_type=storage_type,
        content_size=content_size,
        content_ref=content_ref,
        tenant_id=tenant_id,
        created_at=datetime.now(UTC),
    )

    session.add(message)
    await session.commit()
    await session.refresh(message)

    # For S3 messages, restore content for the response
    if storage_type == "s3" and data.content is not None:
        message.content = data.content

    return ConversationMessageRead.model_validate(message)


async def archive_thread(
    session: AsyncSession,
    *,
    tenant_id: str,
    thread_id: uuid.UUID,
) -> ConversationThreadRead:
    """Archive a conversation thread.

    Args:
        session: Database session
        tenant_id: Tenant identifier
        thread_id: Thread UUID

    Returns:
        Updated thread read schema

    Raises:
        ThreadNotFoundError: If thread does not exist
        ThreadNotActiveError: If thread is not active
    """
    # Load thread
    stmt = select(ConversationThread).where(
        ConversationThread.id == thread_id,
        ConversationThread.tenant_id == tenant_id,
        ConversationThread.deleted_at.is_(None),
    )
    result = await session.execute(stmt)
    thread = result.scalar_one_or_none()

    if thread is None:
        raise ThreadNotFoundError(thread_id)

    if thread.status != "active":
        raise ThreadNotActiveError(thread_id, thread.status)

    # Archive the thread
    thread.status = "archived"
    thread.archived_at = datetime.now(UTC)

    await session.commit()
    await session.refresh(thread)

    return ConversationThreadRead.model_validate(thread)

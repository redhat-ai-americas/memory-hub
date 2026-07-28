"""Conversation thread operations for personal edition."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from memoryhub_local.identity import TENANT_ID, get_owner_id
from memoryhub_local.models.conversation import (
    ConversationMessage,
    ConversationThread,
)


async def create_thread(
    session: AsyncSession,
    scope: str,
    *,
    title: str | None = None,
    participant_ids: list[str] | None = None,
    metadata: dict | None = None,
) -> dict:
    """Create a new conversation thread."""
    owner = get_owner_id()
    thread = ConversationThread(
        scope=scope,
        title=title,
        owner_id=owner,
        actor_id=owner,
        tenant_id=TENANT_ID,
        participant_ids=participant_ids or [owner],
        status="active",
        metadata_=metadata,
    )
    session.add(thread)
    await session.commit()
    await session.refresh(thread)
    return _thread_to_dict(thread)


async def append_message(
    session: AsyncSession,
    thread_id: str,
    role: str,
    content: str,
    *,
    actor_id: str | None = None,
    metadata: dict | None = None,
) -> dict:
    """Append a message to a thread."""
    parsed_id = uuid.UUID(thread_id)

    # Get next sequence number
    result = await session.execute(
        select(func.coalesce(func.max(ConversationMessage.sequence_number), 0)).where(
            ConversationMessage.thread_id == parsed_id,
        )
    )
    next_seq = (result.scalar() or 0) + 1

    msg = ConversationMessage(
        thread_id=parsed_id,
        sequence_number=next_seq,
        role=role,
        content=content,
        storage_type="inline",
        actor_id=actor_id or get_owner_id(),
        tenant_id=TENANT_ID,
        metadata_=metadata,
    )
    session.add(msg)
    await session.commit()
    await session.refresh(msg)
    return _message_to_dict(msg)


async def get_thread(
    session: AsyncSession,
    thread_id: str,
    *,
    limit: int = 50,
    include_messages: bool = True,
) -> dict:
    """Get a thread with its messages."""
    parsed_id = uuid.UUID(thread_id)

    result = await session.execute(
        select(ConversationThread).where(
            ConversationThread.id == parsed_id,
            ConversationThread.tenant_id == TENANT_ID,
        )
    )
    thread = result.scalar_one_or_none()
    if thread is None:
        from fastmcp.exceptions import ToolError
        raise ToolError(f"Thread {thread_id} not found.")

    response = {"thread": _thread_to_dict(thread)}

    if include_messages:
        msg_result = await session.execute(
            select(ConversationMessage)
            .where(ConversationMessage.thread_id == parsed_id)
            .order_by(ConversationMessage.sequence_number)
            .limit(limit)
        )
        messages = list(msg_result.scalars().all())

        # Get total count
        count_result = await session.execute(
            select(func.count()).select_from(ConversationMessage).where(
                ConversationMessage.thread_id == parsed_id,
            )
        )
        total = count_result.scalar() or 0

        response["messages"] = [_message_to_dict(m) for m in messages]
        response["total_messages"] = total
        response["has_more"] = total > limit

    return response


async def list_threads(
    session: AsyncSession,
    *,
    scope: str | None = None,
    status: str = "active",
    limit: int = 20,
) -> dict:
    """List conversation threads."""
    owner = get_owner_id()
    stmt = select(ConversationThread).where(
        ConversationThread.tenant_id == TENANT_ID,
        ConversationThread.owner_id == owner,
        ConversationThread.status == status,
    )
    if scope:
        stmt = stmt.where(ConversationThread.scope == scope)

    stmt = stmt.order_by(ConversationThread.created_at.desc()).limit(limit)
    result = await session.execute(stmt)
    threads = list(result.scalars().all())

    # Total count
    count_stmt = select(func.count()).select_from(ConversationThread).where(
        ConversationThread.tenant_id == TENANT_ID,
        ConversationThread.owner_id == owner,
        ConversationThread.status == status,
    )
    if scope:
        count_stmt = count_stmt.where(ConversationThread.scope == scope)
    count_result = await session.execute(count_stmt)
    total = count_result.scalar() or 0

    return {
        "threads": [_thread_to_dict(t) for t in threads],
        "total": total,
    }


async def archive_thread(
    session: AsyncSession,
    thread_id: str,
) -> dict:
    """Archive a conversation thread."""
    parsed_id = uuid.UUID(thread_id)
    now = datetime.now(timezone.utc)

    await session.execute(
        update(ConversationThread)
        .where(
            ConversationThread.id == parsed_id,
            ConversationThread.tenant_id == TENANT_ID,
        )
        .values(status="archived", archived_at=now)
    )
    await session.commit()

    result = await session.execute(
        select(ConversationThread).where(ConversationThread.id == parsed_id)
    )
    thread = result.scalar_one_or_none()
    if thread is None:
        from fastmcp.exceptions import ToolError
        raise ToolError(f"Thread {thread_id} not found.")
    return _thread_to_dict(thread)


async def delete_thread(
    session: AsyncSession,
    thread_id: str,
    *,
    cascade: str = "delete",
) -> dict:
    """Soft-delete a thread and optionally its messages."""
    from sqlalchemy import delete as sql_delete

    parsed_id = uuid.UUID(thread_id)
    now = datetime.now(timezone.utc)

    # Count messages before deletion
    count_result = await session.execute(
        select(func.count()).select_from(ConversationMessage).where(
            ConversationMessage.thread_id == parsed_id,
        )
    )
    msg_count = count_result.scalar() or 0

    messages_deleted = 0
    if cascade == "delete" and msg_count > 0:
        await session.execute(
            sql_delete(ConversationMessage).where(
                ConversationMessage.thread_id == parsed_id,
            )
        )
        messages_deleted = msg_count

    # Mark thread as deleted
    await session.execute(
        update(ConversationThread)
        .where(
            ConversationThread.id == parsed_id,
            ConversationThread.tenant_id == TENANT_ID,
        )
        .values(status="deleted", deleted_at=now)
    )

    await session.commit()

    return {
        "id": thread_id,
        "status": "deleted",
        "messages_deleted": messages_deleted,
        "cascade_mode": cascade,
    }


def _thread_to_dict(thread: ConversationThread) -> dict:
    return {
        "id": str(thread.id),
        "title": thread.title,
        "scope": thread.scope,
        "status": thread.status,
        "owner_id": thread.owner_id,
        "created_at": thread.created_at.isoformat() if thread.created_at else None,
    }


def _message_to_dict(msg: ConversationMessage) -> dict:
    return {
        "id": str(msg.id),
        "thread_id": str(msg.thread_id),
        "sequence_number": msg.sequence_number,
        "role": msg.role,
        "content": msg.content,
        "actor_id": msg.actor_id,
        "created_at": msg.created_at.isoformat() if msg.created_at else None,
    }

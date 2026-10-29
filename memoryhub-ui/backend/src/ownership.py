"""Which agents belong to which person.

A person signs in to the dashboard with one identity (their OpenShift or
local-account username), while their agents write memories under their own
OAuth client IDs. To let users see "their" memories and manage "their" agents
the BFF keeps an explicit owner for each agent:

* an agent a user creates on the Clients screen is theirs;
* a user can link an existing agent by proving they hold its client secret
  (checked with a client_credentials grant against the auth service);
* a platform admin can assign an owner (this never reveals memory content);
* agents that act for a person (``driver_id`` on writes and audit events)
  belong to that person automatically.
"""

from __future__ import annotations

import logging

import httpx
from memoryhub_core.models.audit import AuditLog
from memoryhub_core.models.memory import MemoryNode
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import Settings

logger = logging.getLogger(__name__)

OWNERS = "memoryhub_ui_agent_owners"


async def ensure_table(db: AsyncSession) -> None:
    from src.schema import require

    await require(db)


async def explicit_owners(db: AsyncSession, tenant_id: str) -> dict[str, str]:
    """client_id -> owner, from the owners table. Never raises."""
    try:
        await ensure_table(db)
        rows = (
            await db.execute(text(f"SELECT client_id, owner FROM {OWNERS} WHERE tenant_id = :t"), {"t": tenant_id})
        ).all()
        return {r[0]: r[1] for r in rows}
    except Exception as exc:  # pragma: no cover - needs a database
        logger.warning("Agent owners unavailable: %s", exc)
        await db.rollback()
        return {}


async def owned_agents(db: AsyncSession, tenant_id: str, username: str) -> set[str]:
    """Agents that belong to ``username``: explicit owners plus driver bindings."""
    agents = {cid for cid, owner in (await explicit_owners(db, tenant_id)).items() if owner == username}
    try:
        agents |= set(
            (
                await db.execute(
                    select(AuditLog.actor_id)
                    .where(
                        AuditLog.tenant_id == tenant_id,
                        AuditLog.driver_id == username,
                        AuditLog.actor_id != username,
                    )
                    .distinct()
                )
            )
            .scalars()
            .all()
        )
        agents |= set(
            (
                await db.execute(
                    select(MemoryNode.actor_id)
                    .where(
                        MemoryNode.tenant_id == tenant_id,
                        MemoryNode.driver_id == username,
                        MemoryNode.actor_id.is_not(None),
                        MemoryNode.actor_id != username,
                    )
                    .distinct()
                )
            )
            .scalars()
            .all()
        )
    except Exception as exc:  # pragma: no cover - needs a database
        logger.warning("Agent bindings unavailable: %s", exc)
        await db.rollback()
    agents.discard(None)  # type: ignore[arg-type]
    return {a for a in agents if a}


async def set_owner(db: AsyncSession, tenant_id: str, client_id: str, owner: str | None, by: str, how: str) -> None:
    await ensure_table(db)
    if owner:
        await db.execute(
            text(
                f"""
                INSERT INTO {OWNERS} (tenant_id, client_id, owner, assigned_by, how)
                VALUES (:t, :c, :o, :b, :h)
                ON CONFLICT (tenant_id, client_id) DO UPDATE
                  SET owner = EXCLUDED.owner, assigned_by = EXCLUDED.assigned_by, how = EXCLUDED.how,
                      assigned_at = now()
                """
            ),
            {"t": tenant_id, "c": client_id, "o": owner, "b": by, "h": how},
        )
    else:
        await db.execute(
            text(f"DELETE FROM {OWNERS} WHERE tenant_id = :t AND client_id = :c"), {"t": tenant_id, "c": client_id}
        )


async def verify_client_secret(settings: Settings, client_id: str, client_secret: str) -> bool:
    """True when the auth service accepts the credentials (client_credentials grant)."""
    if not settings.auth_service_url:
        return False
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.post(
                f"{settings.auth_service_url.rstrip('/')}/token",
                data={"grant_type": "client_credentials", "client_id": client_id, "client_secret": client_secret},
            )
        return resp.status_code == 200
    except Exception as exc:  # pragma: no cover - network dependent
        logger.warning("Auth service unreachable while verifying a client: %s", exc)
        return False

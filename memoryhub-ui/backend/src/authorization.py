"""Human dashboard authorization, separate from MCP token scopes.

The OpenShift OAuth sidecar authenticates the human and overwrites
X-Forwarded-User. The application is bound to loopback in the deployment;
the peer check below also rejects direct calls to the application port.
"""

from __future__ import annotations

import ipaddress
import logging
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from memoryhub_core.authorization.human import ADMIN_MODERATION_SCOPES, Principal
from memoryhub_core.authorization.human import Access as HumanAccess
from memoryhub_core.models.memory import MemoryNode
from memoryhub_core.queries.identities import load_human_grants
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import Settings, get_settings
from src.database import get_db

logger = logging.getLogger(__name__)

def get_principal(request: Request, settings: Annotated[Settings, Depends(get_settings)]) -> Principal:
    problem = settings.identity_problem()
    if problem:
        raise HTTPException(status_code=503, detail=problem)
    if settings.ui_auth_mode == "local":
        # Local development: one configured identity; request headers are never trusted.
        username = settings.ui_local_user.strip()
    else:
        username = _proxy_user(request)
    admins, allowed = settings.human_access()
    if username not in admins and username not in allowed:
        logger.warning("Dashboard access denied: %r is not in the human access lists", username)
        raise HTTPException(status_code=403, detail="Tenant access forbidden")
    return Principal(username=username, role="admin" if username in admins else "user", tenant_id=settings.ui_tenant_id)


def _proxy_user(request: Request) -> str:
    """The user the OpenShift OAuth proxy authenticated; only the loopback sidecar may say."""
    peer = request.client.host if request.client else ""
    try:
        local = ipaddress.ip_address(peer).is_loopback
    except ValueError:
        local = False
    if not local:
        raise HTTPException(status_code=401, detail="OAuth proxy required")
    users = request.headers.getlist("x-forwarded-user")
    if len(users) != 1:
        raise HTTPException(status_code=401, detail="Authenticated user required")
    username = users[0].strip()
    if not username or len(username) > 255 or any(c in username for c in "\r\n\x00"):
        raise HTTPException(status_code=401, detail="Authenticated user required")
    return username


class Access(HumanAccess):
    """HTTP denial mapping around the shared Core human policy."""

    def forbid_person_filter(self, *values) -> None:
        if not self.sees_individual_activity and any(values):
            raise HTTPException(status_code=403, detail="Per-person filters are not available to admins")

    def require_read(self, node: MemoryNode) -> None:
        if not self.can_read(node):
            raise HTTPException(status_code=404, detail="Memory not found")

    def require_delete(self, node: MemoryNode) -> None:
        if not self.can_delete(node):
            raise HTTPException(status_code=403, detail="Memory delete forbidden")


async def get_access(
    principal: Annotated[Principal, Depends(get_principal)],
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Access:
    if principal.role not in ("user", "admin"):
        raise HTTPException(status_code=403, detail="Unsupported dashboard role")
    scopes = {s.strip() for s in settings.ui_admin_moderation_scopes.split(",") if s.strip()}
    scopes &= ADMIN_MODERATION_SCOPES
    write_scopes = {s.strip() for s in settings.ui_admin_write_scopes.split(",") if s.strip()}
    access = Access(
        principal=principal,
        moderation_scopes=scopes,
        admin_write_scopes=write_scopes,
    )
    return await load_human_grants(db, access)


AccessDep = Annotated[Access, Depends(get_access)]

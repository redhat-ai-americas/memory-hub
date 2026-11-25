"""Read-only view of dashboard access assignments for Admins (#744).

Lists who has been granted the dashboard Roles. These are assignments, not
the full list of effective users: group members, cluster-wide grants and
wildcard roles such as cluster-admin are not expanded. Changing access is
done with memoryhub-ui/deploy/dashboard-access.sh (or `oc`), never here: the
dashboard service account may read bindings, not create them.
"""

from __future__ import annotations

import logging
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.authorization import Principal, get_principal
from src.config import Settings, get_settings
from src.kube import KubeClient, KubeUnauthenticated, KubeUnavailable

logger = logging.getLogger(__name__)
router = APIRouter()

ROLE_NAMES = {"memoryhub-dashboard-admin": "admin", "memoryhub-dashboard-user": "user"}
NOTE = ("Assignments, not effective users: group members and cluster-wide grants "
        "(for example cluster-admin) are not expanded.")


class AccessAssignment(BaseModel):
    role: Literal["admin", "user"]
    kind: str
    name: str
    binding: str | None = None
    granted_by: str | None = None
    granted_at: str | None = None


class AccessAssignments(BaseModel):
    source: Literal["openshift-rbac", "lists"]
    namespace: str | None
    assignments: list[AccessAssignment]
    note: str


def kube_client_for(settings: Settings) -> KubeClient:
    return KubeClient(settings.kube_api_url, settings.kube_ca_path, settings.kube_token_path)


def assignments_from_bindings(items: list[dict]) -> list[AccessAssignment]:
    found = []
    for item in items:
        ref = item.get("roleRef") or {}
        role = ROLE_NAMES.get(ref.get("name", "")) if ref.get("kind") == "Role" else None
        if role is None:
            continue
        meta = item.get("metadata") or {}
        annotations = meta.get("annotations") or {}
        for subject in item.get("subjects") or []:
            found.append(AccessAssignment(
                role=role, kind=subject.get("kind", ""), name=subject.get("name", ""),
                binding=meta.get("name"),
                granted_by=annotations.get("memoryhub.io/granted-by"),
                granted_at=annotations.get("memoryhub.io/granted-at"),
            ))
    return sorted(found, key=lambda a: (a.role != "admin", a.kind, a.name))


@router.get("/api/admin/access", response_model=AccessAssignments)
async def dashboard_access(
    principal: Annotated[Principal, Depends(get_principal)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AccessAssignments:
    if principal.role != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")
    if settings.ui_role_source == "lists":
        admins, users = settings.human_access()
        rows = [AccessAssignment(role="admin", kind="User", name=n) for n in sorted(admins)]
        rows += [AccessAssignment(role="user", kind="User", name=n) for n in sorted(users - admins)]
        return AccessAssignments(source="lists", namespace=None, assignments=rows, note=NOTE)
    namespace = settings.rbac_namespace()
    try:
        items = await kube_client_for(settings).role_bindings(namespace)
    except (KubeUnavailable, KubeUnauthenticated):
        raise HTTPException(status_code=503, detail="Access assignments cannot be read right now") from None
    return AccessAssignments(source="openshift-rbac", namespace=namespace,
                             assignments=assignments_from_bindings(items), note=NOTE)

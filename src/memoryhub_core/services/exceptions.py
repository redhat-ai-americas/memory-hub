"""Custom exceptions for the memory service layer."""

import uuid


class MemoryNotFoundError(Exception):
    """Raised when a memory node does not exist."""

    def __init__(self, memory_id: uuid.UUID) -> None:
        self.memory_id = memory_id
        super().__init__(f"Memory node {memory_id} not found")


class MemoryNotCurrentError(Exception):
    """Raised when attempting to update a non-current memory version."""

    def __init__(self, memory_id: uuid.UUID, current_id: uuid.UUID) -> None:
        self.memory_id = memory_id
        self.current_id = current_id
        super().__init__(f"Memory node {memory_id} is not the current version; current is {current_id}")


class MemoryAccessDeniedError(Exception):
    """Raised when access to a memory node is denied."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"Access denied: {reason}")


class ContradictionNotFoundError(Exception):
    """Raised when a contradiction report cannot be found."""

    def __init__(self, contradiction_id: uuid.UUID) -> None:
        self.contradiction_id = contradiction_id
        super().__init__(f"Contradiction report {contradiction_id} not found")


class MemoryAlreadyDeletedError(Exception):
    """Raised when attempting to delete an already-deleted memory."""

    def __init__(self, memory_id: uuid.UUID) -> None:
        self.memory_id = memory_id
        super().__init__(f"Memory node {memory_id} is already deleted")


class RelationshipNotFoundError(Exception):
    """Raised when a graph relationship cannot be found."""

    def __init__(self, relationship_id: uuid.UUID) -> None:
        self.relationship_id = relationship_id
        super().__init__(f"Relationship {relationship_id} not found")


class ProjectInviteOnlyError(Exception):
    """Raised when a user attempts to join an invite-only project."""

    def __init__(self, project_id: str) -> None:
        self.project_id = project_id
        super().__init__(
            f"Project '{project_id}' requires an invitation. "
            "Contact a project admin to be added."
        )


class CrossTenantRelationshipError(Exception):
    """Raised when a relationship would span two different tenants.

    Defense in depth: under normal operation the tool-layer authorize_read
    check already prevents a caller from loading memories from two different
    tenants in the same session, so this error should never reach users.
    It exists to catch bugs in higher layers (e.g., an internal service
    path that bypasses authorize_read) before they poison the graph with
    cross-tenant edges.
    """

    def __init__(
        self,
        source_id: uuid.UUID,
        source_tenant: str,
        target_id: uuid.UUID,
        target_tenant: str,
    ) -> None:
        self.source_id = source_id
        self.source_tenant = source_tenant
        self.target_id = target_id
        self.target_tenant = target_tenant
        super().__init__(
            f"Cross-tenant relationship rejected: source {source_id} "
            f"(tenant={source_tenant!r}) and target {target_id} "
            f"(tenant={target_tenant!r}) must share a tenant."
        )

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

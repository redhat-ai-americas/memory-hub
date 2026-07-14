"""MemoryHub SDK response models."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Memory(BaseModel):
    """A memory node returned by search, read, or write operations."""

    model_config = ConfigDict(extra="allow")

    id: str
    content: str = ""
    stub: str | None = None
    weight: float = 0.7
    scope: str = ""
    branch_type: str | None = None
    owner_id: str = ""
    actor_id: str | None = None
    driver_id: str | None = None
    is_current: bool = True
    version: int = 1
    parent_id: str | None = None
    previous_version_id: str | None = None
    storage_type: str = "inline"
    content_ref: str | None = None
    metadata: dict[str, Any] | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    expires_at: datetime | None = None
    has_children: bool = False
    has_rationale: bool = False
    branch_count: int = 0
    current_version_id: str | None = None
    relationships: list[dict[str, Any]] | None = None
    relevance_score: float | None = None
    result_type: str | None = None  # "full" or "stub"
    is_appendix: bool | None = None  # True when result is cache-stable appendix (#175)
    content_type: str | None = None  # "declarative" or "behavioral"
    content_truncated: bool = False
    full_available: bool = False


class CurationInfo(BaseModel):
    """Curation feedback returned when writing a memory."""

    model_config = ConfigDict(extra="allow")

    blocked: bool = False
    gated: bool = False
    similar_count: int = 0
    nearest_id: str | None = None
    nearest_score: float | None = None
    flags: list[str] = Field(default_factory=list)
    # Populated only when gated=True:
    reason: str | None = None
    existing_memory_id: str | None = None
    existing_memory_stub: str | None = None
    recommendation: str | None = None
    cache_impact: dict[str, Any] | None = None


class WriteResult(BaseModel):
    """Result of a write_memory operation."""

    model_config = ConfigDict(extra="allow")

    memory: Memory | None = None
    curation: CurationInfo


class DeleteResult(BaseModel):
    """Result of a delete_memory operation."""

    model_config = ConfigDict(extra="allow")

    deleted_id: str
    versions_deleted: int = 0
    branches_deleted: int = 0
    total_deleted: int = 0


class SearchResult(BaseModel):
    """Result of a search_memory operation.

    The ``pivot_*`` fields are populated only when the caller passed a
    ``focus`` argument to :meth:`MemoryHubClient.search`. They let the
    agent notice when the immediate query has drifted off the declared
    focus and decide whether to rebias (see #58, Pattern C pivot
    detection). When no focus was declared, these fields are ``None``.
    """

    model_config = ConfigDict(extra="allow")

    results: list[Memory]
    total_matching: int = 0
    has_more: bool = False
    pivot_suggested: bool | None = None
    pivot_reason: str | None = None
    focus_fallback_reason: str | None = None
    # Cache-optimized assembly fields (#175)
    compilation_hash: str | None = None
    compilation_epoch: int | None = None
    appendix_count: int | None = None


class VersionEntry(BaseModel):
    """A single version in a memory's history."""

    model_config = ConfigDict(extra="allow")

    id: str
    version: int
    content: str
    stub: str | None = None
    is_current: bool = False
    created_at: datetime | None = None


class HistoryResult(BaseModel):
    """Result of a get_memory_history operation."""

    model_config = ConfigDict(extra="allow")

    memory_id: str
    versions: list[VersionEntry]
    total_versions: int = 0
    has_more: bool = False
    offset: int = 0


class ContradictionResult(BaseModel):
    """Result of a report_contradiction operation."""

    model_config = ConfigDict(extra="allow")

    memory_id: str
    contradiction_count: int = 0
    threshold: int = 5
    revision_triggered: bool = False
    message: str = ""


class SimilarMemory(BaseModel):
    """A memory returned by get_similar_memories with similarity score."""

    model_config = ConfigDict(extra="allow")

    memory: Memory
    score: float


class RelationshipInfo(BaseModel):
    """A relationship between two memory nodes."""

    model_config = ConfigDict(extra="allow")

    id: str | None = None
    source_id: str
    target_id: str
    relationship_type: str
    metadata: dict[str, Any] | None = None
    created_at: datetime | None = None


class RelationshipsResult(BaseModel):
    """Result of a get_relationships operation."""

    model_config = ConfigDict(extra="allow")

    relationships: list[RelationshipInfo]
    count: int = 0
    provenance_chain: list[dict[str, Any]] | None = None


class CurationRule(BaseModel):
    """A curation rule configuration."""

    model_config = ConfigDict(extra="allow")

    name: str
    tier: str = "embedding"
    action: str = "flag"
    config: dict[str, Any] | None = None
    scope_filter: str | None = None
    enabled: bool = True
    priority: int = 10


class CurationRuleResult(BaseModel):
    """Result of a set_curation_rule operation."""

    model_config = ConfigDict(extra="allow")

    created: bool = False
    updated: bool = False
    rule: CurationRule | dict[str, Any]


class SessionInfo(BaseModel):
    """Result of register_session (used internally)."""

    model_config = ConfigDict(extra="allow")

    session_id: str | None = None
    user_id: str
    name: str
    scopes: list[str]
    message: str = ""


class EntityInfo(BaseModel):
    """A single entity node with relationship count."""

    model_config = ConfigDict(extra="allow")

    id: str
    content: str
    entity_type: str | None = None
    aliases: list[str] = Field(default_factory=list)
    mentions_count: int = 0
    created_at: datetime | None = None


class ListEntitiesResult(BaseModel):
    """Paginated list of entity nodes."""

    model_config = ConfigDict(extra="allow")

    entities: list[EntityInfo]
    total: int = 0
    limit: int = 50
    offset: int = 0
    has_more: bool = False


class MergeEntitiesResult(BaseModel):
    """Result of merging two entities."""

    model_config = ConfigDict(extra="allow")

    surviving_entity: dict[str, Any] = Field(default_factory=dict)
    reassigned_mentions: int = 0
    skipped_duplicates: int = 0
    source_deleted: str = ""
    message: str = ""


class RenameEntityResult(BaseModel):
    """Result of renaming an entity."""

    model_config = ConfigDict(extra="allow")

    entity: dict[str, Any] = Field(default_factory=dict)
    old_name: str = ""
    message: str = ""


class ConversationThread(BaseModel):
    """A conversation thread returned by thread operations."""

    model_config = ConfigDict(extra="allow")

    id: str
    title: str | None = None
    scope: str = ""
    scope_id: str | None = None
    owner_id: str = ""
    actor_id: str | None = None
    tenant_id: str = ""
    status: str = "active"
    participant_ids: list[str] = Field(default_factory=list)
    participant_access: dict[str, str] | None = None
    extraction_cursor: int = 0
    last_extracted_at: datetime | None = None
    expires_at: datetime | None = None
    legal_hold: bool = False
    retention_policy: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ConversationMessage(BaseModel):
    """A single message in a conversation thread."""

    model_config = ConfigDict(extra="allow")

    id: str
    thread_id: str
    sequence_number: int = 0
    role: str = ""
    content: str | None = None
    actor_id: str | None = None
    storage_type: str = "inline"
    tool_call_id: str | None = None
    tenant_id: str = ""
    metadata: dict[str, Any] | None = None
    created_at: datetime | None = None


class ThreadResult(BaseModel):
    """Result of a get_thread operation with optional messages."""

    model_config = ConfigDict(extra="allow")

    thread: ConversationThread
    messages: list[ConversationMessage] | None = None
    has_more: bool = False


class ThreadListResult(BaseModel):
    """Result of a list_threads operation."""

    model_config = ConfigDict(extra="allow")

    threads: list[ConversationThread] = Field(default_factory=list)
    total: int = 0


class ExtractionResult(BaseModel):
    """Result of a thread extraction operation."""

    model_config = ConfigDict(extra="allow")

    extracted_count: int = 0
    cursor: int = 0
    failures: int = 0

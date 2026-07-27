"""Dialect-portable SQLAlchemy models for MemoryHub.

Re-exports all ORM model classes from the local (SQLite-portable) versions.
Pydantic schemas are NOT re-exported -- those stay in memoryhub_core.
"""

from memoryhub_local.models.base import Base, TimestampMixin
from memoryhub_local.models.campaign import Campaign, CampaignMembership
from memoryhub_local.models.contradiction import ContradictionReport
from memoryhub_local.models.conversation import (
    ConversationExtraction,
    ConversationExtractionFailure,
    ConversationMessage,
    ConversationThread,
    PurgeLog,
)
from memoryhub_local.models.curation import CuratorRule
from memoryhub_local.models.memory import MemoryNode, MemoryRelationship
from memoryhub_local.models.project import Project, ProjectMembership
from memoryhub_local.models.reconciliation import ReconciliationDecision
from memoryhub_local.models.role import RoleAssignment
from memoryhub_local.models.utils import generate_stub

__all__ = [
    "Base",
    "Campaign",
    "CampaignMembership",
    "ContradictionReport",
    "ConversationExtraction",
    "ConversationExtractionFailure",
    "ConversationMessage",
    "ConversationThread",
    "CuratorRule",
    "MemoryNode",
    "MemoryRelationship",
    "Project",
    "ProjectMembership",
    "PurgeLog",
    "ReconciliationDecision",
    "RoleAssignment",
    "TimestampMixin",
    "generate_stub",
]

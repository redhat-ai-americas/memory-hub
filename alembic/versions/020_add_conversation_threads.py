"""Add conversation threads

Revision ID: 020_add_conversation_threads
Revises: 019_add_actor_driver_id
Create Date: 2026-06-11

"""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

from alembic import op

# revision identifiers, used by Alembic.
revision = "020_add_conversation_threads"
down_revision = "019_add_actor_driver_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # conversation_threads
    op.create_table(
        "conversation_threads",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("title", sa.Text, nullable=True),
        sa.Column("a2a_context_id", sa.Text, nullable=True),
        sa.Column("scope", sa.String(20), nullable=False),
        sa.Column("scope_id", sa.String(255), nullable=True),
        sa.Column("owner_id", sa.String(255), nullable=False),
        sa.Column("actor_id", sa.String(255), nullable=True),
        sa.Column("driver_id", sa.String(255), nullable=True),
        sa.Column("tenant_id", sa.String(255), nullable=False, server_default=sa.text("'default'")),
        sa.Column("participant_ids", ARRAY(sa.Text), nullable=False, server_default=sa.text("'{}'::text[]")),
        sa.Column("participant_access", JSONB, nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'active'")),
        sa.Column("archived_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("retention_policy", JSONB, nullable=True),
        sa.Column("legal_hold", sa.Boolean, nullable=False, server_default=sa.text("FALSE")),
        sa.Column("last_extracted_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("extraction_cursor", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("metadata", JSONB, nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "participant_access IS NULL OR jsonb_typeof(participant_access) = 'object'",
            name="ck_participant_access_object"
        ),
    )

    op.create_index("ix_conv_threads_owner_scope", "conversation_threads", ["owner_id", "scope"])
    op.create_index("ix_conv_threads_tenant_scope", "conversation_threads", ["tenant_id", "scope"])
    op.create_index(
        "ix_conv_threads_scope_id",
        "conversation_threads",
        ["scope_id"],
        postgresql_where=sa.text("scope_id IS NOT NULL")
    )
    op.create_index(
        "ix_conv_threads_a2a_context_id",
        "conversation_threads",
        ["a2a_context_id"],
        postgresql_where=sa.text("a2a_context_id IS NOT NULL")
    )
    op.create_index("ix_conv_threads_status", "conversation_threads", ["status"])
    op.create_index(
        "ix_conv_threads_deleted_at",
        "conversation_threads",
        ["deleted_at"],
        postgresql_where=sa.text("deleted_at IS NOT NULL")
    )
    op.create_index(
        "ix_conv_threads_expires_at",
        "conversation_threads",
        ["expires_at"],
        postgresql_where=sa.text("expires_at IS NOT NULL")
    )

    # conversation_messages
    op.create_table(
        "conversation_messages",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("thread_id", UUID(as_uuid=True), nullable=False),
        sa.Column("sequence_number", sa.Integer, nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("actor_id", sa.String(255), nullable=True),
        sa.Column("storage_type", sa.String(10), nullable=False, server_default=sa.text("'inline'")),
        sa.Column("content", sa.Text, nullable=True),
        sa.Column("content_ref", sa.String(1024), nullable=True),
        sa.Column("content_size", sa.Integer, nullable=True),
        sa.Column("tool_call_id", sa.String(255), nullable=True),
        sa.Column("handoff_from_agent_id", sa.String(255), nullable=True),
        sa.Column("handoff_authorized_by", sa.String(255), nullable=True),
        sa.Column("handoff_redacted", sa.Boolean, nullable=False, server_default=sa.text("FALSE")),
        sa.Column("tenant_id", sa.String(255), nullable=False, server_default=sa.text("'default'")),
        sa.Column("metadata", JSONB, nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["thread_id"], ["conversation_threads.id"], ondelete="CASCADE"),
    )

    op.create_index(
        "uq_conv_messages_thread_seq",
        "conversation_messages",
        ["thread_id", "sequence_number"],
        unique=True
    )
    op.create_index("ix_conv_messages_thread_id", "conversation_messages", ["thread_id"])
    op.create_index("ix_conv_messages_tenant_id", "conversation_messages", ["tenant_id"])
    op.create_index(
        "ix_conv_messages_actor_id",
        "conversation_messages",
        ["actor_id"],
        postgresql_where=sa.text("actor_id IS NOT NULL")
    )
    op.create_index(
        "ix_conv_messages_tool_call_id",
        "conversation_messages",
        ["tool_call_id"],
        postgresql_where=sa.text("tool_call_id IS NOT NULL")
    )

    # conversation_extractions
    op.create_table(
        "conversation_extractions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("memory_node_id", UUID(as_uuid=True), nullable=False),
        sa.Column("thread_id", UUID(as_uuid=True), nullable=False),
        sa.Column("source_messages", ARRAY(sa.Integer), nullable=False, server_default=sa.text("'{}'::integer[]")),
        sa.Column("extracted_by", sa.String(255), nullable=False),
        sa.Column("extraction_model", sa.String(255), nullable=True),
        sa.Column("extraction_prompt_hash", sa.String(64), nullable=True),
        sa.Column("tenant_id", sa.String(255), nullable=False, server_default=sa.text("'default'")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["memory_node_id"], ["memory_nodes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["thread_id"], ["conversation_threads.id"], ondelete="RESTRICT"),
    )

    op.create_index("ix_conv_extractions_memory_node", "conversation_extractions", ["memory_node_id"])
    op.create_index("ix_conv_extractions_thread_id", "conversation_extractions", ["thread_id"])
    op.create_index("ix_conv_extractions_tenant", "conversation_extractions", ["tenant_id"])

    # purge_log
    op.create_table(
        "purge_log",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("resource_type", sa.String(50), nullable=False),
        sa.Column("resource_id", UUID(as_uuid=True), nullable=False),
        sa.Column("purged_by", sa.String(255), nullable=False),
        sa.Column("purged_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("reason", sa.String(20), nullable=False),
        sa.Column("incident_ref", sa.String(255), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("purge_log")
    op.drop_table("conversation_extractions")
    op.drop_table("conversation_messages")
    op.drop_table("conversation_threads")

"""Add conversation extraction failures

Revision ID: 021_add_extraction_failures
Revises: 020_add_conversation_threads
Create Date: 2026-06-11

"""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

# revision identifiers, used by Alembic.
revision = "021_add_extraction_failures"
down_revision = "020_add_conversation_threads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversation_extraction_failures",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("thread_id", UUID(as_uuid=True), nullable=False),
        sa.Column("window_start", sa.Integer, nullable=False),
        sa.Column("window_end", sa.Integer, nullable=False),
        sa.Column("attempt_count", sa.Integer, nullable=False, server_default=sa.text("1")),
        sa.Column("last_error", sa.Text, nullable=False),
        sa.Column("last_attempt_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("resolved", sa.Boolean, nullable=False, server_default=sa.text("FALSE")),
        sa.Column("tenant_id", sa.String(255), nullable=False, server_default=sa.text("'default'")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["thread_id"], ["conversation_threads.id"], ondelete="CASCADE"),
    )

    op.create_index("ix_conv_extraction_failures_thread_id", "conversation_extraction_failures", ["thread_id"])
    op.create_index("ix_conv_extraction_failures_tenant", "conversation_extraction_failures", ["tenant_id"])


def downgrade() -> None:
    op.drop_table("conversation_extraction_failures")

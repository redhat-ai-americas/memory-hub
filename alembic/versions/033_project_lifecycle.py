"""Project lifecycle: archive, soft delete and policies (#671).

Adds archived_at/archived_by, deleted_at/deleted_by and a policies JSON
column ({ttl_days, max_memories, default_weight}) to projects. Existing
projects stay active with no policies.

Revision ID: 033_project_lifecycle
Revises: 032_persona_source_values
"""

import sqlalchemy as sa

from alembic import op

revision = "033_project_lifecycle"
down_revision = "032_persona_source_values"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("projects", sa.Column("archived_by", sa.String(255), nullable=True))
    op.add_column("projects", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("projects", sa.Column("deleted_by", sa.String(255), nullable=True))
    op.add_column(
        "projects",
        sa.Column("policies", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )


def downgrade() -> None:
    for column in ("policies", "deleted_by", "deleted_at", "archived_by", "archived_at"):
        op.drop_column("projects", column)

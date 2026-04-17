"""Add projects table for enrollment policy management.

Revision ID: 012_add_projects_table
Revises: 011_add_scope_isolation
Create Date: 2026-04-15
"""

import sqlalchemy as sa

from alembic import op

revision = "012_add_projects_table"
down_revision = "011_add_scope_isolation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("invite_only", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("tenant_id", sa.String(255), server_default=sa.text("'default'"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.PrimaryKeyConstraint("name"),
    )

    op.create_index("ix_projects_tenant_id", "projects", ["tenant_id"])

    # Backfill from existing memberships so FK constraint succeeds
    op.execute(
        sa.text(
            "INSERT INTO projects (name, created_by, tenant_id) "
            "SELECT DISTINCT project_id, 'migration-012', 'default' "
            "FROM project_memberships "
            "ON CONFLICT DO NOTHING"
        )
    )

    op.create_foreign_key(
        "fk_project_memberships_project",
        "project_memberships",
        "projects",
        ["project_id"],
        ["name"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_project_memberships_project", "project_memberships", type_="foreignkey")
    op.drop_index("ix_projects_tenant_id", table_name="projects")
    op.drop_table("projects")

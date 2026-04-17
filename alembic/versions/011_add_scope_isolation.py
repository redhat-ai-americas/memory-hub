"""Add scope_id column and membership tables for project/role isolation.

Revision ID: 011_add_scope_isolation
Revises: 010_add_domains
Create Date: 2026-04-10
"""

import sqlalchemy as sa

from alembic import op

revision = "011_add_scope_isolation"
down_revision = "010_add_domains"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add scope_id to memory_nodes for project-level isolation
    op.add_column(
        "memory_nodes",
        sa.Column("scope_id", sa.String(255), nullable=True),
    )
    op.create_index("ix_memory_nodes_scope_id", "memory_nodes", ["scope_id"])

    # Backfill existing project-scoped memories with the default project id
    op.execute(
        "UPDATE memory_nodes SET scope_id = 'memory-hub' WHERE scope = 'project' AND scope_id IS NULL"
    )

    op.create_table(
        "project_memberships",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v4()"), nullable=False),
        sa.Column("project_id", sa.String(255), nullable=False),
        sa.Column("user_id", sa.String(255), nullable=False),
        sa.Column("role", sa.String(50), server_default=sa.text("'member'"), nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("joined_by", sa.String(255), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "user_id", name="uq_project_memberships_member"),
    )

    op.create_index("ix_project_memberships_project", "project_memberships", ["project_id"])
    op.create_index("ix_project_memberships_user", "project_memberships", ["user_id"])

    op.create_table(
        "role_assignments",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v4()"), nullable=False),
        sa.Column("user_id", sa.String(255), nullable=False),
        sa.Column("role_name", sa.String(100), nullable=False),
        sa.Column("tenant_id", sa.String(255), server_default=sa.text("'default'"), nullable=False),
        sa.Column("assigned_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("assigned_by", sa.String(255), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "role_name", "tenant_id", name="uq_role_assignments_member"),
    )

    op.create_index("ix_role_assignments_user", "role_assignments", ["user_id"])
    op.create_index("ix_role_assignments_role", "role_assignments", ["role_name"])
    op.create_index("ix_role_assignments_tenant", "role_assignments", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("ix_role_assignments_tenant", table_name="role_assignments")
    op.drop_index("ix_role_assignments_role", table_name="role_assignments")
    op.drop_index("ix_role_assignments_user", table_name="role_assignments")
    op.drop_table("role_assignments")

    op.drop_index("ix_project_memberships_user", table_name="project_memberships")
    op.drop_index("ix_project_memberships_project", table_name="project_memberships")
    op.drop_table("project_memberships")

    op.drop_index("ix_memory_nodes_scope_id", table_name="memory_nodes")
    op.drop_column("memory_nodes", "scope_id")

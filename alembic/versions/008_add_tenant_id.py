"""Add tenant_id column to governed tables for multi-tenant isolation.

Revision ID: 008_add_tenant_id
Revises: 007_add_deleted_at
Create Date: 2026-04-08
"""

import sqlalchemy as sa
from alembic import op

revision = "008_add_tenant_id"
down_revision = "007_add_deleted_at"
branch_labels = None
depends_on = None


_TENANT_TABLES = (
    "memory_nodes",
    "memory_relationships",
    "contradiction_reports",
    "curator_rules",
)


def upgrade() -> None:
    # Add tenant_id column to each governed table with a server-side default
    # of 'default'. The default lets existing rows populate on add_column and
    # also protects future INSERTs that forget to set tenant_id explicitly
    # (belt-and-suspenders with the service-layer logic added in Phase 3).
    for table in _TENANT_TABLES:
        op.add_column(
            table,
            sa.Column(
                "tenant_id",
                sa.String(length=255),
                nullable=True,
                server_default="default",
            ),
        )

    # Backfill defensively in case any row slipped through with NULL (e.g.,
    # from a crashed mid-upgrade). On a clean upgrade the server_default above
    # already populates existing rows.
    for table in _TENANT_TABLES:
        op.execute(f"UPDATE {table} SET tenant_id = 'default' WHERE tenant_id IS NULL")

    # Lock the column down now that every row has a value. Keep the server
    # default in place — dropping it would regress the safety net.
    for table in _TENANT_TABLES:
        op.alter_column(
            table,
            "tenant_id",
            existing_type=sa.String(length=255),
            existing_server_default=sa.text("'default'::character varying"),
            nullable=False,
        )

    # Indexes matching the common tenant filter patterns.
    op.create_index(
        "ix_memory_nodes_tenant_scope",
        "memory_nodes",
        ["tenant_id", "scope"],
    )
    op.create_index(
        "ix_memory_relationships_tenant",
        "memory_relationships",
        ["tenant_id"],
    )
    op.create_index(
        "ix_contradiction_reports_tenant",
        "contradiction_reports",
        ["tenant_id"],
    )
    op.create_index(
        "ix_curator_rules_tenant",
        "curator_rules",
        ["tenant_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_curator_rules_tenant", table_name="curator_rules")
    op.drop_index("ix_contradiction_reports_tenant", table_name="contradiction_reports")
    op.drop_index("ix_memory_relationships_tenant", table_name="memory_relationships")
    op.drop_index("ix_memory_nodes_tenant_scope", table_name="memory_nodes")

    for table in reversed(_TENANT_TABLES):
        op.drop_column(table, "tenant_id")

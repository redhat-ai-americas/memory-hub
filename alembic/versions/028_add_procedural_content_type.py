"""Allow procedural content_type on memory_nodes.

Part of #552 (procedural graph memory). Recreates the CHECK constraint
added in 017 so the fourth enum value is accepted at the DB layer.

Revision ID: 028_add_procedural_content_type
Revises: 027_add_logical_id
Create Date: 2026-09-18
"""

from alembic import op

revision = "028_add_procedural_content_type"
down_revision = "027_add_logical_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_memory_nodes_content_type", "memory_nodes", type_="check")
    op.create_check_constraint(
        "ck_memory_nodes_content_type",
        "memory_nodes",
        "content_type IN ('experiential', 'knowledge', 'behavioral', 'procedural')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_memory_nodes_content_type", "memory_nodes", type_="check")
    op.create_check_constraint(
        "ck_memory_nodes_content_type",
        "memory_nodes",
        "content_type IN ('experiential', 'knowledge', 'behavioral')",
    )

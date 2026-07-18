"""Add source column to memory_nodes for provenance tracking.

Tracks what produced a memory: agent-written, dreaming extraction, or
import. Enables search filtering for ablation testing and operator audit.

Part of #349 (Layer 2 benchmark).

Revision ID: 026_add_source_column
Revises: 025_add_reconciliation_decisions
Create Date: 2026-07-17
"""

from alembic import op

revision = "026_add_source_column"
down_revision = "025_add_reconciliation_decisions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE memory_nodes ADD COLUMN source VARCHAR(20) NOT NULL DEFAULT 'agent'"
    )
    op.execute(
        """ALTER TABLE memory_nodes ADD CONSTRAINT ck_memory_nodes_source
           CHECK (source IN ('agent', 'dreaming', 'import'))"""
    )
    op.execute("CREATE INDEX ix_memory_nodes_source ON memory_nodes(source)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_memory_nodes_source")
    op.execute("ALTER TABLE memory_nodes DROP CONSTRAINT IF EXISTS ck_memory_nodes_source")
    op.execute("ALTER TABLE memory_nodes DROP COLUMN IF EXISTS source")

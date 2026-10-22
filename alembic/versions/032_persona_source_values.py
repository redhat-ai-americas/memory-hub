"""Extend source check constraint to allow persona_compiler and user values.

Persona compilation writes synopsis nodes with source='persona_compiler'.
User-declared pins are written with source='user'. Neither was allowed by
the original constraint (agent, dreaming, import).

Revision ID: 032_persona_source_values
Revises: 031_add_upstream_trust_level
Part of WRIG-1483 (user persona feature).
"""

from alembic import op

revision = "032_persona_source_values"
down_revision = "031_add_upstream_trust_level"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE memory_nodes DROP CONSTRAINT IF EXISTS ck_memory_nodes_source")
    op.execute(
        """ALTER TABLE memory_nodes ADD CONSTRAINT ck_memory_nodes_source
           CHECK (source IN ('agent', 'dreaming', 'import', 'persona_compiler', 'user'))"""
    )


def downgrade() -> None:
    op.execute("ALTER TABLE memory_nodes DROP CONSTRAINT IF EXISTS ck_memory_nodes_source")
    op.execute(
        """ALTER TABLE memory_nodes ADD CONSTRAINT ck_memory_nodes_source
           CHECK (source IN ('agent', 'dreaming', 'import'))"""
    )

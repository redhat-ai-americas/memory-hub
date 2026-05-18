"""Add entity extraction indexes for Phase 2 of #170.

Creates indexes to support entity-scoped memory nodes and MENTIONS
relationships between memories and extracted entities.

Revision ID: 015_add_entity_extraction
Revises: 014_add_contradiction_resolution
Create Date: 2026-05-18
"""

from alembic import op

revision = "015_add_entity_extraction"
down_revision = "014_add_contradiction_resolution"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # GIN index for full-text search on entity node content.
    # Only entity-scoped nodes participate; the partial predicate
    # keeps the index small.
    op.execute(
        """
        CREATE INDEX ix_entity_nodes_content
        ON memory_nodes USING gin(to_tsvector('english', content))
        WHERE scope = 'entity'
        """
    )

    # Partial index for active MENTIONS relationships.
    # Accelerates the entity-aware search pre-filter join.
    op.execute(
        """
        CREATE INDEX ix_memory_relationships_mentions
        ON memory_relationships (source_id, target_id)
        WHERE relationship_type = 'mentions' AND valid_until IS NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_memory_relationships_mentions")
    op.execute("DROP INDEX IF EXISTS ix_entity_nodes_content")

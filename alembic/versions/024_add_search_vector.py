"""Add full-text search vector to memory_nodes.

Adds a generated tsvector column for keyword-based recall alongside
pgvector semantic search. The stub is weighted 'A' (higher) and content
weighted 'B' so exact matches in summaries rank above body hits.
A GIN index enables fast ts_rank queries.

Part of #305 (hybrid search).

Revision ID: 024_add_search_vector
Revises: 023_add_memory_status
Create Date: 2026-07-10
"""

from alembic import op

revision = "024_add_search_vector"
down_revision = "023_add_memory_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE memory_nodes
        ADD COLUMN search_vector tsvector
        GENERATED ALWAYS AS (
            setweight(to_tsvector('english', coalesce(stub, '')), 'A') ||
            setweight(to_tsvector('english', coalesce(content, '')), 'B')
        ) STORED
        """
    )
    op.execute(
        """
        CREATE INDEX ix_memory_nodes_search_vector
        ON memory_nodes USING GIN (search_vector)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_memory_nodes_search_vector")
    op.execute("ALTER TABLE memory_nodes DROP COLUMN IF EXISTS search_vector")

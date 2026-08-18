"""Add audit_log table for persistent audit events.

Audit events capture every memory operation with actor_id (authenticated
principal) and driver_id (upstream human/system on whose behalf the
operation was taken). Supports compliance recordkeeping and the "who did
what on whose behalf" query pattern.

RLS policies enforce append-only semantics: audit events can be inserted
but never updated or deleted (except by superuser for emergency recovery).

Part of #70 (audit persistence).

Revision ID: 028_add_audit_log
Revises: 027_add_logical_id
Create Date: 2026-08-18
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "028_add_audit_log"
down_revision = "027_add_logical_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("actor_id", sa.String(255), nullable=False),
        sa.Column("driver_id", sa.String(255), nullable=False),
        sa.Column("scope", sa.String(64), nullable=False),
        sa.Column("owner_id", sa.String(255), nullable=False),
        sa.Column("memory_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("tenant_id", sa.String(255), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "decision IN ('allowed', 'denied')", name="ck_audit_decision"
        ),
    )

    # Indexes for common query patterns
    op.create_index(
        "ix_audit_log_actor_time",
        "audit_log",
        ["actor_id", sa.text("timestamp DESC")],
    )
    op.create_index(
        "ix_audit_log_event_type_time",
        "audit_log",
        ["event_type", sa.text("timestamp DESC")],
    )
    op.create_index(
        "ix_audit_log_decision_time",
        "audit_log",
        ["decision", sa.text("timestamp DESC")],
    )
    op.create_index(
        "ix_audit_log_tenant_time",
        "audit_log",
        ["tenant_id", sa.text("timestamp DESC")],
    )
    op.create_index("ix_audit_log_memory_id", "audit_log", ["memory_id"])

    # Enable RLS to enforce append-only semantics
    # Note: RLS requires PostgreSQL 9.5+; OpenShift PostgreSQL meets this
    op.execute("ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY")

    # Revoke UPDATE and DELETE from PUBLIC to enforce append-only at DB level
    # INSERT is allowed for the application role (memoryhub user)
    op.execute("REVOKE UPDATE, DELETE ON audit_log FROM PUBLIC")

    # Policy: allow SELECT for application role (reads for audit queries)
    op.execute("""
        CREATE POLICY audit_select_all ON audit_log
        FOR SELECT
        USING (true)
    """)

    # Policy: allow INSERT for application role (audit event writes)
    # No UPDATE or DELETE policies — those operations are blocked by REVOKE
    op.execute("""
        CREATE POLICY audit_insert_only ON audit_log
        FOR INSERT
        WITH CHECK (true)
    """)


def downgrade() -> None:
    # Drop policies before disabling RLS
    op.execute("DROP POLICY IF EXISTS audit_insert_only ON audit_log")
    op.execute("DROP POLICY IF EXISTS audit_select_all ON audit_log")
    op.execute("ALTER TABLE audit_log DISABLE ROW LEVEL SECURITY")

    # Restore UPDATE/DELETE permissions (for clean downgrade)
    op.execute("GRANT UPDATE, DELETE ON audit_log TO PUBLIC")

    # Drop indexes
    op.drop_index("ix_audit_log_memory_id", table_name="audit_log")
    op.drop_index("ix_audit_log_tenant_time", table_name="audit_log")
    op.drop_index("ix_audit_log_decision_time", table_name="audit_log")
    op.drop_index("ix_audit_log_event_type_time", table_name="audit_log")
    op.drop_index("ix_audit_log_actor_time", table_name="audit_log")

    # Drop table
    op.drop_table("audit_log")

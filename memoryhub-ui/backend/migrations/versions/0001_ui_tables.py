"""MemoryHub UI tables.

Revision ID: 0001_ui_tables
Revises:
Create Date: 2026-10-22

Baseline for every table the dashboard owns (all prefixed ``memoryhub_ui_``).
They used to be created on first use with CREATE TABLE IF NOT EXISTS; this
revision keeps IF NOT EXISTS so databases that already have them upgrade
cleanly, and from here on schema changes are new revisions.

The UI keeps its own version table (``alembic_version_memoryhub_ui``) so it
never collides with memoryhub_core's migrations in the same database.
"""

from alembic import op

revision = "0001_ui_tables"
down_revision = None
branch_labels = None
depends_on = None

TABLES = [
    "memoryhub_ui_settings",
    "memoryhub_ui_accounts",
    "memoryhub_ui_invites",
    "memoryhub_ui_agent_owners",
    "memoryhub_ui_teams",
    "memoryhub_ui_team_members",
    "memoryhub_ui_team_projects",
    "memoryhub_ui_user_prefs",
    "memoryhub_ui_dreams",
    "memoryhub_ui_dream_settings",
    "memoryhub_ui_notifications_seen",
    "memoryhub_ui_knowledge",
    "memoryhub_ui_jobs",
    "memoryhub_ui_search_runs",
    "memoryhub_ui_saved_queries",
    "memoryhub_ui_eval_runs",
    "memoryhub_ui_context_packs",
    "memoryhub_ui_documents",
    "memoryhub_ui_document_links",
]

STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS memoryhub_ui_settings (
        tenant_id VARCHAR(255) PRIMARY KEY,
        settings JSONB NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_by VARCHAR(255)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS memoryhub_ui_accounts (
        id UUID PRIMARY KEY,
        tenant_id VARCHAR(255) NOT NULL,
        username VARCHAR(64) NOT NULL,
        email VARCHAR(320) NOT NULL,
        display_name VARCHAR(255) NOT NULL,
        password_hash TEXT NOT NULL,
        role VARCHAR(16) NOT NULL DEFAULT 'user',
        status VARCHAR(16) NOT NULL DEFAULT 'active',
        job_title VARCHAR(255),
        requested_projects JSONB,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        last_login_at TIMESTAMPTZ,
        approved_by VARCHAR(255),
        invited_by VARCHAR(255),
        UNIQUE (tenant_id, username),
        UNIQUE (tenant_id, email)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS memoryhub_ui_invites (
        code VARCHAR(64) PRIMARY KEY,
        tenant_id VARCHAR(255) NOT NULL,
        role VARCHAR(16) NOT NULL DEFAULT 'user',
        email VARCHAR(320),
        note VARCHAR(255),
        created_by VARCHAR(255) NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        expires_at TIMESTAMPTZ NOT NULL,
        used_by VARCHAR(255),
        used_at TIMESTAMPTZ
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS memoryhub_ui_agent_owners (
        tenant_id VARCHAR(255) NOT NULL,
        client_id VARCHAR(255) NOT NULL,
        owner VARCHAR(255) NOT NULL,
        assigned_by VARCHAR(255) NOT NULL,
        how VARCHAR(32) NOT NULL,
        assigned_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY (tenant_id, client_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS memoryhub_ui_teams (
        id UUID PRIMARY KEY,
        tenant_id VARCHAR(255) NOT NULL,
        name VARCHAR(120) NOT NULL,
        description TEXT,
        created_by VARCHAR(255) NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        UNIQUE (tenant_id, name)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS memoryhub_ui_team_members (
        team_id UUID NOT NULL REFERENCES memoryhub_ui_teams(id) ON DELETE CASCADE,
        user_id VARCHAR(255) NOT NULL,
        role VARCHAR(16) NOT NULL DEFAULT 'member',
        added_by VARCHAR(255) NOT NULL,
        added_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY (team_id, user_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS memoryhub_ui_team_projects (
        team_id UUID NOT NULL REFERENCES memoryhub_ui_teams(id) ON DELETE CASCADE,
        project_id VARCHAR(255) NOT NULL,
        added_by VARCHAR(255) NOT NULL,
        added_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY (team_id, project_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS memoryhub_ui_user_prefs (
        tenant_id VARCHAR(255) NOT NULL,
        username VARCHAR(255) NOT NULL,
        prefs JSONB NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY (tenant_id, username)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS memoryhub_ui_dreams (
        id UUID PRIMARY KEY,
        tenant_id VARCHAR(255) NOT NULL,
        owner VARCHAR(255) NOT NULL,
        started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        duration_ms INTEGER NOT NULL DEFAULT 0,
        trigger VARCHAR(16) NOT NULL DEFAULT 'manual',
        report JSONB NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS memoryhub_ui_dream_settings (
        tenant_id VARCHAR(255) NOT NULL,
        owner VARCHAR(255) NOT NULL,
        settings JSONB NOT NULL,
        PRIMARY KEY (tenant_id, owner)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS memoryhub_ui_notifications_seen (
        tenant_id VARCHAR(255) NOT NULL,
        username VARCHAR(255) NOT NULL,
        seen_at TIMESTAMPTZ NOT NULL,
        PRIMARY KEY (tenant_id, username)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS memoryhub_ui_knowledge (
        tenant_id VARCHAR(255) NOT NULL,
        owner VARCHAR(255) NOT NULL,
        subject VARCHAR(512) NOT NULL,
        generated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        source_hash VARCHAR(64) NOT NULL,
        page JSONB NOT NULL,
        PRIMARY KEY (tenant_id, owner, subject)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS memoryhub_ui_jobs (
        id UUID PRIMARY KEY,
        tenant_id VARCHAR(255) NOT NULL,
        owner VARCHAR(255) NOT NULL,
        kind VARCHAR(64) NOT NULL,
        status VARCHAR(16) NOT NULL,
        trigger VARCHAR(16) NOT NULL DEFAULT 'manual',
        started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        finished_at TIMESTAMPTZ,
        duration_ms INTEGER,
        attempts INTEGER NOT NULL DEFAULT 1,
        correlation_id UUID NOT NULL,
        retry_of UUID,
        detail JSONB NOT NULL DEFAULT '{}'::jsonb,
        error TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS memoryhub_ui_search_runs (
        id UUID PRIMARY KEY,
        tenant_id VARCHAR(255) NOT NULL,
        viewer VARCHAR(255) NOT NULL,
        at TIMESTAMPTZ NOT NULL DEFAULT now(),
        source VARCHAR(16) NOT NULL,
        query_hash VARCHAR(16) NOT NULL,
        retrieval VARCHAR(8) NOT NULL,
        rerank VARCHAR(16) NOT NULL,
        total_ms REAL NOT NULL,
        counts JSONB NOT NULL,
        stage_ms JSONB NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS memoryhub_ui_saved_queries (
        id UUID PRIMARY KEY,
        tenant_id VARCHAR(255) NOT NULL,
        owner VARCHAR(255) NOT NULL,
        name VARCHAR(255) NOT NULL,
        request JSONB NOT NULL,
        expected JSONB NOT NULL DEFAULT '[]'::jsonb,
        visibility VARCHAR(16) NOT NULL DEFAULT 'private',
        project VARCHAR(255),
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        last_result JSONB
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS memoryhub_ui_eval_runs (
        id UUID PRIMARY KEY,
        tenant_id VARCHAR(255) NOT NULL,
        owner VARCHAR(255) NOT NULL,
        started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        duration_ms INTEGER NOT NULL,
        trigger VARCHAR(16) NOT NULL,
        summary JSONB NOT NULL,
        results JSONB NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS memoryhub_ui_context_packs (
        id UUID PRIMARY KEY,
        tenant_id VARCHAR(255) NOT NULL,
        owner VARCHAR(255) NOT NULL,
        name VARCHAR(255) NOT NULL,
        description TEXT,
        pinned JSONB NOT NULL DEFAULT '[]'::jsonb,
        queries JSONB NOT NULL DEFAULT '[]'::jsonb,
        token_budget INTEGER NOT NULL DEFAULT 2000,
        visibility VARCHAR(16) NOT NULL DEFAULT 'private',
        project VARCHAR(255),
        read_only BOOLEAN NOT NULL DEFAULT true,
        agents JSONB NOT NULL DEFAULT '[]'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        last_render JSONB
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS memoryhub_ui_documents (
        id UUID PRIMARY KEY,
        tenant_id VARCHAR(255) NOT NULL,
        owner VARCHAR(255) NOT NULL,
        title VARCHAR(512) NOT NULL,
        mime VARCHAR(128) NOT NULL DEFAULT 'text/plain',
        body TEXT NOT NULL,
        version INTEGER NOT NULL DEFAULT 1,
        project VARCHAR(255),
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS memoryhub_ui_document_links (
        memory_id UUID PRIMARY KEY,
        tenant_id VARCHAR(255) NOT NULL,
        document_id UUID NOT NULL,
        start_at INTEGER NOT NULL,
        end_at INTEGER NOT NULL,
        snippet TEXT NOT NULL,
        status VARCHAR(16) NOT NULL DEFAULT 'ok',
        doc_version INTEGER NOT NULL DEFAULT 1,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_memoryhub_ui_jobs_tenant_started ON memoryhub_ui_jobs (tenant_id, started_at DESC)",
]


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    for table in reversed(TABLES):
        op.execute(f"DROP TABLE IF EXISTS {table}")

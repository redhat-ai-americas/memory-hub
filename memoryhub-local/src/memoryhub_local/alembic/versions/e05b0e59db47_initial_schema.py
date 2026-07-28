"""Initial schema

Revision ID: e05b0e59db47
Revises:
Create Date: 2026-07-28 06:21:39.906881

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import memoryhub_local.models.dialect  # noqa: F401

# revision identifiers, used by Alembic.
revision: str = 'e05b0e59db47'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = inspector.get_table_names()

    if "memory_nodes" in existing_tables:
        return

    op.create_table('campaigns',
    sa.Column('id', memoryhub_local.models.dialect.PortableUUID(length=36), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('status', sa.String(length=20), server_default='active', nullable=False),
    sa.Column('default_ttl', memoryhub_local.models.dialect.IntervalSeconds(), nullable=True),
    sa.Column('tenant_id', sa.String(length=255), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'name', name='uq_campaigns_tenant_name')
    )
    with op.batch_alter_table('campaigns', schema=None) as batch_op:
        batch_op.create_index('ix_campaigns_tenant', ['tenant_id'], unique=False)

    op.create_table('conversation_threads',
    sa.Column('id', memoryhub_local.models.dialect.PortableUUID(length=36), nullable=False),
    sa.Column('title', sa.Text(), nullable=True),
    sa.Column('a2a_context_id', sa.Text(), nullable=True),
    sa.Column('scope', sa.String(length=20), nullable=False),
    sa.Column('scope_id', sa.String(length=255), nullable=True),
    sa.Column('owner_id', sa.String(length=255), nullable=False),
    sa.Column('actor_id', sa.String(length=255), nullable=True),
    sa.Column('driver_id', sa.String(length=255), nullable=True),
    sa.Column('tenant_id', sa.String(length=255), nullable=False),
    sa.Column('participant_ids', memoryhub_local.models.dialect.JsonEncodedList(), nullable=False),
    sa.Column('participant_access', sa.JSON(), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('retention_policy', sa.JSON(), nullable=True),
    sa.Column('legal_hold', sa.Boolean(), nullable=False),
    sa.Column('last_extracted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('extraction_cursor', sa.Integer(), nullable=False),
    sa.Column('metadata', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('conversation_threads', schema=None) as batch_op:
        batch_op.create_index('ix_conv_threads_a2a_context_id', ['a2a_context_id'], unique=False)
        batch_op.create_index('ix_conv_threads_deleted_at', ['deleted_at'], unique=False)
        batch_op.create_index('ix_conv_threads_expires_at', ['expires_at'], unique=False)
        batch_op.create_index('ix_conv_threads_owner_scope', ['owner_id', 'scope'], unique=False)
        batch_op.create_index('ix_conv_threads_scope_id', ['scope_id'], unique=False)
        batch_op.create_index('ix_conv_threads_status', ['status'], unique=False)
        batch_op.create_index('ix_conv_threads_tenant_scope', ['tenant_id', 'scope'], unique=False)

    op.create_table('curator_rules',
    sa.Column('id', memoryhub_local.models.dialect.PortableUUID(length=36), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('trigger', sa.String(length=30), nullable=False),
    sa.Column('tier', sa.String(length=20), nullable=False),
    sa.Column('config', sa.JSON(), nullable=False),
    sa.Column('action', sa.String(length=30), nullable=False),
    sa.Column('scope_filter', sa.String(length=20), nullable=True),
    sa.Column('layer', sa.String(length=20), nullable=False),
    sa.Column('owner_id', sa.String(length=255), nullable=True),
    sa.Column('tenant_id', sa.String(length=255), nullable=False),
    sa.Column('override', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('enabled', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('priority', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('layer', 'owner_id', 'name', name='uq_curator_rules_layer_owner_name')
    )
    with op.batch_alter_table('curator_rules', schema=None) as batch_op:
        batch_op.create_index('ix_curator_rules_enabled', ['enabled'], unique=False)
        batch_op.create_index('ix_curator_rules_layer_owner', ['layer', 'owner_id'], unique=False)
        batch_op.create_index('ix_curator_rules_tenant', ['tenant_id'], unique=False)
        batch_op.create_index('ix_curator_rules_trigger', ['trigger'], unique=False)

    op.create_table('memory_nodes',
    sa.Column('id', memoryhub_local.models.dialect.PortableUUID(length=36), nullable=False),
    sa.Column('parent_id', memoryhub_local.models.dialect.PortableUUID(length=36), nullable=True),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('stub', sa.Text(), nullable=False),
    sa.Column('storage_type', sa.String(length=10), nullable=False),
    sa.Column('content_ref', sa.String(length=1024), nullable=True),
    sa.Column('weight', sa.Float(), nullable=False),
    sa.Column('scope', sa.String(length=20), nullable=False),
    sa.Column('branch_type', sa.String(length=50), nullable=True),
    sa.Column('owner_id', sa.String(length=255), nullable=False),
    sa.Column('actor_id', sa.String(length=255), nullable=True),
    sa.Column('driver_id', sa.String(length=255), nullable=True),
    sa.Column('tenant_id', sa.String(length=255), nullable=False),
    sa.Column('scope_id', sa.String(length=255), nullable=True),
    sa.Column('domains', memoryhub_local.models.dialect.JsonEncodedList(), nullable=True),
    sa.Column('content_type', sa.String(length=20), nullable=False),
    sa.Column('status', sa.String(length=20), server_default='active', nullable=False),
    sa.Column('source', sa.String(length=20), server_default='agent', nullable=False),
    sa.Column('content_hash', sa.String(length=64), nullable=True),
    sa.Column('is_current', sa.Boolean(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('previous_version_id', memoryhub_local.models.dialect.PortableUUID(length=36), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('relevant_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('embedding', memoryhub_local.models.dialect.JsonEncodedVector(), nullable=True),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('metadata', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['parent_id'], ['memory_nodes.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['previous_version_id'], ['memory_nodes.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('memory_nodes', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_memory_nodes_actor_id'), ['actor_id'], unique=False)
        batch_op.create_index('ix_memory_nodes_deleted_at', ['deleted_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_memory_nodes_driver_id'), ['driver_id'], unique=False)
        batch_op.create_index('ix_memory_nodes_expires_at', ['expires_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_memory_nodes_is_current'), ['is_current'], unique=False)
        batch_op.create_index(batch_op.f('ix_memory_nodes_owner_id'), ['owner_id'], unique=False)
        batch_op.create_index('ix_memory_nodes_owner_scope_current', ['owner_id', 'scope', 'is_current'], unique=False)
        batch_op.create_index(batch_op.f('ix_memory_nodes_parent_id'), ['parent_id'], unique=False)
        batch_op.create_index('ix_memory_nodes_relevant_until', ['relevant_until'], unique=False)
        batch_op.create_index(batch_op.f('ix_memory_nodes_scope'), ['scope'], unique=False)
        batch_op.create_index('ix_memory_nodes_scope_id', ['scope_id'], unique=False)
        batch_op.create_index('ix_memory_nodes_source', ['source'], unique=False)
        batch_op.create_index('ix_memory_nodes_status', ['status'], unique=False)
        batch_op.create_index('ix_memory_nodes_tenant_scope', ['tenant_id', 'scope'], unique=False)

    op.create_table('projects',
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('invite_only', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('tenant_id', sa.String(length=255), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('created_by', sa.String(length=255), nullable=False),
    sa.PrimaryKeyConstraint('name')
    )
    with op.batch_alter_table('projects', schema=None) as batch_op:
        batch_op.create_index('ix_projects_tenant_id', ['tenant_id'], unique=False)

    op.create_table('purge_log',
    sa.Column('id', memoryhub_local.models.dialect.PortableUUID(length=36), nullable=False),
    sa.Column('resource_type', sa.String(length=50), nullable=False),
    sa.Column('resource_id', memoryhub_local.models.dialect.PortableUUID(length=36), nullable=False),
    sa.Column('purged_by', sa.String(length=255), nullable=False),
    sa.Column('purged_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('reason', sa.String(length=20), nullable=False),
    sa.Column('incident_ref', sa.String(length=255), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('role_assignments',
    sa.Column('id', memoryhub_local.models.dialect.PortableUUID(length=36), nullable=False),
    sa.Column('user_id', sa.String(length=255), nullable=False),
    sa.Column('role_name', sa.String(length=100), nullable=False),
    sa.Column('tenant_id', sa.String(length=255), nullable=False),
    sa.Column('assigned_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('assigned_by', sa.String(length=255), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'role_name', 'tenant_id', name='uq_role_assignments_member')
    )
    with op.batch_alter_table('role_assignments', schema=None) as batch_op:
        batch_op.create_index('ix_role_assignments_role', ['role_name'], unique=False)
        batch_op.create_index('ix_role_assignments_tenant', ['tenant_id'], unique=False)
        batch_op.create_index('ix_role_assignments_user', ['user_id'], unique=False)

    op.create_table('campaign_memberships',
    sa.Column('id', memoryhub_local.models.dialect.PortableUUID(length=36), nullable=False),
    sa.Column('campaign_id', memoryhub_local.models.dialect.PortableUUID(length=36), nullable=False),
    sa.Column('project_id', sa.String(length=255), nullable=False),
    sa.Column('enrolled_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('enrolled_by', sa.String(length=255), nullable=False),
    sa.ForeignKeyConstraint(['campaign_id'], ['campaigns.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('campaign_id', 'project_id', name='uq_campaign_memberships_enrollment')
    )
    with op.batch_alter_table('campaign_memberships', schema=None) as batch_op:
        batch_op.create_index('ix_campaign_memberships_campaign', ['campaign_id'], unique=False)
        batch_op.create_index('ix_campaign_memberships_project', ['project_id'], unique=False)

    op.create_table('contradiction_reports',
    sa.Column('id', memoryhub_local.models.dialect.PortableUUID(length=36), nullable=False),
    sa.Column('memory_id', memoryhub_local.models.dialect.PortableUUID(length=36), nullable=False),
    sa.Column('observed_behavior', sa.Text(), nullable=False),
    sa.Column('confidence', sa.Float(), nullable=False),
    sa.Column('reporter', sa.String(length=255), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('resolved', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('resolution_action', sa.String(length=50), nullable=True),
    sa.Column('resolved_by', sa.String(length=255), nullable=True),
    sa.Column('tenant_id', sa.String(length=255), nullable=False),
    sa.ForeignKeyConstraint(['memory_id'], ['memory_nodes.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('contradiction_reports', schema=None) as batch_op:
        batch_op.create_index('ix_contradiction_reports_memory_resolved', ['memory_id', 'resolved'], unique=False)
        batch_op.create_index('ix_contradiction_reports_resolved_created', ['resolved', 'created_at'], unique=False)
        batch_op.create_index('ix_contradiction_reports_tenant', ['tenant_id'], unique=False)

    op.create_table('conversation_extraction_failures',
    sa.Column('id', memoryhub_local.models.dialect.PortableUUID(length=36), nullable=False),
    sa.Column('thread_id', memoryhub_local.models.dialect.PortableUUID(length=36), nullable=False),
    sa.Column('window_start', sa.Integer(), nullable=False),
    sa.Column('window_end', sa.Integer(), nullable=False),
    sa.Column('attempt_count', sa.Integer(), nullable=False),
    sa.Column('last_error', sa.Text(), nullable=False),
    sa.Column('last_attempt_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('resolved', sa.Boolean(), nullable=False),
    sa.Column('tenant_id', sa.String(length=255), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['thread_id'], ['conversation_threads.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('conversation_extraction_failures', schema=None) as batch_op:
        batch_op.create_index('ix_conv_extraction_failures_tenant', ['tenant_id'], unique=False)
        batch_op.create_index('ix_conv_extraction_failures_thread_id', ['thread_id'], unique=False)

    op.create_table('conversation_extractions',
    sa.Column('id', memoryhub_local.models.dialect.PortableUUID(length=36), nullable=False),
    sa.Column('memory_node_id', memoryhub_local.models.dialect.PortableUUID(length=36), nullable=False),
    sa.Column('thread_id', memoryhub_local.models.dialect.PortableUUID(length=36), nullable=False),
    sa.Column('source_messages', memoryhub_local.models.dialect.JsonEncodedList(), nullable=False),
    sa.Column('extracted_by', sa.String(length=255), nullable=False),
    sa.Column('extraction_model', sa.String(length=255), nullable=True),
    sa.Column('extraction_prompt_hash', sa.String(length=64), nullable=True),
    sa.Column('tenant_id', sa.String(length=255), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['memory_node_id'], ['memory_nodes.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['thread_id'], ['conversation_threads.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('conversation_extractions', schema=None) as batch_op:
        batch_op.create_index('ix_conv_extractions_memory_node', ['memory_node_id'], unique=False)
        batch_op.create_index('ix_conv_extractions_tenant', ['tenant_id'], unique=False)
        batch_op.create_index('ix_conv_extractions_thread_id', ['thread_id'], unique=False)

    op.create_table('conversation_messages',
    sa.Column('id', memoryhub_local.models.dialect.PortableUUID(length=36), nullable=False),
    sa.Column('thread_id', memoryhub_local.models.dialect.PortableUUID(length=36), nullable=False),
    sa.Column('sequence_number', sa.Integer(), nullable=False),
    sa.Column('role', sa.String(length=20), nullable=False),
    sa.Column('actor_id', sa.String(length=255), nullable=True),
    sa.Column('storage_type', sa.String(length=10), nullable=False),
    sa.Column('content', sa.Text(), nullable=True),
    sa.Column('content_ref', sa.String(length=1024), nullable=True),
    sa.Column('content_size', sa.Integer(), nullable=True),
    sa.Column('tool_call_id', sa.String(length=255), nullable=True),
    sa.Column('handoff_from_agent_id', sa.String(length=255), nullable=True),
    sa.Column('handoff_authorized_by', sa.String(length=255), nullable=True),
    sa.Column('handoff_redacted', sa.Boolean(), nullable=False),
    sa.Column('tenant_id', sa.String(length=255), nullable=False),
    sa.Column('metadata', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['thread_id'], ['conversation_threads.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('conversation_messages', schema=None) as batch_op:
        batch_op.create_index('ix_conv_messages_actor_id', ['actor_id'], unique=False)
        batch_op.create_index('ix_conv_messages_tenant_id', ['tenant_id'], unique=False)
        batch_op.create_index('ix_conv_messages_thread_id', ['thread_id'], unique=False)
        batch_op.create_index('ix_conv_messages_tool_call_id', ['tool_call_id'], unique=False)
        batch_op.create_index('uq_conv_messages_thread_seq', ['thread_id', 'sequence_number'], unique=True)

    op.create_table('memory_relationships',
    sa.Column('id', memoryhub_local.models.dialect.PortableUUID(length=36), nullable=False),
    sa.Column('source_id', memoryhub_local.models.dialect.PortableUUID(length=36), nullable=False),
    sa.Column('target_id', memoryhub_local.models.dialect.PortableUUID(length=36), nullable=False),
    sa.Column('relationship_type', sa.String(length=50), nullable=False),
    sa.Column('metadata_', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('created_by', sa.String(length=255), nullable=False),
    sa.Column('tenant_id', sa.String(length=255), nullable=False),
    sa.Column('valid_from', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('valid_until', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint('source_id != target_id', name='ck_memory_relationships_no_self_ref'),
    sa.ForeignKeyConstraint(['source_id'], ['memory_nodes.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['target_id'], ['memory_nodes.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('memory_relationships', schema=None) as batch_op:
        batch_op.create_index('ix_memory_relationships_source_type', ['source_id', 'relationship_type'], unique=False)
        batch_op.create_index('ix_memory_relationships_source_type_validity', ['source_id', 'relationship_type', 'valid_until'], unique=False)
        batch_op.create_index('ix_memory_relationships_target_type', ['target_id', 'relationship_type'], unique=False)
        batch_op.create_index('ix_memory_relationships_tenant', ['tenant_id'], unique=False)
        batch_op.create_index('ix_memory_relationships_type', ['relationship_type'], unique=False)

    op.create_table('project_memberships',
    sa.Column('id', memoryhub_local.models.dialect.PortableUUID(length=36), nullable=False),
    sa.Column('project_id', sa.String(length=255), nullable=False),
    sa.Column('user_id', sa.String(length=255), nullable=False),
    sa.Column('role', sa.String(length=50), server_default='member', nullable=False),
    sa.Column('joined_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('joined_by', sa.String(length=255), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['projects.name'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('project_id', 'user_id', name='uq_project_memberships_member')
    )
    with op.batch_alter_table('project_memberships', schema=None) as batch_op:
        batch_op.create_index('ix_project_memberships_project', ['project_id'], unique=False)
        batch_op.create_index('ix_project_memberships_user', ['user_id'], unique=False)

    op.create_table('reconciliation_decisions',
    sa.Column('id', memoryhub_local.models.dialect.PortableUUID(length=36), nullable=False),
    sa.Column('extraction_run_id', sa.Text(), nullable=False),
    sa.Column('candidate_content', sa.Text(), nullable=False),
    sa.Column('candidate_stub', sa.Text(), nullable=False),
    sa.Column('nearest_match_id', memoryhub_local.models.dialect.PortableUUID(length=36), nullable=True),
    sa.Column('similarity_score', sa.Float(), nullable=True),
    sa.Column('action', sa.String(length=20), nullable=False),
    sa.Column('tiebreaker_verdict', sa.String(length=20), nullable=True),
    sa.Column('content_type_match', sa.Boolean(), nullable=True),
    sa.Column('domain_match', sa.Boolean(), nullable=True),
    sa.Column('memory_id', memoryhub_local.models.dialect.PortableUUID(length=36), nullable=True),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('owner_id', sa.String(length=255), nullable=False),
    sa.Column('tenant_id', sa.String(length=255), nullable=False),
    sa.Column('scope', sa.String(length=50), nullable=False),
    sa.Column('scope_id', sa.String(length=255), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['memory_id'], ['memory_nodes.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['nearest_match_id'], ['memory_nodes.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('reconciliation_decisions', schema=None) as batch_op:
        batch_op.create_index('ix_recon_decisions_run', ['extraction_run_id'], unique=False)
        batch_op.create_index('ix_recon_decisions_tenant', ['tenant_id'], unique=False)

    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('reconciliation_decisions', schema=None) as batch_op:
        batch_op.drop_index('ix_recon_decisions_tenant')
        batch_op.drop_index('ix_recon_decisions_run')

    op.drop_table('reconciliation_decisions')
    with op.batch_alter_table('project_memberships', schema=None) as batch_op:
        batch_op.drop_index('ix_project_memberships_user')
        batch_op.drop_index('ix_project_memberships_project')

    op.drop_table('project_memberships')
    with op.batch_alter_table('memory_relationships', schema=None) as batch_op:
        batch_op.drop_index('ix_memory_relationships_type')
        batch_op.drop_index('ix_memory_relationships_tenant')
        batch_op.drop_index('ix_memory_relationships_target_type')
        batch_op.drop_index('ix_memory_relationships_source_type_validity')
        batch_op.drop_index('ix_memory_relationships_source_type')

    op.drop_table('memory_relationships')
    with op.batch_alter_table('conversation_messages', schema=None) as batch_op:
        batch_op.drop_index('uq_conv_messages_thread_seq')
        batch_op.drop_index('ix_conv_messages_tool_call_id')
        batch_op.drop_index('ix_conv_messages_thread_id')
        batch_op.drop_index('ix_conv_messages_tenant_id')
        batch_op.drop_index('ix_conv_messages_actor_id')

    op.drop_table('conversation_messages')
    with op.batch_alter_table('conversation_extractions', schema=None) as batch_op:
        batch_op.drop_index('ix_conv_extractions_thread_id')
        batch_op.drop_index('ix_conv_extractions_tenant')
        batch_op.drop_index('ix_conv_extractions_memory_node')

    op.drop_table('conversation_extractions')
    with op.batch_alter_table('conversation_extraction_failures', schema=None) as batch_op:
        batch_op.drop_index('ix_conv_extraction_failures_thread_id')
        batch_op.drop_index('ix_conv_extraction_failures_tenant')

    op.drop_table('conversation_extraction_failures')
    with op.batch_alter_table('contradiction_reports', schema=None) as batch_op:
        batch_op.drop_index('ix_contradiction_reports_tenant')
        batch_op.drop_index('ix_contradiction_reports_resolved_created')
        batch_op.drop_index('ix_contradiction_reports_memory_resolved')

    op.drop_table('contradiction_reports')
    with op.batch_alter_table('campaign_memberships', schema=None) as batch_op:
        batch_op.drop_index('ix_campaign_memberships_project')
        batch_op.drop_index('ix_campaign_memberships_campaign')

    op.drop_table('campaign_memberships')
    with op.batch_alter_table('role_assignments', schema=None) as batch_op:
        batch_op.drop_index('ix_role_assignments_user')
        batch_op.drop_index('ix_role_assignments_tenant')
        batch_op.drop_index('ix_role_assignments_role')

    op.drop_table('role_assignments')
    op.drop_table('purge_log')
    with op.batch_alter_table('projects', schema=None) as batch_op:
        batch_op.drop_index('ix_projects_tenant_id')

    op.drop_table('projects')
    with op.batch_alter_table('memory_nodes', schema=None) as batch_op:
        batch_op.drop_index('ix_memory_nodes_tenant_scope')
        batch_op.drop_index('ix_memory_nodes_status')
        batch_op.drop_index('ix_memory_nodes_source')
        batch_op.drop_index('ix_memory_nodes_scope_id')
        batch_op.drop_index(batch_op.f('ix_memory_nodes_scope'))
        batch_op.drop_index('ix_memory_nodes_relevant_until')
        batch_op.drop_index(batch_op.f('ix_memory_nodes_parent_id'))
        batch_op.drop_index('ix_memory_nodes_owner_scope_current')
        batch_op.drop_index(batch_op.f('ix_memory_nodes_owner_id'))
        batch_op.drop_index(batch_op.f('ix_memory_nodes_is_current'))
        batch_op.drop_index('ix_memory_nodes_expires_at')
        batch_op.drop_index(batch_op.f('ix_memory_nodes_driver_id'))
        batch_op.drop_index('ix_memory_nodes_deleted_at')
        batch_op.drop_index(batch_op.f('ix_memory_nodes_actor_id'))

    op.drop_table('memory_nodes')
    with op.batch_alter_table('curator_rules', schema=None) as batch_op:
        batch_op.drop_index('ix_curator_rules_trigger')
        batch_op.drop_index('ix_curator_rules_tenant')
        batch_op.drop_index('ix_curator_rules_layer_owner')
        batch_op.drop_index('ix_curator_rules_enabled')

    op.drop_table('curator_rules')
    with op.batch_alter_table('conversation_threads', schema=None) as batch_op:
        batch_op.drop_index('ix_conv_threads_tenant_scope')
        batch_op.drop_index('ix_conv_threads_status')
        batch_op.drop_index('ix_conv_threads_scope_id')
        batch_op.drop_index('ix_conv_threads_owner_scope')
        batch_op.drop_index('ix_conv_threads_expires_at')
        batch_op.drop_index('ix_conv_threads_deleted_at')
        batch_op.drop_index('ix_conv_threads_a2a_context_id')

    op.drop_table('conversation_threads')
    with op.batch_alter_table('campaigns', schema=None) as batch_op:
        batch_op.drop_index('ix_campaigns_tenant')

    op.drop_table('campaigns')
    # ### end Alembic commands ###

"""Campaign membership resolution for RBAC.

Provides helpers that resolve which campaigns a caller has access to,
based on project enrollment. Used by the authz layer and search filters
to include campaign-scoped memories in results.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from memoryhub_core.models.campaign import Campaign, CampaignMembership


async def get_campaigns_for_project(
    session: AsyncSession,
    project_id: str,
    tenant_id: str,
) -> set[str]:
    """Return the set of campaign IDs (as strings) accessible to a project.

    A project has access to a campaign when:
    1. The project is enrolled in the campaign (campaign_memberships row exists)
    2. The campaign belongs to the same tenant
    3. The campaign status is 'active'

    Returns campaign UUIDs as strings since memory_nodes.owner_id is VARCHAR
    and campaign-scoped memories use the campaign UUID as their owner_id.
    """
    stmt = (
        select(Campaign.id)
        .join(CampaignMembership, Campaign.id == CampaignMembership.campaign_id)
        .where(
            CampaignMembership.project_id == project_id,
            Campaign.tenant_id == tenant_id,
            Campaign.status == "active",
        )
    )
    result = await session.execute(stmt)
    return {str(row[0]) for row in result.all()}

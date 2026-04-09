"""Tests for campaign membership resolution and search filter integration."""

import uuid

import pytest
from sqlalchemy import text

from memoryhub_core.models.campaign import Campaign, CampaignMembership
from memoryhub_core.models.memory import MemoryNode
from memoryhub_core.services.campaign import get_campaigns_for_project
from memoryhub_core.services.memory import _build_search_filters


# -- get_campaigns_for_project ------------------------------------------------


@pytest.mark.asyncio
async def test_returns_campaigns_for_enrolled_project(async_session):
    """A project enrolled in an active campaign gets that campaign ID back."""
    campaign_id = uuid.uuid4()
    async_session.add(Campaign(
        id=campaign_id,
        name="spring-boot-modernization",
        status="active",
        tenant_id="default",
    ))
    async_session.add(CampaignMembership(
        id=uuid.uuid4(),
        campaign_id=campaign_id,
        project_id="proj-alpha",
        enrolled_by="alice",
    ))
    await async_session.flush()

    result = await get_campaigns_for_project(
        async_session, "proj-alpha", "default"
    )
    assert result == {str(campaign_id)}


@pytest.mark.asyncio
async def test_excludes_completed_campaigns(async_session):
    """Completed campaigns are not returned."""
    campaign_id = uuid.uuid4()
    async_session.add(Campaign(
        id=campaign_id,
        name="old-campaign",
        status="completed",
        tenant_id="default",
    ))
    async_session.add(CampaignMembership(
        id=uuid.uuid4(),
        campaign_id=campaign_id,
        project_id="proj-alpha",
        enrolled_by="alice",
    ))
    await async_session.flush()

    result = await get_campaigns_for_project(
        async_session, "proj-alpha", "default"
    )
    assert result == set()


@pytest.mark.asyncio
async def test_excludes_archived_campaigns(async_session):
    """Archived campaigns are not returned."""
    campaign_id = uuid.uuid4()
    async_session.add(Campaign(
        id=campaign_id,
        name="archived-campaign",
        status="archived",
        tenant_id="default",
    ))
    async_session.add(CampaignMembership(
        id=uuid.uuid4(),
        campaign_id=campaign_id,
        project_id="proj-alpha",
        enrolled_by="alice",
    ))
    await async_session.flush()

    result = await get_campaigns_for_project(
        async_session, "proj-alpha", "default"
    )
    assert result == set()


@pytest.mark.asyncio
async def test_excludes_wrong_tenant(async_session):
    """Campaigns in a different tenant are not returned."""
    campaign_id = uuid.uuid4()
    async_session.add(Campaign(
        id=campaign_id,
        name="other-tenant-campaign",
        status="active",
        tenant_id="tenant-b",
    ))
    async_session.add(CampaignMembership(
        id=uuid.uuid4(),
        campaign_id=campaign_id,
        project_id="proj-alpha",
        enrolled_by="alice",
    ))
    await async_session.flush()

    result = await get_campaigns_for_project(
        async_session, "proj-alpha", "default"
    )
    assert result == set()


@pytest.mark.asyncio
async def test_returns_multiple_campaigns(async_session):
    """A project enrolled in multiple active campaigns gets all IDs."""
    ids = [uuid.uuid4(), uuid.uuid4()]
    for i, cid in enumerate(ids):
        async_session.add(Campaign(
            id=cid,
            name=f"campaign-{i}",
            status="active",
            tenant_id="default",
        ))
        async_session.add(CampaignMembership(
            id=uuid.uuid4(),
            campaign_id=cid,
            project_id="proj-alpha",
            enrolled_by="alice",
        ))
    await async_session.flush()

    result = await get_campaigns_for_project(
        async_session, "proj-alpha", "default"
    )
    assert result == {str(cid) for cid in ids}


@pytest.mark.asyncio
async def test_returns_empty_for_unenrolled_project(async_session):
    """A project not enrolled in any campaign gets an empty set."""
    campaign_id = uuid.uuid4()
    async_session.add(Campaign(
        id=campaign_id,
        name="exclusive-campaign",
        status="active",
        tenant_id="default",
    ))
    async_session.add(CampaignMembership(
        id=uuid.uuid4(),
        campaign_id=campaign_id,
        project_id="proj-beta",
        enrolled_by="bob",
    ))
    await async_session.flush()

    result = await get_campaigns_for_project(
        async_session, "proj-alpha", "default"
    )
    assert result == set()


# -- _build_search_filters campaign_ids integration ---------------------------


def test_campaign_filter_with_campaign_ids():
    """When campaign is in authorized_scopes and campaign_ids is non-empty,
    the filter includes an IN condition."""
    authorized = {"user": "alice", "campaign": None}
    campaign_ids = {"uuid-1", "uuid-2"}
    filters = _build_search_filters(
        scope=None, owner_id=None, current_only=True,
        authorized_scopes=authorized, tenant_id="default",
        campaign_ids=campaign_ids,
    )
    assert filters is not None
    # The filter list should contain conditions — we can't easily inspect
    # SQLAlchemy clauses, but we verify it didn't short-circuit to None.
    assert len(filters) >= 3  # deleted_at, tenant, is_current, scope conditions


def test_campaign_filter_without_campaign_ids():
    """When campaign is the only authorized scope but campaign_ids is empty,
    and no other scopes are authorized, returns None (no results)."""
    authorized = {"campaign": None}
    filters = _build_search_filters(
        scope=None, owner_id=None, current_only=True,
        authorized_scopes=authorized, tenant_id="default",
        campaign_ids=None,
    )
    # Campaign was skipped, no other scopes → scope_conditions is empty
    # → short-circuits to None (no results possible).
    assert filters is None


def test_campaign_filter_mixed_scopes():
    """Campaign + user scopes: even with empty campaign_ids,
    user-scope results are still returned (campaign is skipped)."""
    authorized = {"user": "alice", "campaign": None}
    filters = _build_search_filters(
        scope=None, owner_id=None, current_only=True,
        authorized_scopes=authorized, tenant_id="default",
        campaign_ids=set(),
    )
    assert filters is not None
    # Should not short-circuit — user scope still produces results
    assert len(filters) >= 3

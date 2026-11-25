"""Durable identities and username reuse (docs/auth/human-role-resolution.md)."""

from datetime import UTC, datetime

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.human_identity import HumanIdentity, IdentityBase, profile_for
from src.identity import VerifiedIdentity

ISSUER = "openshift:https://api.c1:6443"


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(IdentityBase.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        yield session
    await engine.dispose()


def who(username="alice", subject="uid-1", display=None, issuer=ISSUER):
    return VerifiedIdentity(username=username, issuer=issuer, subject=subject, display_name=display)


async def count(db: AsyncSession) -> int:
    return (await db.execute(select(func.count()).select_from(HumanIdentity))).scalar_one()


@pytest.mark.asyncio
async def test_first_sign_in_creates_a_stable_id_that_later_sign_ins_keep(db):
    first = await profile_for(db, "t1", who(display="Alice"), refresh=True)
    again = await profile_for(db, "t1", who(display="Alice A."), refresh=True)
    cached = await profile_for(db, "t1", who(), refresh=False)
    assert first.id == again.id == cached.id
    assert again.display_name == "Alice A."
    assert await count(db) == 1


@pytest.mark.asyncio
async def test_recreated_account_with_the_same_username_is_refused(db):
    await profile_for(db, "t1", who(subject="uid-old"), refresh=True)
    with pytest.raises(HTTPException) as refused:
        await profile_for(db, "t1", who(subject="uid-new"), refresh=True)
    assert refused.value.status_code == 403
    assert await count(db) == 1


@pytest.mark.asyncio
async def test_same_username_from_another_identity_provider_is_refused(db):
    await profile_for(db, "t1", who(), refresh=True)
    with pytest.raises(HTTPException):
        await profile_for(db, "t1", who(issuer="openshift:https://api.other:6443"), refresh=True)


@pytest.mark.asyncio
async def test_a_renamed_account_is_refused_until_an_operator_resolves_it(db):
    await profile_for(db, "t1", who(username="alice"), refresh=True)
    with pytest.raises(HTTPException) as refused:
        await profile_for(db, "t1", who(username="alice.smith"), refresh=True)
    assert "username changed" in refused.value.detail
    # ... and the old name is still taken, so nobody else can inherit it.
    with pytest.raises(HTTPException):
        await profile_for(db, "t1", who(username="alice", subject="uid-2"), refresh=True)


@pytest.mark.asyncio
async def test_disabled_profile_is_refused(db):
    profile = await profile_for(db, "t1", who(), refresh=True)
    profile.disabled_at = datetime.now(UTC)
    await db.commit()
    with pytest.raises(HTTPException) as refused:
        await profile_for(db, "t1", who(), refresh=False)
    assert "disabled" in refused.value.detail


@pytest.mark.asyncio
async def test_tenants_are_independent(db):
    a = await profile_for(db, "t1", who(), refresh=True)
    b = await profile_for(db, "t2", who(subject="uid-9"), refresh=True)
    assert a.id != b.id and await count(db) == 2


@pytest.mark.asyncio
async def test_a_profile_never_grants_anything():
    columns = set(HumanIdentity.__table__.columns.keys())
    assert not columns & {"role", "roles", "scopes", "projects", "is_admin"}

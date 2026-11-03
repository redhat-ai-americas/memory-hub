import uuid
from datetime import UTC, datetime

import pytest
from memoryhub_core.models.audit import AuditLog
from memoryhub_core.models.base import Base
from memoryhub_core.models.campaign import Campaign, CampaignMembership
from memoryhub_core.models.contradiction import ContradictionReport
from memoryhub_core.models.memory import MemoryNode, MemoryRelationship
from memoryhub_core.models.project import Project, ProjectMembership
from memoryhub_core.models.role import RoleAssignment
from sqlalchemy import JSON, Integer, Text, event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest.fixture
def labs_on(monkeypatch):
    """Turn MemoryHub Labs on for one test (MEMORYHUB_UI_LABS=true)."""
    from src.config import get_settings

    monkeypatch.setenv("MEMORYHUB_UI_LABS", "true")
    get_settings.cache_clear()
    yield
    monkeypatch.delenv("MEMORYHUB_UI_LABS", raising=False)
    get_settings.cache_clear()


@pytest.fixture
async def mutation_db(monkeypatch):
    """Use real persistence with portable column types, without a live service."""
    for column in (MemoryNode.__table__.c.embedding, MemoryNode.__table__.c.domains, AuditLog.__table__.c.metadata):
        monkeypatch.setattr(column, "type", JSON())
    for column in (MemoryNode.__table__.c.domains, MemoryRelationship.__table__.c.metadata_):
        monkeypatch.setattr(column, "server_default", None)
    search = MemoryNode.__table__.c.search_vector
    monkeypatch.setattr(search, "type", Text())
    monkeypatch.setattr(search, "computed", None)
    monkeypatch.setattr(search, "server_default", None)
    monkeypatch.setattr(AuditLog.__table__.c.id, "type", Integer())
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    @event.listens_for(engine.sync_engine, "connect")
    def sqlite_functions(connection, _):
        connection.create_function("uuid_generate_v4", 0, lambda: uuid.uuid4().hex)
        connection.create_function("now", 0, lambda: datetime.now(UTC).isoformat())

    tables = [
        model.__table__
        for model in (
            MemoryNode,
            MemoryRelationship,
            ContradictionReport,
            AuditLog,
            Project,
            ProjectMembership,
            RoleAssignment,
            Campaign,
            CampaignMembership,
        )
    ]
    async with engine.begin() as connection:
        await connection.run_sync(lambda sync: Base.metadata.create_all(sync, tables=tables))
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        yield session
    await engine.dispose()

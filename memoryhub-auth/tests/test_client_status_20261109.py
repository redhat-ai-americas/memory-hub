"""QA 2026-11-09 RT2-CL-05: tokens name their client (azp); resource servers can re-check it."""

import os
import uuid
from datetime import UTC, datetime

import jwt
import pytest

os.environ.setdefault("AUTH_ADMIN_KEY", "test-admin-key")
os.environ["AUTH_INTERNAL_SERVICE_KEY"] = "test-service-key"

from src.models import OAuthClient  # noqa: E402
from src.tokens import create_access_token  # noqa: E402

SERVICE_HEADERS = {"X-Service-Key": "test-service-key"}


@pytest.fixture(autouse=True)
def _service_key(monkeypatch):
    monkeypatch.setenv("AUTH_INTERNAL_SERVICE_KEY", "test-service-key")


async def _add(db_session, client_id, active=True):
    db_session.add(
        OAuthClient(
            id=str(uuid.uuid4()),
            client_id=client_id,
            client_secret_hash="unused",
            client_name=client_id,
            identity_type="service",
            tenant_id="t1",
            default_scopes=["memory:read"],
            active=active,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
    )
    await db_session.commit()


def test_access_token_carries_azp():
    token = create_access_token(subject="u", identity_type="user", tenant_id="t1", scopes=[], client_id="agent-1")
    assert jwt.decode(token, options={"verify_signature": False})["azp"] == "agent-1"


@pytest.mark.asyncio
async def test_active_client_status(client, db_session):
    await _add(db_session, "st-active")
    resp = await client.get("/internal/clients/st-active/status", headers=SERVICE_HEADERS)
    assert resp.status_code == 200
    assert resp.json() == {"client_id": "st-active", "tenant_id": "t1", "scopes": ["memory:read"]}


@pytest.mark.asyncio
async def test_revoked_and_unknown_clients_are_404(client, db_session):
    await _add(db_session, "st-revoked", active=False)
    for cid in ("st-revoked", "st-nobody"):
        assert (await client.get(f"/internal/clients/{cid}/status", headers=SERVICE_HEADERS)).status_code == 404


@pytest.mark.asyncio
async def test_status_requires_service_key(client, db_session):
    await _add(db_session, "st-key")
    assert (await client.get("/internal/clients/st-key/status")).status_code == 401
    assert (await client.get("/internal/clients/st-key/status", headers={"X-Service-Key": "x"})).status_code == 401

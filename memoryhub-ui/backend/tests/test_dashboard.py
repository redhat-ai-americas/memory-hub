"""Tests for the dashboard (redesign) helpers and DB-free endpoints."""

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from src.main import app
from src.routes_admin import _scope_matrix, _validate_settings
from src.ui_common import DEFAULT_TENANT_SETTINGS, _merge, clean_stub


def test_clean_stub_strips_core_suffix():
    assert clean_stub("Prefer UBI images [scope=user, weight=0.8, branches=1]") == "Prefer UBI images"
    assert clean_stub("Plain stub") == "Plain stub"


def test_scope_matrix_enterprise_write_needs_approval():
    rows = {r["tier"]: r for r in _scope_matrix(["memory:read", "memory:write"])}
    assert rows["user"]["read"] and rows["user"]["write"] == "yes"
    assert rows["enterprise"]["write"] == "via approval"
    admin = {r["tier"]: r for r in _scope_matrix(["memory:admin"])}
    assert admin["enterprise"]["write"] == "yes"


def test_scope_matrix_tier_specific_scopes():
    rows = {r["tier"]: r for r in _scope_matrix(["memory:read:project", "memory:write:project"])}
    assert rows["project"]["read"] and rows["project"]["write"] == "yes"
    assert not rows["user"]["read"] and rows["user"]["write"] == "no"


def test_settings_merge_keeps_defaults_and_validation_rejects_bad_values():
    merged = _merge(DEFAULT_TENANT_SETTINGS, {"retrieval": {"max_results": 20}})
    assert merged["retrieval"]["max_results"] == 20
    assert merged["governance"]["contradiction_threshold"] == 5
    _validate_settings(merged)
    merged["retrieval"]["max_results"] = 99
    with pytest.raises(HTTPException):
        _validate_settings(merged)


@pytest.mark.asyncio
async def test_rule_test_regex_reports_column():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/rules/test",
            json={
                "tier": "regex",
                "pattern": "(def |class )",
                "sample": "x = 1\ndef f(): pass",
                "action": "quarantine",
            },
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["matched"] is True
    assert body["matches"][0] == {"text": "def ", "start": 6, "col": 0, "line": 2}


@pytest.mark.asyncio
async def test_rule_test_invalid_regex_is_422():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/rules/test", json={"tier": "regex", "pattern": "(", "sample": "x"})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_auth_status_open_mode_without_dev_key():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/auth/status")
    assert resp.json()["authenticated"] is True

import os

import jwt
import pytest

from src.core.auth import requires_scopes


class _DummyCtx:
    def __init__(self, headers: dict[str, str] | None = None) -> None:
        class _Req:
            def __init__(self, h: dict[str, str]) -> None:
                self.headers = h

        self.request = _Req(headers or {})
        self._errors: list[str] = []

    async def error(self, message: str) -> None:
        self._errors.append(message)


@pytest.fixture(autouse=True)
def _jwt_env(monkeypatch):
    monkeypatch.setenv("MCP_AUTH_JWT_ALG", "HS256")
    monkeypatch.setenv("MCP_AUTH_JWT_SECRET", "test-secret")
    monkeypatch.delenv("MCP_AUTH_JWT_PUBLIC_KEY", raising=False)
    yield


def _make_token(payload: dict) -> str:
    return jwt.encode(
        payload,
        os.getenv("MCP_AUTH_JWT_SECRET", "test-secret"),
        algorithm=os.getenv("MCP_AUTH_JWT_ALG", "HS256"),
    )


@pytest.mark.asyncio
async def test_requires_scopes_allows_when_present():
    @requires_scopes("read")
    async def secured(ctx=None):
        return {"ok": True}

    token = _make_token({"scope": "read"})
    ctx = _DummyCtx({"Authorization": f"Bearer {token}"})
    result = await secured(ctx=ctx)
    assert result == {"ok": True}


@pytest.mark.asyncio
async def test_requires_scopes_denies_when_missing():
    @requires_scopes("admin")
    async def secured(ctx=None):
        return {"ok": True}

    token = _make_token({"scope": "read write"})
    ctx = _DummyCtx({"Authorization": f"Bearer {token}"})
    result = await secured(ctx=ctx)
    assert result.get("error") == "forbidden"
    assert "admin" in result.get("missing", [])


@pytest.mark.asyncio
async def test_requires_scopes_missing_context():
    @requires_scopes("read")
    async def secured():
        return {"ok": True}

    result = await secured()
    assert result.get("error") == "missing context for auth"

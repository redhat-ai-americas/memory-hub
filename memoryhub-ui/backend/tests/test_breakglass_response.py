"""Private content must not leave the server before its incident audit commits."""
import pytest
from httpx import ASGITransport, AsyncClient

from src import breakglass


@pytest.mark.parametrize("audit_fails", [True, False])
async def test_incident_response_waits_for_audit(monkeypatch, audit_fails):
    flushed = False

    async def flush(state):
        nonlocal flushed
        if audit_fails:
            raise RuntimeError("Synthetic unavailable audit store")
        flushed = True

    monkeypatch.setattr(breakglass, "flush", flush)

    async def endpoint(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"private evidence"})

    transport = ASGITransport(app=breakglass.BreakGlassAuditMiddleware(endpoint))
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        response = await c.get("/api/memory/test/context")
    if audit_fails:
        assert response.status_code == 503
        assert "private evidence" not in response.text
    else:
        assert flushed
        assert response.text == "private evidence"

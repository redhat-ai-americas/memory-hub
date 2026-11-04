"""Elevated credentials cannot bypass the super-user incident boundary."""
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException

from src import routes
from src.config import Settings
from src.ui_common import Viewer


@pytest.mark.parametrize("scope", ["memory:admin:super", "memory:admin:cross_tenant"])
def test_platform_admin_cannot_mint_elevated_credentials(scope):
    viewer = Viewer("admin", "Admin", None, "account", "admin")
    with pytest.raises(HTTPException) as error:
        routes._validate_client_scopes(viewer, ["memory:admin", scope])
    assert error.value.status_code == 403
    routes._validate_client_scopes(Viewer("super", "Super", None, "account", "superuser"), [scope])


async def test_platform_admin_cannot_rotate_or_edit_existing_elevated_client(monkeypatch):
    viewer = Viewer("admin", "Admin", None, "account", "admin")
    monkeypatch.setattr(routes, "viewer_from_request", lambda *a: viewer)
    response = Mock()
    response.json.return_value = {"default_scopes": ["memory:admin", "memory:admin:super"]}
    admin_request = AsyncMock(return_value=response)
    monkeypatch.setattr(routes, "_admin_request", admin_request)
    with pytest.raises(HTTPException) as error:
        await routes._client_viewer(Mock(), AsyncMock(), Settings(), "privileged-agent")
    assert error.value.status_code == 403
    assert admin_request.await_args.args[1] == "GET"

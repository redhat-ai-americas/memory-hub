"""Identity and entitlement adapters (docs/auth/human-role-resolution.md)."""

import pytest
from fastapi import HTTPException

from src.config import Settings
from src.identity import (
    Authentication,
    ListEntitlements,
    LocalIdentity,
    ProxyHeaderIdentity,
    VerifiedIdentity,
    entitlement_resolver_for,
    identity_provider_for,
)


def _authn(username="alice", credential=None):
    return Authentication(VerifiedIdentity(username, "test", username), credential=credential)


def test_credential_never_appears_in_repr_or_equality():
    a = _authn(credential="sha256~secret-token")
    b = _authn(credential="sha256~other-token")
    assert "secret-token" not in repr(a)
    assert a == b
    assert a.credential_digest != b.credential_digest
    assert _authn().credential_digest is None


@pytest.mark.asyncio
async def test_list_entitlements_admin_wins_then_user_then_forbidden():
    resolver = ListEntitlements(admins={"alice"}, users={"alice", "bob"})
    assert await resolver.resolve(_authn("alice")) == "admin"
    assert await resolver.resolve(_authn("bob")) == "user"
    with pytest.raises(HTTPException) as denied:
        await resolver.resolve(_authn("carol"))
    assert denied.value.status_code == 403


def test_provider_selection_follows_configuration():
    assert isinstance(identity_provider_for(Settings(ui_auth_mode="local", ui_local_user="dev")), LocalIdentity)
    assert isinstance(identity_provider_for(Settings()), ProxyHeaderIdentity)
    assert isinstance(entitlement_resolver_for(Settings(ui_admin_users="a")), ListEntitlements)

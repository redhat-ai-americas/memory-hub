import hashlib
import logging
import secrets
import time

import jwt

from src.config import settings
from src.keys import get_kid, get_private_key

log = logging.getLogger("memoryhub-auth.tokens")


def create_access_token(
    subject: str,
    identity_type: str,
    tenant_id: str,
    scopes: list[str],
    client_id: str | None = None,
) -> str:
    """Create a signed JWT access token.

    ``azp`` names the OAuth client the token was issued to, so resource servers can
    refuse tokens of a client that was revoked after issuance (QA 2026-11-09 RT2-CL-05).
    """
    now = int(time.time())
    payload = {
        "sub": subject,
        "identity_type": identity_type,
        "tenant_id": tenant_id,
        "scopes": scopes,
        "iat": now,
        "exp": now + settings.access_token_ttl,
        "iss": settings.issuer,
        "aud": settings.audience,
    }
    if client_id:
        payload["azp"] = client_id
    return jwt.encode(
        payload,
        get_private_key(),
        algorithm="RS256",
        headers={"kid": get_kid()},
    )


def create_refresh_token() -> tuple[str, str]:
    """Create a refresh token. Returns (raw_token, sha256_hash)."""
    raw = secrets.token_urlsafe(48)
    token_hash = hashlib.sha256(raw.encode()).hexdigest()
    return raw, token_hash

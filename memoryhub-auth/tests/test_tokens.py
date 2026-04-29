"""Tests for JWT access token and refresh token creation."""
import hashlib

import jwt as pyjwt
import pytest
from src.keys import get_kid, get_public_key
from src.tokens import create_access_token, create_refresh_token


class TestAccessToken:
    def test_required_claims_present(self):
        token = create_access_token(
            subject="agent-1",
            identity_type="service",
            tenant_id="org-acme",
            scopes=["memory:read", "memory:write:organizational"],
        )
        decoded = pyjwt.decode(
            token, get_public_key(), algorithms=["RS256"], audience="memoryhub"
        )
        assert decoded["sub"] == "agent-1"
        assert decoded["identity_type"] == "service"
        assert decoded["tenant_id"] == "org-acme"
        assert set(decoded["scopes"]) == {"memory:read", "memory:write:organizational"}
        assert decoded["iss"] == "https://test-auth.example.com"
        assert decoded["aud"] == "memoryhub"
        assert "iat" in decoded
        assert "exp" in decoded

    def test_ttl_matches_settings(self):
        """exp - iat must equal AUTH_ACCESS_TOKEN_TTL (300 in test env)."""
        token = create_access_token(
            subject="u1", identity_type="user", tenant_id="t1", scopes=["memory:read"]
        )
        decoded = pyjwt.decode(
            token, get_public_key(), algorithms=["RS256"], audience="memoryhub"
        )
        assert decoded["exp"] - decoded["iat"] == 300

    def test_kid_header(self):
        token = create_access_token(
            subject="u1", identity_type="user", tenant_id="t1", scopes=[]
        )
        header = pyjwt.get_unverified_header(token)
        assert header["kid"] == get_kid()
        assert header["alg"] == "RS256"

    def test_empty_scopes(self):
        token = create_access_token(
            subject="u1", identity_type="user", tenant_id="t1", scopes=[]
        )
        decoded = pyjwt.decode(
            token, get_public_key(), algorithms=["RS256"], audience="memoryhub"
        )
        assert decoded["scopes"] == []

    def test_signature_is_invalid_with_wrong_key(self):
        from cryptography.hazmat.primitives.asymmetric import rsa

        other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        token = create_access_token(
            subject="u1", identity_type="user", tenant_id="t1", scopes=[]
        )
        with pytest.raises(pyjwt.InvalidSignatureError):
            pyjwt.decode(
                token,
                other_key.public_key(),
                algorithms=["RS256"],
                audience="memoryhub",
            )


class TestRefreshToken:
    def test_returns_raw_and_hash(self):
        raw, hashed = create_refresh_token()
        assert isinstance(raw, str)
        assert isinstance(hashed, str)

    def test_raw_token_length(self):
        """secrets.token_urlsafe(48) produces at least 64 characters."""
        raw, _ = create_refresh_token()
        assert len(raw) >= 64

    def test_hash_is_sha256_hex(self):
        _, hashed = create_refresh_token()
        assert len(hashed) == 64
        assert all(c in "0123456789abcdef" for c in hashed)

    def test_hash_matches_raw(self):
        raw, hashed = create_refresh_token()
        assert hashlib.sha256(raw.encode()).hexdigest() == hashed

    def test_tokens_are_unique(self):
        raw1, hash1 = create_refresh_token()
        raw2, hash2 = create_refresh_token()
        assert raw1 != raw2
        assert hash1 != hash2

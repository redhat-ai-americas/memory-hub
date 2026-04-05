"""Tests for RSA key loading, JWKS generation, and helper utilities."""
import base64

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from src.keys import (
    _int_to_base64url,
    get_jwks,
    get_kid,
    get_private_key,
    get_public_key,
)


class TestKeyLoading:
    def test_keys_are_loaded(self):
        """Keys should be loaded by the session-scoped autouse fixture."""
        assert get_private_key() is not None
        assert get_public_key() is not None

    def test_private_key_is_rsa(self):
        assert isinstance(get_private_key(), rsa.RSAPrivateKey)

    def test_public_key_is_rsa(self):
        assert isinstance(get_public_key(), rsa.RSAPublicKey)

    def test_kid_is_stable(self):
        """Calling get_kid() repeatedly returns the same value."""
        assert get_kid() == get_kid()
        assert len(get_kid()) > 0

    def test_private_key_size(self):
        """Key must be at least RSA-2048 for security."""
        assert get_private_key().key_size >= 2048


class TestJWKS:
    def test_structure(self):
        jwks = get_jwks()
        assert "keys" in jwks
        assert len(jwks["keys"]) == 1

    def test_key_fields(self):
        key = get_jwks()["keys"][0]
        assert key["kty"] == "RSA"
        assert key["use"] == "sig"
        assert key["alg"] == "RS256"
        assert key["kid"] == get_kid()
        assert "n" in key
        assert "e" in key

    def test_public_key_can_verify_signed_token(self):
        """A token signed with the private key must be verifiable via the JWKS public key."""
        from src.tokens import create_access_token

        token = create_access_token(
            subject="test-user",
            identity_type="user",
            tenant_id="test-tenant",
            scopes=["memory:read"],
        )

        decoded = jwt.decode(
            token,
            get_public_key(),
            algorithms=["RS256"],
            audience="memoryhub",
        )
        assert decoded["sub"] == "test-user"


class TestIntToBase64Url:
    def test_known_value(self):
        """65537 (0x010001) should encode to the well-known RSA public exponent representation."""
        result = _int_to_base64url(65537)
        expected = base64.urlsafe_b64encode(b"\x01\x00\x01").decode().rstrip("=")
        assert result == expected

    def test_no_padding(self):
        """Result must not contain base64 padding characters."""
        assert "=" not in _int_to_base64url(65537)

    def test_roundtrip(self):
        """Decoding the result back to bytes should recover the original integer."""
        n = 12345678901234567890
        encoded = _int_to_base64url(n)
        # Restore padding for standard decode
        padded = encoded + "=" * (-len(encoded) % 4)
        recovered = int.from_bytes(base64.urlsafe_b64decode(padded), "big")
        assert recovered == n

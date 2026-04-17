import base64
import hashlib
import logging
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from src.config import settings

log = logging.getLogger("memoryhub-auth.keys")

_private_key = None
_public_key = None
_kid = None


def _generate_key_pair() -> tuple:
    """Generate a new RSA-2048 key pair."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()
    return private_key, public_key


def _save_keys(private_key, public_key, keys_dir: str) -> None:
    """Save key pair to disk for local development."""
    path = Path(keys_dir)
    path.mkdir(parents=True, exist_ok=True)

    priv_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    (path / "private.pem").write_bytes(priv_pem)
    (path / "public.pem").write_bytes(pub_pem)
    log.info("Generated and saved new RSA key pair to %s", keys_dir)


def _load_key_from_pem(pem_data: bytes, is_private: bool):
    """Load an RSA key from PEM bytes."""
    if is_private:
        return serialization.load_pem_private_key(pem_data, password=None)
    return serialization.load_pem_public_key(pem_data)


def _compute_kid(public_key) -> str:
    """Compute a key ID from the public key's SHA-256 fingerprint."""
    pub_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    digest = hashlib.sha256(pub_bytes).digest()[:8]
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def load_keys() -> None:
    """Load or generate RSA keys. Call once at startup."""
    global _private_key, _public_key, _kid

    # Priority 1: PEM content from env vars
    if settings.rsa_private_key_pem and settings.rsa_public_key_pem:
        _private_key = _load_key_from_pem(settings.rsa_private_key_pem.encode(), is_private=True)
        _public_key = _load_key_from_pem(settings.rsa_public_key_pem.encode(), is_private=False)
        log.info("Loaded RSA keys from environment variables")

    # Priority 2: PEM files from paths
    elif settings.rsa_private_key_path and settings.rsa_public_key_path:
        _private_key = _load_key_from_pem(Path(settings.rsa_private_key_path).read_bytes(), is_private=True)
        _public_key = _load_key_from_pem(Path(settings.rsa_public_key_path).read_bytes(), is_private=False)
        log.info("Loaded RSA keys from file paths")

    # Priority 3: Local dev — load from keys_dir or generate
    else:
        keys_dir = Path(settings.keys_dir)
        priv_path = keys_dir / "private.pem"
        pub_path = keys_dir / "public.pem"

        if priv_path.exists() and pub_path.exists():
            _private_key = _load_key_from_pem(priv_path.read_bytes(), is_private=True)
            _public_key = _load_key_from_pem(pub_path.read_bytes(), is_private=False)
            log.info("Loaded RSA keys from %s", keys_dir)
        else:
            _private_key, _public_key = _generate_key_pair()
            _save_keys(_private_key, _public_key, settings.keys_dir)

    _kid = _compute_kid(_public_key)


def get_private_key():
    """Return the loaded RSA private key."""
    if _private_key is None:
        raise RuntimeError("RSA keys not loaded — call load_keys() at startup")
    return _private_key


def get_public_key():
    """Return the loaded RSA public key."""
    if _public_key is None:
        raise RuntimeError("RSA keys not loaded — call load_keys() at startup")
    return _public_key


def get_kid() -> str:
    """Return the key ID."""
    if _kid is None:
        raise RuntimeError("RSA keys not loaded — call load_keys() at startup")
    return _kid


def _int_to_base64url(n: int) -> str:
    """Convert an integer to a base64url-encoded string."""
    byte_length = (n.bit_length() + 7) // 8
    n_bytes = n.to_bytes(byte_length, byteorder="big")
    return base64.urlsafe_b64encode(n_bytes).decode().rstrip("=")


def get_jwks() -> dict:
    """Return the JWKS document containing the public key."""
    pub = get_public_key()
    pub_numbers = pub.public_numbers()

    return {
        "keys": [
            {
                "kty": "RSA",
                "use": "sig",
                "alg": "RS256",
                "kid": get_kid(),
                "n": _int_to_base64url(pub_numbers.n),
                "e": _int_to_base64url(pub_numbers.e),
            }
        ]
    }

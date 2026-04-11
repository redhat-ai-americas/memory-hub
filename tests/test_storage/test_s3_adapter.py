"""Unit tests for the S3 storage adapter.

Mocks the minio client to test the async wrapper logic without a real S3 backend.
"""

import uuid
from unittest.mock import MagicMock, patch

import pytest

from memoryhub_core.config import MinIOSettings
from memoryhub_core.storage.s3 import S3StorageAdapter


@pytest.fixture
def settings() -> MinIOSettings:
    return MinIOSettings(
        endpoint="localhost:9000",
        access_key="test-key",
        secret_key="test-secret",
        bucket="test-bucket",
        secure=False,
    )


@pytest.fixture
def adapter(settings: MinIOSettings) -> S3StorageAdapter:
    with patch("memoryhub_core.storage.s3.Minio") as mock_cls:
        mock_cls.return_value = MagicMock()
        inst = S3StorageAdapter(settings)
    return inst


# --- _build_key ---

def test_build_key_format():
    tenant = "acme"
    mem_id = uuid.UUID("12345678-1234-1234-1234-123456789abc")
    ver_id = uuid.UUID("abcdefab-cdef-abcd-efab-cdefabcdefab")
    key = S3StorageAdapter._build_key(tenant, mem_id, ver_id)
    assert key == f"acme/{mem_id}/{ver_id}"


# --- put_content ---

async def test_put_content_returns_key(adapter: S3StorageAdapter):
    tenant = "acme"
    mem_id = uuid.uuid4()
    ver_id = uuid.uuid4()
    content = "hello world"

    key = await adapter.put_content(tenant, mem_id, ver_id, content)
    assert key == f"{tenant}/{mem_id}/{ver_id}"


async def test_put_content_calls_put_object(adapter: S3StorageAdapter):
    tenant = "acme"
    mem_id = uuid.uuid4()
    ver_id = uuid.uuid4()
    content = "hello world"

    await adapter.put_content(tenant, mem_id, ver_id, content)
    adapter._client.put_object.assert_called_once()
    call_args = adapter._client.put_object.call_args
    # put_object is called via partial, so check the mock was invoked
    assert call_args is not None


# --- get_content ---

async def test_get_content_returns_decoded(adapter: S3StorageAdapter):
    mock_response = MagicMock()
    mock_response.read.return_value = b"stored content"
    adapter._client.get_object.return_value = mock_response

    result = await adapter.get_content("acme/some-id/ver-id")
    assert result == "stored content"
    mock_response.close.assert_called_once()
    mock_response.release_conn.assert_called_once()


# --- delete_content ---

async def test_delete_content_calls_remove_object(adapter: S3StorageAdapter):
    await adapter.delete_content("acme/some-id/ver-id")
    adapter._client.remove_object.assert_called_once_with("test-bucket", "acme/some-id/ver-id")


# --- delete_contents ---

async def test_delete_contents_empty_list_is_noop(adapter: S3StorageAdapter):
    await adapter.delete_contents([])
    adapter._client.remove_objects.assert_not_called()


async def test_delete_contents_calls_remove_objects(adapter: S3StorageAdapter):
    adapter._client.remove_objects.return_value = iter([])  # no errors
    refs = ["acme/id1/v1", "acme/id2/v2"]
    await adapter.delete_contents(refs)
    adapter._client.remove_objects.assert_called_once()


# --- ensure_bucket ---

async def test_ensure_bucket_creates_when_not_exists(adapter: S3StorageAdapter):
    adapter._client.bucket_exists.return_value = False
    await adapter.ensure_bucket()
    adapter._client.make_bucket.assert_called_once_with("test-bucket")


async def test_ensure_bucket_skips_when_exists(adapter: S3StorageAdapter):
    adapter._client.bucket_exists.return_value = True
    await adapter.ensure_bucket()
    adapter._client.make_bucket.assert_not_called()

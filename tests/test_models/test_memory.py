"""Tests for memory node Pydantic schemas and utility functions."""

import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from memoryhub.models.schemas import (
    MemoryNodeCreate,
    MemoryNodeRead,
    MemoryNodeStub,
    MemoryNodeUpdate,
    MemoryScope,
    MemoryVersionInfo,
    StorageType,
)
from memoryhub.models.utils import STUB_CONTENT_LIMIT, generate_stub

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class TestMemoryScope:
    def test_valid_scopes(self):
        for value in ("user", "project", "role", "organizational", "enterprise"):
            assert MemoryScope(value) == value

    def test_invalid_scope(self):
        with pytest.raises(ValueError, match="'galaxy' is not a valid MemoryScope"):
            MemoryScope("galaxy")

    def test_scope_string_behavior(self):
        """StrEnum values work as plain strings."""
        assert MemoryScope.USER == "user"
        assert f"scope={MemoryScope.ENTERPRISE}" == "scope=enterprise"


class TestStorageType:
    def test_valid_types(self):
        assert StorageType("inline") == "inline"
        assert StorageType("s3") == "s3"

    def test_invalid_type(self):
        with pytest.raises(ValueError):
            StorageType("gcs")


# ---------------------------------------------------------------------------
# MemoryNodeCreate
# ---------------------------------------------------------------------------


class TestMemoryNodeCreate:
    def test_minimal_create(self, sample_memory_data):
        node = MemoryNodeCreate(**sample_memory_data)
        assert node.content == "prefers Podman over Docker"
        assert node.scope == MemoryScope.USER
        assert node.weight == 0.9
        assert node.owner_id == "user-123"
        assert node.parent_id is None
        assert node.branch_type is None
        assert node.metadata is None

    def test_full_create(self, sample_memory_data):
        parent = uuid.uuid4()
        data = {
            **sample_memory_data,
            "parent_id": parent,
            "branch_type": "rationale",
            "metadata": {"source": "conversation"},
        }
        node = MemoryNodeCreate(**data)
        assert node.parent_id == parent
        assert node.branch_type == "rationale"
        assert node.metadata == {"source": "conversation"}

    def test_default_weight(self):
        node = MemoryNodeCreate(content="test", scope="user", owner_id="u1")
        assert node.weight == 0.7

    def test_weight_lower_bound(self, sample_memory_data):
        node = MemoryNodeCreate(**{**sample_memory_data, "weight": 0.0})
        assert node.weight == 0.0

    def test_weight_upper_bound(self, sample_memory_data):
        node = MemoryNodeCreate(**{**sample_memory_data, "weight": 1.0})
        assert node.weight == 1.0

    @pytest.mark.parametrize("bad_weight", [-0.1, 1.1, 2.0, -100.0])
    def test_weight_out_of_range(self, sample_memory_data, bad_weight):
        with pytest.raises(ValidationError, match="weight"):
            MemoryNodeCreate(**{**sample_memory_data, "weight": bad_weight})

    def test_empty_content_rejected(self, sample_memory_data):
        with pytest.raises(ValidationError, match="content"):
            MemoryNodeCreate(**{**sample_memory_data, "content": ""})

    def test_empty_owner_rejected(self, sample_memory_data):
        with pytest.raises(ValidationError, match="owner_id"):
            MemoryNodeCreate(**{**sample_memory_data, "owner_id": ""})

    def test_invalid_scope_rejected(self, sample_memory_data):
        with pytest.raises(ValidationError, match="scope"):
            MemoryNodeCreate(**{**sample_memory_data, "scope": "galactic"})


# ---------------------------------------------------------------------------
# MemoryNodeUpdate
# ---------------------------------------------------------------------------


class TestMemoryNodeUpdate:
    def test_all_none(self):
        update = MemoryNodeUpdate()
        assert update.content is None
        assert update.weight is None
        assert update.metadata is None

    def test_partial_update(self):
        update = MemoryNodeUpdate(weight=0.5)
        assert update.weight == 0.5
        assert update.content is None

    def test_weight_validation(self):
        with pytest.raises(ValidationError, match="weight"):
            MemoryNodeUpdate(weight=1.5)


# ---------------------------------------------------------------------------
# MemoryNodeRead
# ---------------------------------------------------------------------------


def _make_read_data(**overrides) -> dict:
    """Build a complete MemoryNodeRead-compatible dict."""
    base = {
        "id": uuid.uuid4(),
        "parent_id": None,
        "content": "test content",
        "stub": "test content [scope=user, weight=0.7, branches=0, rationale=no]",
        "storage_type": "inline",
        "content_ref": None,
        "weight": 0.7,
        "scope": "user",
        "branch_type": None,
        "owner_id": "user-1",
        "is_current": True,
        "version": 1,
        "previous_version_id": None,
        "metadata": None,
        "created_at": datetime.now(tz=UTC),
        "updated_at": datetime.now(tz=UTC),
        "has_children": False,
        "has_rationale": False,
    }
    base.update(overrides)
    return base


class TestMemoryNodeRead:
    def test_round_trip(self):
        data = _make_read_data()
        node = MemoryNodeRead(**data)
        assert node.id == data["id"]
        assert node.scope == MemoryScope.USER
        assert node.storage_type == StorageType.INLINE

    def test_with_s3_storage(self):
        data = _make_read_data(storage_type="s3", content_ref="s3://memoryhub/abc123")
        node = MemoryNodeRead(**data)
        assert node.storage_type == StorageType.S3
        assert node.content_ref == "s3://memoryhub/abc123"

    def test_with_children_and_rationale(self):
        data = _make_read_data(has_children=True, has_rationale=True)
        node = MemoryNodeRead(**data)
        assert node.has_children is True
        assert node.has_rationale is True

    def test_serialization(self):
        data = _make_read_data()
        node = MemoryNodeRead(**data)
        dumped = node.model_dump()
        assert isinstance(dumped["id"], uuid.UUID)
        assert dumped["scope"] == "user"

    def test_json_round_trip(self):
        data = _make_read_data()
        node = MemoryNodeRead(**data)
        json_str = node.model_dump_json()
        restored = MemoryNodeRead.model_validate_json(json_str)
        assert restored.id == node.id
        assert restored.scope == node.scope


# ---------------------------------------------------------------------------
# MemoryNodeStub
# ---------------------------------------------------------------------------


class TestMemoryNodeStub:
    def test_stub_fields(self):
        stub = MemoryNodeStub(
            id=uuid.uuid4(),
            stub="prefers Podman [scope=user, weight=0.9, branches=1, rationale=yes]",
            scope="user",
            weight=0.9,
            branch_type=None,
            has_children=True,
            has_rationale=True,
        )
        assert stub.has_rationale is True
        assert stub.has_children is True

    def test_stub_minimal(self):
        stub = MemoryNodeStub(
            id=uuid.uuid4(),
            stub="short memory",
            scope="project",
            weight=0.5,
        )
        assert stub.branch_type is None
        assert stub.has_children is False
        assert stub.has_rationale is False


# ---------------------------------------------------------------------------
# MemoryVersionInfo
# ---------------------------------------------------------------------------


class TestMemoryVersionInfo:
    def test_version_info(self):
        info = MemoryVersionInfo(
            id=uuid.uuid4(),
            version=3,
            is_current=True,
            created_at=datetime.now(tz=UTC),
            stub="some stub",
        )
        assert info.version == 3
        assert info.is_current is True

    def test_version_must_be_positive(self):
        with pytest.raises(ValidationError, match="version"):
            MemoryVersionInfo(
                id=uuid.uuid4(),
                version=0,
                is_current=False,
                created_at=datetime.now(tz=UTC),
                stub="stub",
            )


# ---------------------------------------------------------------------------
# generate_stub utility
# ---------------------------------------------------------------------------


class TestGenerateStub:
    def test_short_content(self):
        result = generate_stub("hello world", "user", 0.9, 2, True)
        assert result == "hello world [scope=user, weight=0.9, branches=2, rationale=yes]"

    def test_long_content_truncated(self):
        long_content = "x" * 500
        result = generate_stub(long_content, "enterprise", 1.0, 0, False)
        # Content portion should be exactly STUB_CONTENT_LIMIT chars
        prefix = result.split(" [scope=")[0]
        assert len(prefix) == STUB_CONTENT_LIMIT
        assert result.endswith("[scope=enterprise, weight=1.0, branches=0, rationale=no]")

    def test_exact_limit_content(self):
        content = "a" * STUB_CONTENT_LIMIT
        result = generate_stub(content, "project", 0.5, 1, False)
        prefix = result.split(" [scope=")[0]
        assert len(prefix) == STUB_CONTENT_LIMIT

    def test_empty_content(self):
        result = generate_stub("", "user", 0.0, 0, False)
        assert result == " [scope=user, weight=0.0, branches=0, rationale=no]"

    def test_rationale_flag(self):
        yes = generate_stub("mem", "user", 0.5, 0, True)
        no = generate_stub("mem", "user", 0.5, 0, False)
        assert "rationale=yes" in yes
        assert "rationale=no" in no

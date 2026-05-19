"""Tests for Obsidian export functionality."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from memoryhub.export import _memory_to_markdown, _generate_obsidian_config


def test_memory_to_markdown_basic():
    """Test basic memory to markdown conversion."""
    memory = {
        "id": "test-uuid-123",
        "scope": "user",
        "weight": 0.8,
        "owner_id": "user-456",
        "version": 2,
        "content": "This is test memory content.",
        "created_at": "2024-01-15T10:30:00Z",
        "updated_at": "2024-01-16T14:20:00Z",
        "domains": ["Python", "Testing"],
    }

    markdown = _memory_to_markdown(memory)

    # Check frontmatter
    assert "---" in markdown
    assert "id: test-uuid-123" in markdown
    assert "scope: user" in markdown
    assert "weight: 0.8" in markdown
    assert "owner: user-456" in markdown
    assert "version: 2" in markdown
    assert "created: 2024-01-15T10:30:00Z" in markdown
    assert "updated: 2024-01-16T14:20:00Z" in markdown

    # Check domains in YAML list format
    assert "domains:" in markdown
    assert "  - Python" in markdown
    assert "  - Testing" in markdown

    # Check tags
    assert "tags:" in markdown
    assert "  - scope/user" in markdown
    assert "  - Python" in markdown
    assert "  - Testing" in markdown

    # Check content
    assert "This is test memory content." in markdown


def test_memory_to_markdown_with_content_type():
    """Test memory with content_type field."""
    memory = {
        "id": "test-uuid-456",
        "scope": "project",
        "weight": 0.9,
        "owner_id": "user-789",
        "version": 1,
        "content": "Behavioral pattern example.",
        "content_type": "behavioral",
    }

    markdown = _memory_to_markdown(memory)

    assert "content_type: behavioral" in markdown


def test_memory_to_markdown_entity_node():
    """Test entity node generates entity-specific tags."""
    memory = {
        "id": "entity-123",
        "scope": "user",
        "weight": 0.7,
        "owner_id": "user-abc",
        "version": 1,
        "content": "John Doe is a software engineer.",
        "branch_type": "entity:person",
    }

    markdown = _memory_to_markdown(memory)

    # Check entity tags
    assert "  - entity" in markdown
    assert "  - entity/person" in markdown


def test_memory_to_markdown_with_relationships():
    """Test memory with relationships generates wikilinks."""
    memory = {
        "id": "memory-source",
        "scope": "user",
        "weight": 0.7,
        "owner_id": "user-xyz",
        "version": 1,
        "content": "Main memory content.",
    }

    relationships = [
        {
            "source_id": "memory-source",
            "target_id": "memory-target-1",
            "relationship_type": "related",
        },
        {
            "source_id": "memory-source",
            "target_id": "memory-target-2",
            "relationship_type": "supersedes",
        },
        {
            "source_id": "memory-other",
            "target_id": "memory-source",
            "relationship_type": "references",
        },
    ]

    markdown = _memory_to_markdown(memory, relationships)

    # Check relationships section
    assert "## Relationships" in markdown
    assert "[[memory-target-1]] (related)" in markdown
    assert "[[memory-target-2]] (supersedes)" in markdown
    assert "[[memory-other]] (references)" in markdown


def test_memory_to_markdown_no_domains():
    """Test memory without domains field."""
    memory = {
        "id": "test-uuid-789",
        "scope": "organizational",
        "weight": 0.5,
        "owner_id": "org-123",
        "version": 1,
        "content": "Organization-wide policy.",
    }

    markdown = _memory_to_markdown(memory)

    # Should still have tags section with scope tag
    assert "tags:" in markdown
    assert "  - scope/organizational" in markdown

    # Should not have domains section
    assert "domains:" not in markdown


def test_memory_to_markdown_empty_content():
    """Test memory with empty content."""
    memory = {
        "id": "empty-content",
        "scope": "user",
        "weight": 0.7,
        "owner_id": "user-empty",
        "version": 1,
        "content": "",
    }

    markdown = _memory_to_markdown(memory)

    # Should still generate valid frontmatter
    assert "id: empty-content" in markdown
    assert "scope: user" in markdown


def test_generate_obsidian_config(tmp_path: Path):
    """Test Obsidian graph.json generation."""
    scopes = {"user", "project", "organizational"}

    _generate_obsidian_config(tmp_path, scopes)

    # Check .obsidian directory created
    obsidian_dir = tmp_path / ".obsidian"
    assert obsidian_dir.exists()
    assert obsidian_dir.is_dir()

    # Check graph.json created
    graph_file = obsidian_dir / "graph.json"
    assert graph_file.exists()

    # Parse and validate JSON
    with graph_file.open() as f:
        config = json.load(f)

    assert "colorGroups" in config
    assert isinstance(config["colorGroups"], list)

    # Check color groups for each scope
    color_groups = config["colorGroups"]
    queries = {group["query"] for group in color_groups}

    assert "tag:#scope/user" in queries
    assert "tag:#scope/project" in queries
    assert "tag:#scope/organizational" in queries


def test_generate_obsidian_config_creates_parent_dirs(tmp_path: Path):
    """Test that _generate_obsidian_config creates necessary parent directories."""
    nested_dir = tmp_path / "nested" / "vault"

    _generate_obsidian_config(nested_dir, {"user"})

    assert (nested_dir / ".obsidian" / "graph.json").exists()


def test_memory_to_markdown_entity_type_extraction():
    """Test different entity types are correctly extracted."""
    test_cases = [
        ("entity:person", "entity/person"),
        ("entity:organization", "entity/organization"),
        ("entity:location", "entity/location"),
    ]

    for branch_type, expected_tag in test_cases:
        memory = {
            "id": "test-entity",
            "scope": "user",
            "weight": 0.7,
            "owner_id": "user-test",
            "version": 1,
            "content": "Test entity content.",
            "branch_type": branch_type,
        }

        markdown = _memory_to_markdown(memory)
        assert f"  - {expected_tag}" in markdown
        assert "  - entity" in markdown


def test_memory_to_markdown_relationship_direction():
    """Test relationships correctly handle direction (outgoing vs incoming)."""
    memory_id = "central-memory"

    memory = {
        "id": memory_id,
        "scope": "user",
        "weight": 0.7,
        "owner_id": "user-abc",
        "version": 1,
        "content": "Central node.",
    }

    # Mix of outgoing and incoming relationships
    relationships = [
        # Outgoing (source is this memory)
        {
            "source_id": memory_id,
            "target_id": "outgoing-target",
            "relationship_type": "relates_to",
        },
        # Incoming (target is this memory)
        {
            "source_id": "incoming-source",
            "target_id": memory_id,
            "relationship_type": "derived_from",
        },
    ]

    markdown = _memory_to_markdown(memory, relationships)

    # Both should appear as wikilinks
    assert "[[outgoing-target]] (relates_to)" in markdown
    assert "[[incoming-source]] (derived_from)" in markdown

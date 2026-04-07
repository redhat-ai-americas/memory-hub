"""Tests for memoryhub.config — project YAML schema and loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from memoryhub.config import (
    CONFIG_FILENAME,
    ConfigError,
    MemoryLoadingConfig,
    ProjectConfig,
    RetrievalDefaults,
    find_project_config,
    load_project_config,
)

# ── Defaults ─────────────────────────────────────────────────────────────────


def test_project_config_defaults():
    """Empty ProjectConfig matches the design-doc defaults for memory-hub itself."""
    pc = ProjectConfig()

    assert pc.memory_loading.mode == "focused"
    assert pc.memory_loading.pattern == "lazy_with_rebias"
    assert pc.memory_loading.focus_source == "auto"
    assert pc.memory_loading.session_focus_weight == 0.4
    assert pc.memory_loading.on_topic_shift == "rebias"
    assert pc.memory_loading.cross_domain_contradiction_detection is False

    # Pattern E knobs default to "off" — included in schema for #62 forward
    # compat but not yet wired into the SDK.
    assert pc.memory_loading.live_subscription is False
    assert pc.memory_loading.push_payload == "uri_only"
    assert pc.memory_loading.push_filter_weight == 0.6
    assert pc.memory_loading.push_transport == "queue"

    assert pc.retrieval_defaults.max_results == 10
    assert pc.retrieval_defaults.max_response_tokens == 4000
    assert pc.retrieval_defaults.default_mode == "full"


# ── Loader: missing file ─────────────────────────────────────────────────────


def test_load_project_config_missing_returns_defaults(tmp_path, monkeypatch):
    """Auto-discovery from a clean directory returns defaults, not an error."""
    monkeypatch.chdir(tmp_path)
    pc = load_project_config()
    assert isinstance(pc, ProjectConfig)
    assert pc.memory_loading.mode == "focused"


def test_load_project_config_explicit_missing_raises(tmp_path):
    """Explicit path that doesn't exist is an error, not silent default."""
    bogus = tmp_path / "nope.yaml"
    with pytest.raises(ConfigError) as exc_info:
        load_project_config(bogus)
    assert exc_info.value.path == bogus
    assert "does not exist" in exc_info.value.detail


def test_load_project_config_empty_file_returns_defaults(tmp_path):
    """An empty YAML file is treated as 'use defaults'."""
    cfg = tmp_path / CONFIG_FILENAME
    cfg.write_text("")
    pc = load_project_config(cfg)
    assert pc == ProjectConfig()


# ── Loader: valid configs ────────────────────────────────────────────────────


def test_load_project_config_valid_full(tmp_path):
    cfg = tmp_path / CONFIG_FILENAME
    cfg.write_text(
        """
memory_loading:
  mode: broad
  pattern: eager
  focus_source: declared
  session_focus_weight: 0.0
  on_topic_shift: ignore
  cross_domain_contradiction_detection: true
  live_subscription: true
  push_payload: full_content
  push_filter_weight: 0.8
  push_transport: pubsub

retrieval_defaults:
  max_results: 25
  max_response_tokens: 8000
  default_mode: index
"""
    )

    pc = load_project_config(cfg)
    assert pc.memory_loading.mode == "broad"
    assert pc.memory_loading.pattern == "eager"
    assert pc.memory_loading.focus_source == "declared"
    assert pc.memory_loading.session_focus_weight == 0.0
    assert pc.memory_loading.cross_domain_contradiction_detection is True
    assert pc.memory_loading.live_subscription is True
    assert pc.memory_loading.push_payload == "full_content"
    assert pc.memory_loading.push_transport == "pubsub"
    assert pc.retrieval_defaults.max_results == 25
    assert pc.retrieval_defaults.max_response_tokens == 8000
    assert pc.retrieval_defaults.default_mode == "index"


def test_load_project_config_partial(tmp_path):
    """Missing top-level sections fall back to per-section defaults."""
    cfg = tmp_path / CONFIG_FILENAME
    cfg.write_text(
        """
retrieval_defaults:
  max_results: 5
"""
    )

    pc = load_project_config(cfg)
    # Partial section: max_results overridden, other fields keep defaults.
    assert pc.retrieval_defaults.max_results == 5
    assert pc.retrieval_defaults.max_response_tokens == 4000
    assert pc.retrieval_defaults.default_mode == "full"
    # memory_loading entirely absent: full defaults.
    assert pc.memory_loading == MemoryLoadingConfig()


# ── Loader: invalid configs ──────────────────────────────────────────────────


def test_load_project_config_invalid_yaml(tmp_path):
    cfg = tmp_path / CONFIG_FILENAME
    cfg.write_text("memory_loading:\n  mode: focused\n   bad indent: x\n")
    with pytest.raises(ConfigError) as exc_info:
        load_project_config(cfg)
    assert "YAML parse error" in exc_info.value.detail


def test_load_project_config_top_level_must_be_mapping(tmp_path):
    cfg = tmp_path / CONFIG_FILENAME
    cfg.write_text("- just\n- a\n- list\n")
    with pytest.raises(ConfigError) as exc_info:
        load_project_config(cfg)
    assert "must be a mapping" in exc_info.value.detail


def test_load_project_config_unknown_top_level_key(tmp_path):
    """Typos at the top level are surfaced, not silently ignored."""
    cfg = tmp_path / CONFIG_FILENAME
    cfg.write_text(
        """
memry_loading:
  mode: focused
"""
    )
    with pytest.raises(ConfigError) as exc_info:
        load_project_config(cfg)
    assert "memry_loading" in exc_info.value.detail


def test_load_project_config_invalid_enum(tmp_path):
    cfg = tmp_path / CONFIG_FILENAME
    cfg.write_text(
        """
memory_loading:
  mode: not_a_real_mode
"""
    )
    with pytest.raises(ConfigError) as exc_info:
        load_project_config(cfg)
    assert "mode" in exc_info.value.detail


def test_load_project_config_out_of_range_weight(tmp_path):
    cfg = tmp_path / CONFIG_FILENAME
    cfg.write_text(
        """
memory_loading:
  session_focus_weight: 2.5
"""
    )
    with pytest.raises(ConfigError) as exc_info:
        load_project_config(cfg)
    assert "session_focus_weight" in exc_info.value.detail


def test_load_project_config_max_results_too_high(tmp_path):
    cfg = tmp_path / CONFIG_FILENAME
    cfg.write_text(
        """
retrieval_defaults:
  max_results: 999
"""
    )
    with pytest.raises(ConfigError) as exc_info:
        load_project_config(cfg)
    assert "max_results" in exc_info.value.detail


# ── Auto-discovery walking up the tree ───────────────────────────────────────


def test_find_project_config_walks_up(tmp_path: Path):
    """find_project_config climbs parents until it finds .memoryhub.yaml."""
    project_root = tmp_path / "myproj"
    nested = project_root / "src" / "package" / "module"
    nested.mkdir(parents=True)
    cfg = project_root / CONFIG_FILENAME
    cfg.write_text("memory_loading:\n  mode: broad\n")

    found = find_project_config(start=nested)
    assert found is not None
    assert found.resolve() == cfg.resolve()


def test_find_project_config_returns_none_when_absent(tmp_path: Path, monkeypatch):
    """Reaches filesystem root cleanly without raising."""
    nested = tmp_path / "nothing" / "here"
    nested.mkdir(parents=True)
    # Make sure no config exists anywhere in this isolated tree.
    found = find_project_config(start=nested)
    # The walk eventually hits / which probably doesn't have one either,
    # but to keep the test deterministic, only assert that nothing under
    # tmp_path is returned.
    if found is not None:
        assert tmp_path not in found.parents

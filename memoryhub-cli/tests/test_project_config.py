"""Tests for memoryhub_cli.project_config — schema build, render, write."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from memoryhub import (
    CONFIG_FILENAME,
    ProjectConfig,
    load_project_config,
)
from memoryhub_cli.project_config import (
    GENERATED_RULE_NAME,
    LEGACY_RULE_NAME,
    InitChoices,
    build_project_config,
    render_rule_file,
    render_yaml,
    rewrite_rule_file,
    suggest_pattern,
    write_init_files,
)

# ── build_project_config ──────────────────────────────────────────────────


def _choices(**overrides) -> InitChoices:
    base = dict(
        session_shape="adaptive",
        pattern="lazy_with_rebias",
        focus_source="auto",
        cross_domain_contradiction_detection=False,
        campaigns=[],
    )
    base.update(overrides)
    return InitChoices(**base)


def test_suggest_pattern_for_each_shape():
    assert suggest_pattern("focused") == "lazy"
    assert suggest_pattern("broad") == "eager"
    assert suggest_pattern("adaptive") == "lazy_with_rebias"


def test_build_project_config_maps_focused_shape_to_focused_mode():
    cfg = build_project_config(_choices(session_shape="focused", pattern="lazy"))
    assert cfg.memory_loading.mode == "focused"
    assert cfg.memory_loading.pattern == "lazy"


def test_build_project_config_maps_broad_shape_to_broad_mode():
    cfg = build_project_config(_choices(session_shape="broad", pattern="eager"))
    assert cfg.memory_loading.mode == "broad"


def test_build_project_config_maps_adaptive_shape_to_focused_mode():
    """Adaptive sessions stay 'focused' on the mode axis but pivot via pattern."""
    cfg = build_project_config(_choices(session_shape="adaptive"))
    assert cfg.memory_loading.mode == "focused"
    assert cfg.memory_loading.pattern == "lazy_with_rebias"


def test_build_project_config_passes_focus_source_through():
    cfg = build_project_config(_choices(focus_source="declared"))
    assert cfg.memory_loading.focus_source == "declared"


def test_build_project_config_passes_contradiction_flag_through():
    cfg = build_project_config(
        _choices(cross_domain_contradiction_detection=True)
    )
    assert cfg.memory_loading.cross_domain_contradiction_detection is True


def test_build_project_config_passes_campaigns_through():
    cfg = build_project_config(
        _choices(campaigns=["spring-boot-modernization", "fips-compliance"])
    )
    assert cfg.memory_loading.campaigns == ["spring-boot-modernization", "fips-compliance"]


def test_build_project_config_empty_campaigns_by_default():
    cfg = build_project_config(_choices())
    assert cfg.memory_loading.campaigns == []


# ── render_yaml ──────────────────────────────────────────────────────────


def test_render_yaml_includes_generator_banner():
    out = render_yaml(build_project_config(_choices()))
    assert "# MemoryHub project configuration" in out
    assert "memoryhub config regenerate" in out


def test_render_yaml_round_trips_through_loader(tmp_path):
    cfg = build_project_config(
        _choices(
            session_shape="broad",
            pattern="eager",
            focus_source="directory",
            cross_domain_contradiction_detection=True,
        )
    )
    path = tmp_path / CONFIG_FILENAME
    path.write_text(render_yaml(cfg))

    reloaded = load_project_config(path)
    assert reloaded == cfg


def test_render_yaml_includes_pattern_e_knobs():
    """Pattern E knobs ship in the YAML so #62 can land without re-shipping schema."""
    out = render_yaml(build_project_config(_choices()))
    parsed = yaml.safe_load(out)
    ml = parsed["memory_loading"]
    assert "live_subscription" in ml
    assert "push_payload" in ml
    assert "push_filter_weight" in ml
    assert "push_transport" in ml


def test_render_yaml_round_trips_with_campaigns(tmp_path):
    cfg = build_project_config(
        _choices(campaigns=["spring-boot-modernization"])
    )
    path = tmp_path / CONFIG_FILENAME
    path.write_text(render_yaml(cfg))
    reloaded = load_project_config(path)
    assert reloaded.memory_loading.campaigns == ["spring-boot-modernization"]


# ── render_rule_file: per-pattern structural assertions ───────────────────


def test_rule_file_eager_required_phrases():
    cfg = build_project_config(_choices(session_shape="broad", pattern="eager"))
    out = render_rule_file(cfg)

    assert "Eager" in out
    # Loads index of everything at startup.
    assert 'mode="index"' in out
    assert "max_results=50" in out
    # Honest about not getting push notifications.
    assert "NOT pushed automatically" in out
    # Shared blocks present.
    assert "## Memory hygiene" in out
    assert "## Contradiction handling" in out
    # Auth placeholder is present.
    assert "register_session(api_key=" in out


def test_rule_file_lazy_required_phrases():
    cfg = build_project_config(_choices(session_shape="focused", pattern="lazy"))
    out = render_rule_file(cfg)

    assert "Lazy" in out
    # Critical: do NOT call search at session start.
    assert "Do NOT" in out
    # Drives the agent to derive intent from the first turn.
    assert "first user turn" in out.lower() or "first user message" in out.lower()
    # Calls out the vague-opening failure mode honestly.
    assert "vague" in out.lower()


def test_rule_file_lazy_with_rebias_specifies_three_pivot_triggers():
    """Pattern C must spell out concrete pivot triggers, not 'watch for pivots'."""
    cfg = build_project_config(_choices(pattern="lazy_with_rebias"))
    out = render_rule_file(cfg)

    assert "Lazy + Rebias" in out
    # The three triggers from the design doc, named explicitly.
    assert "Subsystem change" in out
    assert "Unknown concept" in out
    assert "Explicit switch" in out
    # ADD vs replace is the load-bearing distinction.
    assert "ADD the results" in out
    assert "do not replace it" in out


def test_rule_file_jit_required_phrases():
    cfg = build_project_config(_choices(pattern="jit"))
    out = render_rule_file(cfg)

    assert "Just-in-Time" in out
    # No working set in this pattern.
    assert "no working set" in out.lower()
    # One-shot framing, not accumulation.
    assert "one-shot" in out
    assert "Do not accumulate" in out


def test_rule_file_contradiction_disabled_explains_tradeoff():
    """When contradiction detection is OFF, the rule must explain the tradeoff."""
    cfg = build_project_config(
        _choices(cross_domain_contradiction_detection=False)
    )
    out = render_rule_file(cfg)
    assert "cross_domain_contradiction_detection: false" in out
    assert "tradeoff" in out.lower()


def test_rule_file_contradiction_enabled_keeps_simple_call():
    cfg = build_project_config(
        _choices(cross_domain_contradiction_detection=True)
    )
    out = render_rule_file(cfg)
    assert "tradeoff" not in out.lower()
    assert "report_contradiction" in out


def test_rule_file_warns_against_hand_editing():
    """The 'do not hand-edit' preamble appears on every generated file."""
    cfg = build_project_config(_choices())
    out = render_rule_file(cfg)
    assert "Do not hand-edit" in out
    assert "memoryhub config regenerate" in out


def test_rule_file_includes_campaign_block_when_enrolled():
    cfg = build_project_config(
        _choices(campaigns=["spring-boot-modernization", "fips-compliance"])
    )
    out = render_rule_file(cfg)
    assert "## Campaign enrollment" in out
    assert "- spring-boot-modernization" in out
    assert "- fips-compliance" in out
    assert "project_id" in out


def test_rule_file_omits_campaign_block_when_no_campaigns():
    cfg = build_project_config(_choices(campaigns=[]))
    out = render_rule_file(cfg)
    assert "## Campaign enrollment" not in out


# ── write_init_files ─────────────────────────────────────────────────────


def test_write_init_files_writes_both_paths(tmp_path: Path):
    cfg = build_project_config(_choices())
    result = write_init_files(cfg, tmp_path)

    assert result.yaml_path == tmp_path / CONFIG_FILENAME
    assert result.rule_path == tmp_path / ".claude" / "rules" / GENERATED_RULE_NAME
    assert result.yaml_path.is_file()
    assert result.rule_path.is_file()
    assert result.legacy_backup is None  # nothing to migrate


def test_write_init_files_round_trips_yaml(tmp_path: Path):
    cfg = build_project_config(
        _choices(
            session_shape="broad",
            pattern="eager",
            focus_source="directory",
        )
    )
    result = write_init_files(cfg, tmp_path)
    reloaded = load_project_config(result.yaml_path)
    assert reloaded == cfg


def test_write_init_files_refuses_to_clobber_existing_yaml(tmp_path: Path):
    cfg = build_project_config(_choices())
    write_init_files(cfg, tmp_path)
    with pytest.raises(FileExistsError):
        write_init_files(cfg, tmp_path)


def test_write_init_files_force_overwrites(tmp_path: Path):
    cfg_a = build_project_config(_choices(pattern="lazy"))
    write_init_files(cfg_a, tmp_path)

    cfg_b = build_project_config(_choices(pattern="eager", session_shape="broad"))
    result = write_init_files(cfg_b, tmp_path, overwrite=True)

    rendered = result.rule_path.read_text()
    assert "Eager" in rendered
    # Old pattern's title should not still be in the file.
    assert "Lazy + Rebias" not in rendered


def test_write_init_files_backs_up_legacy_rule(tmp_path: Path):
    rules_dir = tmp_path / ".claude" / "rules"
    rules_dir.mkdir(parents=True)
    legacy = rules_dir / LEGACY_RULE_NAME
    legacy.write_text("# Old hand-written rule\nLoad bearing prose here.")

    cfg = build_project_config(_choices())
    result = write_init_files(cfg, tmp_path)

    assert result.legacy_backup is not None
    assert result.legacy_backup.exists()
    assert "Load bearing prose here." in result.legacy_backup.read_text()
    # Original location is now occupied by... nothing (the new rule lives at
    # memoryhub-loading.md, not memoryhub-integration.md).
    assert not legacy.exists()
    assert result.rule_path.exists()


def test_write_init_files_handles_multiple_legacy_backups(tmp_path: Path):
    """A second init run with a fresh legacy file gets a numbered .bak."""
    rules_dir = tmp_path / ".claude" / "rules"
    rules_dir.mkdir(parents=True)
    legacy = rules_dir / LEGACY_RULE_NAME
    legacy.write_text("v1")

    cfg = build_project_config(_choices())
    first = write_init_files(cfg, tmp_path)
    assert first.legacy_backup is not None
    assert first.legacy_backup.name.endswith(".bak")

    # Re-introduce a legacy file (simulate a project resurrected from VCS),
    # then re-init with --force.
    legacy.write_text("v2")
    second = write_init_files(cfg, tmp_path, overwrite=True)
    assert second.legacy_backup is not None
    assert second.legacy_backup != first.legacy_backup
    assert "v2" in second.legacy_backup.read_text()


# ── rewrite_rule_file ────────────────────────────────────────────────────


# ── CLI wiring smoke tests ───────────────────────────────────────────────


def test_config_app_registers_init_and_regenerate():
    """`memoryhub config init` and `memoryhub config regenerate` are reachable."""
    from typer.testing import CliRunner

    from memoryhub_cli.main import app

    runner = CliRunner()
    result = runner.invoke(app, ["config", "--help"])
    assert result.exit_code == 0
    assert "init" in result.stdout
    assert "regenerate" in result.stdout


def test_config_init_runs_end_to_end_via_cli(tmp_path: Path):
    """Drive the typer command with stdin input and inspect the written files."""
    from typer.testing import CliRunner

    from memoryhub_cli.main import app

    runner = CliRunner()
    # Inputs answer: shape=adaptive(3), pattern=default(3), focus=default(4),
    # contradictions=default(N).
    answers = "3\n3\n4\nN\n\n"
    result = runner.invoke(
        app,
        ["config", "init", "--dir", str(tmp_path)],
        input=answers,
    )
    assert result.exit_code == 0, result.output
    yaml_path = tmp_path / CONFIG_FILENAME
    rule_path = tmp_path / ".claude" / "rules" / GENERATED_RULE_NAME
    assert yaml_path.is_file()
    assert rule_path.is_file()

    cfg = load_project_config(yaml_path)
    assert cfg.memory_loading.pattern == "lazy_with_rebias"
    assert cfg.memory_loading.mode == "focused"
    assert "Lazy + Rebias" in rule_path.read_text()


def test_config_regenerate_picks_up_yaml_edits(tmp_path: Path):
    """Edit the YAML by hand, then run regenerate, and the rule file follows."""
    from typer.testing import CliRunner

    from memoryhub_cli.main import app

    cfg = build_project_config(_choices(pattern="lazy"))
    write_init_files(cfg, tmp_path)

    yaml_path = tmp_path / CONFIG_FILENAME
    # Hand-edit: switch to eager.
    yaml_path.write_text(
        "memory_loading:\n  pattern: eager\n  mode: broad\n"
    )

    runner = CliRunner()
    result = runner.invoke(app, ["config", "regenerate", "--dir", str(tmp_path)])
    assert result.exit_code == 0, result.output

    rule_path = tmp_path / ".claude" / "rules" / GENERATED_RULE_NAME
    assert "Eager" in rule_path.read_text()
    # YAML still has the user's edit; not clobbered.
    assert "pattern: eager" in yaml_path.read_text()


def test_config_regenerate_errors_when_no_yaml(tmp_path: Path):
    from typer.testing import CliRunner

    from memoryhub_cli.main import app

    runner = CliRunner()
    result = runner.invoke(app, ["config", "regenerate", "--dir", str(tmp_path)])
    assert result.exit_code != 0
    assert "memoryhub config init" in result.output


def test_rewrite_rule_file_does_not_touch_yaml(tmp_path: Path):
    """Regenerate flow must not clobber the user's hand-edited YAML."""
    cfg = build_project_config(_choices(pattern="lazy"))
    write_init_files(cfg, tmp_path)
    yaml_path = tmp_path / CONFIG_FILENAME

    # User edits the YAML by hand to switch patterns.
    yaml_path.write_text(
        "memory_loading:\n  pattern: eager\n  mode: broad\n"
    )
    yaml_mtime_before = yaml_path.stat().st_mtime

    edited = load_project_config(yaml_path)
    result = rewrite_rule_file(edited, tmp_path)

    # Rule file reflects the new pattern.
    assert "Eager" in result.rule_path.read_text()
    # YAML untouched.
    assert yaml_path.stat().st_mtime == yaml_mtime_before
    assert "pattern: eager" in yaml_path.read_text()

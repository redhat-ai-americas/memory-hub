import pytest
from pathlib import Path
from src.tools._preview_prompt_utility import preview_prompt


def test_missing_schema_warning(tmp_path, capsys):
    # Create prompt YAML with {output_schema} placeholder
    prompt_file = tmp_path / "test_prompt.yaml"
    prompt_file.write_text(
        """\
name: test_prompt
description: Test
prompt: "<output_schema>{output_schema}</output_schema>"
"""
    )

    # No schema file created
    preview_prompt("test_prompt", strict=False, _prompts_dir=tmp_path)
    out = capsys.readouterr().out
    assert "still contains '{output_schema}'" in out


def test_strict_mode_raises(tmp_path):
    prompt_file = tmp_path / "strict_prompt.yaml"
    prompt_file.write_text(
        """\
name: strict_prompt
description: Test
prompt: "<output_schema>{output_schema}</output_schema>"
"""
    )

    with pytest.raises(RuntimeError) as e:
        preview_prompt("strict_prompt", strict=True, _prompts_dir=tmp_path)
    assert "missing schema file" in str(e.value)

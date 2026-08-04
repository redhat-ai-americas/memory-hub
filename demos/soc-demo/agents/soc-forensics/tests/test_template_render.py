"""Render-tests for the scaffolded ``agent.yaml`` template.

The template ships with a commented-out files.chunking block that
operators flip on by setting CHUNKING_ENABLED + the matching
PGVECTOR_URL / EMBEDDING_URL env vars. These tests load the actual
``templates/agent-loop/agent.yaml`` file through ``AgentConfig`` and
assert that env-var substitution lands the chunking knobs in the right
place.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fipsagents.baseagent.config import AgentConfig, load_config

TEMPLATE_AGENT_YAML = Path(__file__).resolve().parents[1] / "agent.yaml"


@pytest.fixture(scope="module")
def template_path() -> Path:
    assert TEMPLATE_AGENT_YAML.is_file(), (
        f"Template agent.yaml not found at {TEMPLATE_AGENT_YAML}"
    )
    return TEMPLATE_AGENT_YAML


class TestChunkingDefaults:
    """Default deployment: chunking off, files off."""

    def test_loads_with_no_env(self, template_path: Path):
        cfg = load_config(template_path, env={})
        assert isinstance(cfg, AgentConfig)

    def test_chunking_disabled_by_default(self, template_path: Path):
        cfg = load_config(template_path, env={})
        assert cfg.server.files.chunking.enabled is False

    def test_chunking_backend_null_by_default(self, template_path: Path):
        cfg = load_config(template_path, env={})
        assert cfg.server.files.chunking.backend == "null"

    def test_embedding_url_empty_by_default(self, template_path: Path):
        cfg = load_config(template_path, env={})
        assert cfg.server.files.chunking.database_url == ""
        assert cfg.server.files.chunking.embedding_url == ""

    def test_embedding_model_default(self, template_path: Path):
        cfg = load_config(template_path, env={})
        # Mirrors ChunkingConfig.embedding_model default.
        assert cfg.server.files.chunking.embedding_model == "all-MiniLM-L6-v2"

    def test_embedding_dimension_default(self, template_path: Path):
        cfg = load_config(template_path, env={})
        assert cfg.server.files.chunking.embedding_dimension == 768

    def test_table_name_default(self, template_path: Path):
        cfg = load_config(template_path, env={})
        assert cfg.server.files.chunking.table_name == "file_chunks"


class TestChunkingEnabled:
    """A real production deployment flips the env vars on."""

    @pytest.fixture
    def env(self) -> dict[str, str]:
        return {
            "CHUNKING_ENABLED": "true",
            "CHUNKING_BACKEND": "pgvector",
            "PGVECTOR_URL": "postgresql://chunks:secret@pgv:5432/chunks",
            "EMBEDDING_URL": "http://embedding.platform.svc/v1",
            "EMBEDDING_MODEL": "BAAI/bge-small-en-v1.5",
            "EMBEDDING_DIMENSION": "384",
            "CHUNKING_TABLE": "agent_file_chunks",
        }

    def test_chunking_enabled(self, template_path: Path, env: dict[str, str]):
        cfg = load_config(template_path, env=env)
        assert cfg.server.files.chunking.enabled is True

    def test_chunking_backend_pgvector(self, template_path: Path, env: dict[str, str]):
        cfg = load_config(template_path, env=env)
        assert cfg.server.files.chunking.backend == "pgvector"

    def test_database_url_propagates(self, template_path: Path, env: dict[str, str]):
        cfg = load_config(template_path, env=env)
        assert (
            cfg.server.files.chunking.database_url
            == "postgresql://chunks:secret@pgv:5432/chunks"
        )

    def test_embedding_url_propagates(self, template_path: Path, env: dict[str, str]):
        cfg = load_config(template_path, env=env)
        assert (
            cfg.server.files.chunking.embedding_url
            == "http://embedding.platform.svc/v1"
        )

    def test_embedding_model_propagates(self, template_path: Path, env: dict[str, str]):
        cfg = load_config(template_path, env=env)
        assert cfg.server.files.chunking.embedding_model == "BAAI/bge-small-en-v1.5"

    def test_embedding_dimension_coerces(self, template_path: Path, env: dict[str, str]):
        # Env vars are strings; ChunkingConfig must coerce to int.
        cfg = load_config(template_path, env=env)
        assert cfg.server.files.chunking.embedding_dimension == 384

    def test_table_name_propagates(self, template_path: Path, env: dict[str, str]):
        cfg = load_config(template_path, env=env)
        assert cfg.server.files.chunking.table_name == "agent_file_chunks"


class TestFilesBlockUnaffected:
    """Adding chunking should not change the files block defaults."""

    def test_files_disabled_by_default(self, template_path: Path):
        cfg = load_config(template_path, env={})
        assert cfg.server.files.enabled is False

    def test_files_default_max_size(self, template_path: Path):
        cfg = load_config(template_path, env={})
        # 50 MiB — preserved from the FilesConfig default.
        assert cfg.server.files.max_file_size_bytes == 50 * 1024 * 1024


class TestPromptAssemblyScaffold:
    """Prompt assembly scaffolding: identity.md, personality.md, and config block."""

    def test_identity_file_exists(self):
        identity_path = TEMPLATE_AGENT_YAML.parent / "identity.md"
        assert identity_path.is_file(), f"identity.md not found at {identity_path}"

    def test_personality_file_exists(self):
        personality_path = TEMPLATE_AGENT_YAML.parent / "personality.md"
        assert personality_path.is_file(), f"personality.md not found at {personality_path}"

    def test_prompt_assembly_enabled_by_default(self, template_path: Path):
        cfg = load_config(template_path, env={})
        assert cfg.prompt_assembly is not None

    def test_identity_enabled_by_default(self, template_path: Path):
        cfg = load_config(template_path, env={})
        assert cfg.prompt_assembly.identity.enabled is True

    def test_identity_source_is_identity_md(self, template_path: Path):
        cfg = load_config(template_path, env={})
        assert cfg.prompt_assembly.identity.source == "identity.md"

    def test_personality_disabled_by_default(self, template_path: Path):
        cfg = load_config(template_path, env={})
        assert cfg.prompt_assembly.personality.enabled is False

    def test_governance_enabled_by_default(self, template_path: Path):
        cfg = load_config(template_path, env={})
        assert cfg.prompt_assembly.governance_enabled is True

    def test_capabilities_enabled_by_default(self, template_path: Path):
        cfg = load_config(template_path, env={})
        assert cfg.prompt_assembly.capabilities_enabled is True

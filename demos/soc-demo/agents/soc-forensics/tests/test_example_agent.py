"""Smoke tests for the scaffolded MyAgent stub.

This file is intentionally coupled to the scaffold's example agent. When
/create-agent runs (Step 10), it replaces this file entirely with tests
for the new agent. The generic framework test suite (test_agent.py,
test_tools.py, test_config.py, etc.) is what survives scaffolding.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from fipsagents.baseagent.agent import BaseAgent, StepOutcome
from fipsagents.baseagent.config import AgentConfig, BackoffConfig, LLMConfig, LoopConfig
from fipsagents.baseagent.llm import LLMClient, ModelResponse


_TEMPLATE_ROOT = Path(__file__).resolve().parent.parent


def _make_config(**overrides: Any) -> AgentConfig:
    defaults = {
        "model": LLMConfig(
            endpoint="http://test:8321/v1",
            name="test-model",
            temperature=0.5,
            max_tokens=256,
        ),
        "loop": LoopConfig(
            max_iterations=5,
            backoff=BackoffConfig(initial=0.01, max=0.05, multiplier=2.0),
        ),
    }
    defaults.update(overrides)
    return AgentConfig(**defaults)


def _mock_response(content: str | None = None) -> Any:
    message = SimpleNamespace(content=content, tool_calls=None)
    choice = SimpleNamespace(message=message)
    return SimpleNamespace(choices=[choice])


# Import after helpers so the module's top-level imports can resolve.
from agent import MyAgent  # noqa: E402


class TestMyAgentInstantiation:
    def test_is_base_agent_subclass(self):
        assert issubclass(MyAgent, BaseAgent)

    def test_can_instantiate_with_config(self):
        agent = MyAgent(config=_make_config())
        # config is only assigned after setup(); pre-setup it is None.
        assert agent.config is None


class TestMyAgentStep:
    @pytest.mark.asyncio
    async def test_step_returns_model_content(self, tmp_path: Path):
        """The minimal step() shape: call_model -> run_tool_calls -> done.

        With no tool calls in the response, run_tool_calls is a no-op and
        the assistant content flows straight through to StepResult.result.
        """
        agent = MyAgent(
            config=_make_config(),
            base_dir=_TEMPLATE_ROOT,
        )
        await agent.setup()

        agent.llm = MagicMock(spec=LLMClient)
        agent.llm.call_model = AsyncMock(
            return_value=ModelResponse(_mock_response(content="hello world"))
        )

        agent.add_message("user", "say hi")
        result = await agent.step()

        assert result.outcome is StepOutcome.DONE
        assert result.result == "hello world"
        agent.llm.call_model.assert_awaited()

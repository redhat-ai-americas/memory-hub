"""Dynamic discovery of agent class, output model, and LLM tool names."""

from __future__ import annotations

import importlib
import inspect
from functools import lru_cache
from fipsagents.baseagent.agent import BaseAgent

from evals import _TEMPLATE_ROOT


@lru_cache(maxsize=1)
def _discover_agent_class() -> type:
    """Find the single BaseAgent subclass in agent.py.

    Raises RuntimeError with an actionable message when zero or multiple
    subclasses are found.
    """
    agent_module = importlib.import_module("agent")
    candidates = [
        obj
        for _name, obj in inspect.getmembers(agent_module, inspect.isclass)
        if issubclass(obj, BaseAgent) and obj is not BaseAgent
    ]
    if len(candidates) == 0:
        raise RuntimeError(
            "No BaseAgent subclass found in agent.py. "
            "Run /create-agent to generate your agent."
        )
    if len(candidates) > 1:
        names = [c.__name__ for c in candidates]
        raise RuntimeError(
            f"Multiple BaseAgent subclasses in agent.py: {names}. "
            "The eval runner expects exactly one."
        )
    return candidates[0]


@lru_cache(maxsize=1)
def _discover_output_model() -> type | None:
    """Find a Pydantic BaseModel subclass in agent.py for structured output.

    Returns None if the agent does not define one (i.e. does not use
    structured output).
    """
    from pydantic import BaseModel as PydanticBaseModel

    agent_module = importlib.import_module("agent")
    candidates = [
        obj
        for _name, obj in inspect.getmembers(agent_module, inspect.isclass)
        if issubclass(obj, PydanticBaseModel) and obj is not PydanticBaseModel
    ]
    if not candidates:
        return None
    # Most agents define a single output schema; return the first.
    return candidates[0]


@lru_cache(maxsize=1)
def _discover_llm_tool_name() -> str | None:
    """Find the name of an LLM-visible tool for mock tool call responses.

    Falls back to None if no tools are found, in which case mock responses
    will skip tool call simulation and return text directly.
    """
    try:
        from fipsagents.baseagent.tools import ToolRegistry
        registry = ToolRegistry()
        registry.discover(_TEMPLATE_ROOT / "tools")
        for t in registry.get_all():
            if t.visibility in ("llm_only", "both"):
                return t.name
    except Exception:
        pass
    return None

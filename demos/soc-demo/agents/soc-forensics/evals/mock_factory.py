"""Mock object factories for eval agent instances and OpenAI SDK responses."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

from fipsagents.baseagent.config import AgentConfig, BackoffConfig, LLMConfig, LoopConfig
from fipsagents.baseagent.llm import LLMClient, ModelResponse

from evals import _TEMPLATE_ROOT
from evals.discovery import (
    _discover_agent_class,
    _discover_llm_tool_name,
    _discover_output_model,
)


def _build_mock_instance(model_class: type) -> Any:
    """Create a plausible mock instance of a Pydantic model from its schema.

    Uses ``model_json_schema()`` to inspect fields and populate them with
    type-appropriate placeholder values.
    """
    schema = model_class.model_json_schema()
    props = schema.get("properties", {})
    mock_data: dict[str, Any] = {}
    for field_name, field_schema in props.items():
        field_type = field_schema.get("type", "string")
        if field_type == "string":
            mock_data[field_name] = f"Mock {field_name} for eval"
        elif field_type in ("number", "integer"):
            # Respect JSON Schema constraints if present.
            minimum = field_schema.get("minimum", field_schema.get("exclusiveMinimum", 0))
            maximum = field_schema.get("maximum", field_schema.get("exclusiveMaximum", 1))
            mock_data[field_name] = round((minimum + maximum) / 2, 2)
        elif field_type == "boolean":
            mock_data[field_name] = True
        elif field_type == "array":
            mock_data[field_name] = ["https://example.com/eval-source"]
        else:
            mock_data[field_name] = f"mock_{field_name}"
    return model_class(**mock_data)


def _build_mock_response(
    content: str | None = None,
    tool_calls: list[Any] | None = None,
) -> Any:
    """Construct a fake OpenAI ChatCompletion matching ModelResponse expectations."""
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    choice = SimpleNamespace(message=message)
    return SimpleNamespace(choices=[choice])


def _make_tool_call_obj(name: str, arguments: dict[str, Any]) -> Any:
    """Build a fake tool-call object in OpenAI format."""
    return SimpleNamespace(
        id=f"call_eval_{name}",
        function=SimpleNamespace(
            name=name,
            arguments=json.dumps(arguments),
        ),
    )


def _build_mock_responses(
    query: str,
    fixture_data: dict[str, Any] | None = None,
) -> tuple[list[Any], Any | None, str]:
    """Produce the sequence of mock LLM responses for a single eval case.

    Returns (call_model_side_effects, report_or_none, validation_text).

    The report is built from whatever Pydantic model the agent defines in
    agent.py.  If no model is found (the agent does not use structured
    output), *report* is None and callers should skip call_model_json
    mocking.
    """
    # Detect multi-step queries (comparisons, "vs", multiple topics).
    multi_step_keywords = {"compare", "vs", "versus", "difference", "between"}
    is_multi_step = any(kw in query.lower() for kw in multi_step_keywords)

    side_effects: list[Any] = []

    tool_name = _discover_llm_tool_name()

    if tool_name is None:
        # No LLM-visible tools — skip tool call simulation, just return text.
        side_effects.append(
            ModelResponse(
                _build_mock_response(
                    content=f"Based on analysis of '{query}', here are the findings."
                )
            )
        )
    elif is_multi_step:
        # Simulate multiple tool call rounds.
        tc1 = _make_tool_call_obj(tool_name, {"query": query})
        side_effects.append(
            ModelResponse(_build_mock_response(tool_calls=[tc1]))
        )
        tc2 = _make_tool_call_obj(
            tool_name, {"query": f"{query} detailed comparison"}
        )
        side_effects.append(
            ModelResponse(_build_mock_response(tool_calls=[tc2]))
        )
        side_effects.append(
            ModelResponse(
                _build_mock_response(
                    content=f"After thorough research on '{query}', here are the findings."
                )
            )
        )
    else:
        # Single tool call round.
        search_tc = _make_tool_call_obj(tool_name, {"query": query})
        side_effects.append(
            ModelResponse(_build_mock_response(tool_calls=[search_tc]))
        )
        side_effects.append(
            ModelResponse(
                _build_mock_response(
                    content=f"Based on my research about '{query}', here are the findings."
                )
            )
        )

    # Build a mock report from the agent's Pydantic output model.
    output_model = _discover_output_model()
    report: Any | None = None
    if output_model is not None:
        report = _build_mock_instance(output_model)

    validation_text = "The report addresses the query."

    return side_effects, report, validation_text


async def create_agent(*, use_real_llm: bool = False) -> Any:
    """Create an agent instance by discovering the BaseAgent subclass in agent.py.

    When *use_real_llm* is False (the default), the LLM client is replaced
    with mocks so evals run without a live model endpoint.
    """
    agent_cls = _discover_agent_class()

    config = AgentConfig(
        model=LLMConfig(
            endpoint="http://eval-mock:8321/v1",
            name="eval-mock-model",
            temperature=0.0,
            max_tokens=1024,
        ),
        loop=LoopConfig(
            max_iterations=5,
            backoff=BackoffConfig(initial=0.01, max=0.05, multiplier=2.0),
        ),
    )
    agent = agent_cls(config=config, base_dir=_TEMPLATE_ROOT)

    if use_real_llm:
        await agent.setup()
    else:
        # Partial setup: real tools/prompts/rules/skills, mock LLM.
        agent.config = config
        agent.llm = MagicMock(spec=LLMClient)
        agent.tools.discover(_TEMPLATE_ROOT / "tools")
        prompts_dir = _TEMPLATE_ROOT / "prompts"
        if prompts_dir.is_dir():
            agent.prompts.load_all(prompts_dir)
        rules_dir = _TEMPLATE_ROOT / "rules"
        if rules_dir.is_dir():
            agent.rules.load_all(rules_dir)
        skills_dir = _TEMPLATE_ROOT / "skills"
        if skills_dir.is_dir():
            agent.skills.load_all(skills_dir)
        agent._setup_done = True

    return agent

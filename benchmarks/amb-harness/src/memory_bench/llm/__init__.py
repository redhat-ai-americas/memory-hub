import os

from .base import LLM, Schema
from .anthropic import AnthropicLLM
from .gemini import GeminiLLM
from .vllm import VllmLLM

REGISTRY: dict[str, type[LLM]] = {
    "anthropic": AnthropicLLM,
    "gemini": GeminiLLM,
    "vllm": VllmLLM,
}


def get_llm(name: str = "anthropic") -> LLM:
    if name not in REGISTRY:
        raise ValueError(f"Unknown LLM: '{name}'. Available: {list(REGISTRY)}")
    return REGISTRY[name]()


def get_answer_llm() -> LLM:
    provider = os.environ.get("OMB_ANSWER_LLM", "anthropic")
    model = os.environ.get("OMB_ANSWER_MODEL")
    cls = REGISTRY.get(provider)
    if cls is None:
        raise ValueError(f"Unknown OMB_ANSWER_LLM: '{provider}'. Available: {list(REGISTRY)}")
    return cls(model) if model else cls()


def get_judge_llm() -> LLM:
    provider = os.environ.get("OMB_JUDGE_LLM", "anthropic")
    model = os.environ.get("OMB_JUDGE_MODEL")
    cls = REGISTRY.get(provider)
    if cls is None:
        raise ValueError(f"Unknown OMB_JUDGE_LLM: '{provider}'. Available: {list(REGISTRY)}")
    return cls(model) if model else cls()

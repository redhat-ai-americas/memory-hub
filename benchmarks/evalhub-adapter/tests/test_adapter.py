"""Unit tests for the AMBAdapter EvalHub integration."""

import pytest

from memoryhub_evalhub.adapter import _detect_llm_provider


class TestDetectLlmProvider:
    def test_gemini_by_name(self):
        assert _detect_llm_provider("https://example.com", "gemini-2.5-flash-lite") == "gemini"

    def test_gemini_by_url(self):
        assert _detect_llm_provider("https://generativelanguage.googleapis.com", "some-model") == "gemini"

    def test_anthropic_by_url(self):
        assert _detect_llm_provider("https://api.anthropic.com", "some-model") == "anthropic"

    def test_anthropic_by_name(self):
        assert _detect_llm_provider("https://example.com", "claude-haiku-4-5") == "anthropic"

    def test_vllm_fallback(self):
        assert _detect_llm_provider("https://my-vllm.example.com", "llama-3-8b") == "vllm"

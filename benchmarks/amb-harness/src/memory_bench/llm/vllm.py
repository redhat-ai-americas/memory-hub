"""vLLM-compatible LLM adapter for MCQ benchmarks.

Uses the OpenAI-compatible chat completions endpoint. For MCQ tasks,
returns structured output by appending a JSON instruction to the prompt
and parsing the response. Does not rely on json_schema response_format
which some vLLM backends silently ignore.
"""

import json
import os
import re
import time

from openai import OpenAI

from .base import LLM, Schema

_MAX_RETRIES = 4
_RETRY_BASE_DELAY = 2


class VllmLLM(LLM):
    def __init__(self, model: str | None = None):
        base_url = os.environ.get("VLLM_BASE_URL", "http://localhost:8000/v1")
        self._client = OpenAI(base_url=base_url, api_key="unused")
        self._model = model or os.environ.get(
            "VLLM_MODEL", "google/gemma-4-E4B-it"
        )

    @property
    def model_id(self) -> str:
        return f"vllm:{self._model}"

    def generate(self, prompt: str, schema: Schema) -> dict:
        fields = ", ".join(
            f'"{k}": <{v.get("type", "string")}>'
            for k, v in schema.properties.items()
        )
        json_instruction = (
            f"\n\nRespond with ONLY a JSON object: {{{fields}}}. "
            "No other text."
        )

        delay = _RETRY_BASE_DELAY
        last_exc = None
        for attempt in range(_MAX_RETRIES):
            try:
                response = self._client.chat.completions.create(
                    model=self._model,
                    messages=[{"role": "user", "content": prompt + json_instruction}],
                    max_tokens=512,
                    temperature=0,
                )
                text = response.choices[0].message.content.strip()
                # Extract JSON from response (may have markdown fences)
                match = re.search(r'\{[^{}]*\}', text, re.DOTALL)
                if match:
                    return json.loads(match.group())
                raise ValueError(f"No JSON found in response: {text[:200]}")
            except (json.JSONDecodeError, ValueError) as e:
                last_exc = e
                if attempt < _MAX_RETRIES - 1:
                    time.sleep(delay)
                    delay *= 2
                    continue
                # Last resort: try to extract choice letter for MCQ
                if "choice" in schema.properties:
                    letter = re.search(r'\b([a-dA-D])\b', text)
                    if letter:
                        return {
                            "choice": letter.group(1),
                            "reasoning": text,
                        }
                raise
            except Exception as e:
                last_exc = e
                msg = str(e)
                if "429" in msg or "503" in msg:
                    if attempt < _MAX_RETRIES - 1:
                        time.sleep(delay)
                        delay *= 2
                        continue
                raise
        raise RuntimeError(f"vLLM request failed after {_MAX_RETRIES} retries: {last_exc}")

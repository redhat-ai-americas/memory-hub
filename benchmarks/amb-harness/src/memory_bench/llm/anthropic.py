import os
import time

from anthropic import Anthropic

from .base import LLM, Schema

_MAX_RETRIES = 6
_RETRY_BASE_DELAY = 5


class AnthropicLLM(LLM):
    def __init__(self, model: str = "claude-sonnet-4-6"):
        self._client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
        self._model = model

    @property
    def model_id(self) -> str:
        return f"anthropic:{self._model}"

    def generate(self, prompt: str, schema: Schema) -> dict:
        tool_def = {
            "name": "respond",
            "description": "Respond with the structured output",
            "input_schema": {
                "type": "object",
                "properties": schema.properties,
                "required": schema.required,
            },
        }
        delay = _RETRY_BASE_DELAY
        last_exc = None
        for attempt in range(_MAX_RETRIES):
            try:
                response = self._client.messages.create(
                    model=self._model,
                    max_tokens=4096,
                    messages=[{"role": "user", "content": prompt}],
                    tools=[tool_def],
                    tool_choice={"type": "tool", "name": "respond"},
                )
                for block in response.content:
                    if block.type == "tool_use" and block.name == "respond":
                        result = block.input
                        missing = [k for k in schema.required if k not in result]
                        if missing:
                            raise ValueError(
                                f"Schema fields {missing} missing from response: "
                                f"{list(result.keys())}"
                            )
                        return result
                raise RuntimeError("No tool_use block found in response")
            except Exception as e:
                last_exc = e
                msg = str(e)
                retryable = (
                    "429" in msg or "529" in msg
                    or "overloaded" in msg.lower()
                    or isinstance(e, ValueError)
                )
                if retryable and attempt < _MAX_RETRIES - 1:
                    time.sleep(delay)
                    delay *= 2
                    continue
                raise
        raise RuntimeError(f"Anthropic request failed after {_MAX_RETRIES} retries: {last_exc}")

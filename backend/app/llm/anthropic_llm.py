"""Claude via the Anthropic SDK, with schema-validated structured output."""

from __future__ import annotations

import logging

import anthropic
from pydantic import BaseModel, ValidationError

from ..config import get_settings
from .base import LLMCall, LLMError, record_usage

log = logging.getLogger(__name__)


class AnthropicLLM:
    def __init__(self) -> None:
        s = get_settings()
        self.settings = s
        self.client = anthropic.Anthropic(api_key=s.anthropic_api_key or None, max_retries=3, timeout=600)
        self.fallbacks = s.llm_server_fallbacks

    def _kwargs(self, call: LLMCall, max_tokens: int) -> dict:
        s = self.settings
        model = s.llm_strong_model if call.tier == "strong" else s.llm_fast_model
        kwargs: dict = {
            "model": model,
            "max_tokens": max_tokens,
            "system": call.system,
            "messages": [{"role": "user", "content": call.content}],
            "output_format": call.output,
        }
        if call.tier == "strong":
            kwargs["thinking"] = {"type": "adaptive"}
            kwargs["output_config"] = {"effort": s.llm_strong_effort}
            if self.fallbacks and model in ("claude-opus-5-5", "claude-opus-5", "claude-fable-5-1"):
                # server-side refusal fallback: the API retries a declined request on a fallback model
                kwargs["extra_headers"] = {"anthropic-beta": "server-side-fallback-2026-07-01"}
                kwargs["extra_body"] = {"fallbacks": "default"}
        return kwargs

    def run(self, call: LLMCall) -> BaseModel:
        attempts = self.settings.llm_max_retries + 1
        max_tokens = 32000 if call.tier == "strong" else 8000
        last_error = "no attempt made"
        for attempt in range(attempts):
            try:
                with self.client.messages.stream(**self._kwargs(call, max_tokens)) as stream:
                    msg = stream.get_final_message()
            except anthropic.BadRequestError as e:
                if self.fallbacks and "fallback" in str(e).lower():
                    log.warning("server-side fallbacks rejected; disabling: %s", e)
                    self.fallbacks = False
                    continue
                raise LLMError(f"{call.step}: bad request: {e}") from e
            except (ValidationError, ValueError) as e:
                last_error = f"invalid structured output: {e}"
                continue
            except anthropic.APIError as e:  # rate limits, 5xx, connection; SDK already retried
                raise LLMError(f"{call.step}: API error: {e}") from e
            u = msg.usage
            record_usage(call.step, u.input_tokens + (u.cache_read_input_tokens or 0) + (u.cache_creation_input_tokens or 0), u.output_tokens)
            if msg.stop_reason == "refusal":
                raise LLMError(f"{call.step}: model declined the request")
            if msg.stop_reason == "max_tokens":
                last_error = "output truncated at max_tokens"
                max_tokens = min(max_tokens * 2, 64000)
                continue
            parsed = getattr(msg, "parsed_output", None)
            if parsed is None:
                last_error = "model returned no structured output"
                continue
            log.info("llm %s ok (attempt %d, usage=%s)", call.step, attempt + 1, msg.usage)
            return parsed
        raise LLMError(f"{call.step}: {last_error} after {attempts} attempts")

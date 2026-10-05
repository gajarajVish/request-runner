"""OpenAI via the Responses API, with schema-validated structured output.

Same contract as the Anthropic implementation: one LLMCall in, one validated pydantic object
out, bounded retries on invalid output, LLMError otherwise. Content blocks arrive in the
Anthropic shape used throughout the app (text, base64 image) and are converted here.
"""

from __future__ import annotations

import logging

import openai
from pydantic import BaseModel, ValidationError

from ..config import get_settings
from .base import LLMCall, LLMError, record_usage

log = logging.getLogger(__name__)


def _convert(blocks: list[dict]) -> list[dict]:
    out = []
    for b in blocks:
        if b["type"] == "text":
            out.append({"type": "input_text", "text": b["text"]})
        elif b["type"] == "image" and b.get("source", {}).get("type") == "base64":
            src = b["source"]
            out.append({"type": "input_image", "image_url": f"data:{src['media_type']};base64,{src['data']}", "detail": "high"})
        else:
            raise LLMError(f"unsupported content block for OpenAI: {b['type']}")
    return out


class OpenAILLM:
    def __init__(self) -> None:
        s = get_settings()
        self.settings = s
        self.client = openai.OpenAI(api_key=s.openai_api_key or None, max_retries=3, timeout=600)

    def run(self, call: LLMCall) -> BaseModel:
        s = self.settings
        strong = call.tier == "strong"
        model = s.openai_strong_model if strong else s.openai_fast_model
        attempts = s.llm_max_retries + 1
        max_tokens = 32000 if strong else 8000
        last_error = "no attempt made"
        for attempt in range(attempts):
            try:
                resp = self.client.responses.parse(
                    model=model,
                    instructions=call.system,
                    input=[{"role": "user", "content": _convert(call.content)}],
                    text_format=call.output,
                    reasoning={"effort": s.openai_reasoning_effort if strong else "low"},
                    max_output_tokens=max_tokens,
                )
            except openai.BadRequestError as e:
                raise LLMError(f"{call.step}: bad request: {e}") from e
            except (ValidationError, ValueError) as e:
                last_error = f"invalid structured output: {e}"
                continue
            except openai.APIError as e:  # rate limits, 5xx, connection; SDK already retried
                raise LLMError(f"{call.step}: API error: {e}") from e
            if resp.usage:
                record_usage(call.step, resp.usage.input_tokens, resp.usage.output_tokens)
            if resp.status == "incomplete":
                reason = getattr(resp.incomplete_details, "reason", "incomplete")
                if reason == "max_output_tokens":
                    last_error = "output truncated at max_output_tokens"
                    max_tokens = min(max_tokens * 2, 64000)
                    continue
                raise LLMError(f"{call.step}: response incomplete ({reason})")
            refusal = next((c.refusal for o in resp.output if o.type == "message" for c in o.content if c.type == "refusal"), None)
            if refusal:
                raise LLMError(f"{call.step}: model declined the request")
            parsed = resp.output_parsed
            if parsed is None:
                last_error = "model returned no structured output"
                continue
            log.info("llm %s ok via %s (attempt %d, usage=%s)", call.step, model, attempt + 1, resp.usage)
            return parsed
        raise LLMError(f"{call.step}: {last_error} after {attempts} attempts")

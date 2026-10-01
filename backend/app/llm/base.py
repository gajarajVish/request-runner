"""Provider-neutral LLM interface.

Workflow code builds an `LLMCall` (system prompt, content blocks, output schema) and gets back
a validated pydantic object. `context` carries structured inputs that are not sent to the
model; fakes use it to produce deterministic outputs in tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LLMError(Exception):
    """The model call failed or never produced valid output. Becomes a reviewable error."""


@dataclass
class LLMCall:
    step: str  # scope | scope_row | classify | check | answer_question | chat
    system: str
    content: list[dict[str, Any]]
    output: type[BaseModel]
    tier: Literal["strong", "fast"] = "strong"
    context: dict[str, Any] = field(default_factory=dict)


class LLM(Protocol):
    def run(self, call: LLMCall) -> BaseModel: ...


_llm: LLM | None = None


def get_llm() -> LLM:
    global _llm
    if _llm is None:
        from ..config import get_settings

        if get_settings().llm_provider == "fake":
            from .fake import FakeLLM

            _llm = FakeLLM()
        else:
            from .anthropic_llm import AnthropicLLM

            _llm = AnthropicLLM()
    return _llm


def set_llm(llm: LLM | None) -> None:
    global _llm
    _llm = llm


def run(call: LLMCall, output: type[T]) -> T:
    result = get_llm().run(call)
    if not isinstance(result, output):
        # fakes may return dicts; validate them the same way real output is validated
        result = output.model_validate(result if isinstance(result, dict) else result.model_dump())
    return result

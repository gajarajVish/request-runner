"""Provider-neutral LLM interface.

Workflow code builds an `LLMCall` (system prompt, content blocks, output schema) and gets back
a validated pydantic object. `context` carries structured inputs that are not sent to the
model; fakes use it to produce deterministic outputs in tests.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
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
        elif get_settings().llm_provider == "openai":
            from .openai_llm import OpenAILLM

            _llm = OpenAILLM()
        else:
            from .anthropic_llm import AnthropicLLM

            _llm = AnthropicLLM()
    return _llm


def set_llm(llm: LLM | None) -> None:
    global _llm
    _llm = llm


# --------------------------------------------------------------------------- daily token budget
# Usage is kept per UTC day in DATA_DIR/llm-usage.json so the cap survives restarts. A call
# already in flight can overshoot the cap; the next one is refused.

_usage_lock = threading.Lock()


def _usage_path():
    from ..config import get_settings

    return get_settings().data_dir / "llm-usage.json"


def _load_usage() -> dict[str, Any]:
    try:
        return json.loads(_usage_path().read_text())
    except (OSError, ValueError):
        return {}


def usage_today() -> dict[str, int]:
    day = datetime.now(UTC).date().isoformat()
    with _usage_lock:
        return _load_usage().get(day, {"input": 0, "output": 0, "calls": 0})


def record_usage(step: str, input_tokens: int, output_tokens: int) -> None:
    day = datetime.now(UTC).date().isoformat()
    with _usage_lock:
        data = _load_usage()
        d = data.setdefault(day, {"input": 0, "output": 0, "calls": 0})
        d["input"] += int(input_tokens or 0)
        d["output"] += int(output_tokens or 0)
        d["calls"] += 1
        by_step = d.setdefault("by_step", {})
        by_step[step] = by_step.get(step, 0) + int(input_tokens or 0) + int(output_tokens or 0)
        for old in sorted(data)[:-30]:  # keep 30 days
            del data[old]
        _usage_path().write_text(json.dumps(data, indent=1))


def _check_budget(call: LLMCall) -> None:
    from ..config import get_settings

    cap = get_settings().llm_daily_token_budget
    if cap <= 0:
        return
    u = usage_today()
    if u["input"] + u["output"] >= cap:
        raise LLMError(f"{call.step}: daily LLM token budget reached ({cap:,} tokens); resets at 00:00 UTC")


def run(call: LLMCall, output: type[T]) -> T:
    _check_budget(call)
    result = get_llm().run(call)
    if not isinstance(result, output):
        # fakes may return dicts; validate them the same way real output is validated
        result = output.model_validate(result if isinstance(result, dict) else result.model_dump())
    return result

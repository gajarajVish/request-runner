"""Deterministic stand-in for tests (and LLM_PROVIDER=fake for offline UI work).

Register a handler per step: `fake.on("check", lambda call: {...})`. Without one, each step
returns a conservative default (nothing met, nothing closed, no questions).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from .base import LLMCall

Handler = Callable[[LLMCall], Any]


class FakeLLM:
    def __init__(self) -> None:
        self.handlers: dict[str, Handler] = {}
        self.calls: list[LLMCall] = []

    def on(self, step: str, handler: Handler) -> FakeLLM:
        self.handlers[step] = handler
        return self

    def run(self, call: LLMCall) -> BaseModel:
        self.calls.append(call)
        handler = self.handlers.get(call.step) or getattr(self, f"_default_{call.step}")
        out = handler(call)
        if isinstance(out, BaseModel):
            return out
        return call.output.model_validate(out)

    # ------------------------------------------------------------------ defaults

    def _default_scope(self, call: LLMCall) -> dict:
        return {
            "message_to_requester": "Here is a draft checklist.",
            "clarifying_questions": [],
            "title": call.context.get("comment", "Request")[:60],
            "provider_name": None,
            "provider_email": None,
            "provider_organization": None,
            "due_date": None,
            "items": [],
            "assumptions": [],
            "ready_to_confirm": False,
        }

    def _default_scope_row(self, call: LLMCall) -> dict:
        row = call.context["row"]
        instructions = row.get("instructions", "")
        vague = len(instructions.split()) < 6
        return {
            "title": row.get("title", ""),
            "vague": vague,
            "vague_reason": "too vague to scope" if vague else None,
            "items": []
            if vague
            else [
                {
                    "kind": "answer" if instructions.rstrip().endswith("?") else "document",
                    "description": instructions,
                    "criteria": {
                        "period": None,
                        "entity": None,
                        "format": None,
                        "required_elements": [],
                        "signature": None,
                        "currency_rule": None,
                    },
                    "subpoints": [],
                }
            ],
            "assumptions": [],
        }

    def _default_classify(self, call: LLMCall) -> dict:
        return {
            "substantive": True,
            "closes_request": False,
            "closing_quote": None,
            "closing_refs": [],
            "questions": [],
            "attachment_assignments": [],
            "answered_refs": [],
            "mentions_attachments": False,
            "summary": "reply",
        }

    def _default_check(self, call: LLMCall) -> dict:
        return {
            "items": [
                {
                    "item_key": k,
                    "verdict": "not_met",
                    "rationale": "fake: not assessed",
                    "missing": ["not provided"],
                    "citations": [],
                    "subpoints": [],
                    "needs_review": False,
                    "review_reason": None,
                }
                for k in call.context.get("item_keys", [])
            ],
            "suspicious": [],
            "unreadable": [],
        }

    def _default_answer_question(self, call: LLMCall) -> dict:
        return {"in_scope": False, "answer": None, "basis_item_keys": [], "reason": "fake"}

    def _default_chat(self, call: LLMCall) -> dict:
        return {"reply": "OK.", "proposed_action": "none", "new_due_date": None}

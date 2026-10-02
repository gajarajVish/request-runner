"""Deterministic stand-in for tests (and LLM_PROVIDER=fake for offline UI work).

Register a handler per step: `fake.on("check", lambda call: {...})`. Without one, each step
returns a conservative default (nothing met, nothing closed, no questions).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date
from typing import Any

from pydantic import BaseModel

from .base import LLMCall

Handler = Callable[[LLMCall], Any]

_EMPTY_CRITERIA = {"period": None, "entity": None, "format": None, "required_elements": [], "signature": None, "currency_rule": None}
_MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def _parse_due(text: str, today: str | None) -> str | None:
    """"by Oct 30" / "by October 30, 2026" -> ISO date (next occurrence when no year is given)."""
    m = re.search(r"\bby\s+([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s*(\d{4}))?", text)
    if not m or m.group(1)[:3].lower() not in _MONTHS:
        return None
    t = date.fromisoformat(today) if today else date.today()
    try:
        d = date(int(m.group(3) or t.year), _MONTHS[m.group(1)[:3].lower()], int(m.group(2)))
    except ValueError:
        return None
    if not m.group(3) and d < t:
        d = d.replace(year=d.year + 1)
    return d.isoformat()


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
        """Offline stand-in: keeps the existing draft, otherwise reads the provider's email, name and
        a "by <date>" from the first request message, and makes that request the one item."""
        base = call.context.get("base")
        if base and (base.get("items") or base.get("provider_email")):
            return {
                "message_to_requester": "Kept your current checklist (offline mode can't apply changes; edit it directly).",
                "clarifying_questions": [],
                "title": call.context.get("title") or "Request",
                "provider_name": base.get("provider_name"),
                "provider_email": base.get("provider_email"),
                "provider_organization": None,
                "due_date": base.get("due_date"),
                "items": [{k: i[k] for k in ("kind", "description", "criteria", "subpoints")} for i in base.get("items", [])],
                "assumptions": [],
                "ready_to_confirm": bool(base.get("items") and base.get("provider_email")),
            }
        thread = call.context.get("comment", "")
        ask = next((ln.removeprefix("[requester] ").strip() for ln in thread.splitlines() if ln.startswith("[requester] ")), thread.strip())
        email = re.search(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", ask)
        name = re.search(r"from\s+([A-Z][\w.'-]*(?:\s+[A-Z][\w.'-]*)*)\s*\(?\s*[\w.+-]+@", ask)
        due = _parse_due(ask, call.context.get("today"))
        item = re.sub(r"\s*\(?[\w.+-]+@[\w-]+(?:\.[\w-]+)+\)?", "", ask)
        item = re.sub(r"\s+by\s+\w+\.?\s+\d{1,2}(?:st|nd|rd|th)?(?:,?\s*\d{4})?\.?$", "", item, flags=re.I).strip(" .")
        item = re.sub(r"^(?:please\s+)?(?:get|collect|request|ask for)\s+(?:(?:a|an|the)\s+)?", "", item, flags=re.I)
        if name and f" from {name.group(1)}" in item:
            item = item[: item.index(f" from {name.group(1)}")]
        item = item[:1].upper() + item[1:] if item else "Requested document"
        return {
            "message_to_requester": "Offline mode (LLM_PROVIDER=fake): I filled this in from your message without a model. Check it, edit if needed, then confirm.",
            "clarifying_questions": [],
            "title": item[:60],
            "provider_name": name.group(1) if name else None,
            "provider_email": email.group(0).lower() if email else None,
            "provider_organization": None,
            "due_date": due,
            "items": [{"kind": "answer" if ask.rstrip().endswith("?") else "document", "description": item, "criteria": _EMPTY_CRITERIA, "subpoints": []}],
            "assumptions": [],
            "ready_to_confirm": bool(email),
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

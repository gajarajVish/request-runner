"""Builders for fake model outputs."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

from app import clock
from app.db import session_scope
from app.models import Conversation, ConversationRequest, OutboundMessage, Request
from app.workflow import jobs, scoping
from app.workflow.outbox import reply_address

from .conftest import user


def criteria(**kw):
    base = {"period": None, "entity": None, "format": None, "required_elements": [], "signature": None, "currency_rule": None}
    base.update(kw)
    return base


def item(description, kind="document", subpoints=(), **crit):
    return {"kind": kind, "description": description, "criteria": criteria(**crit), "subpoints": list(subpoints)}


def proposal(items, *, email="jordan@example.com", name="Jordan Lee", questions=(), due="2026-10-17", title="Signed MSA and insurance certificate", org="Acme Logistics LLC"):
    return {
        "message_to_requester": "Here's the checklist." if not questions else "A couple of questions first.",
        "clarifying_questions": list(questions),
        "title": title,
        "provider_name": name,
        "provider_email": email,
        "provider_organization": org,
        "due_date": due,
        "items": items,
        "assumptions": [],
        "ready_to_confirm": not questions,
    }


MSA_ITEMS = [
    item(
        "Current certificate of insurance for Acme Logistics LLC (policy period covering today)",
        entity="Acme Logistics LLC",
        currency_rule="policy period includes today",
    ),
    item(
        "The 2025 Amended and Restated MSA between Alder & Finch Co. and Acme Logistics LLC, signed by both parties",
        signature={"required": True, "mode": "named_parties", "parties": ["Alder & Finch Co.", "Acme Logistics LLC"], "date_required": False},
    ),
]


def check_out(items, suspicious=(), unreadable=()):
    return {"items": items, "suspicious": list(suspicious), "unreadable": list(unreadable)}


def cite(evidence_id, quote=None, page=None, sheet=None, cell_range=None, visual=False, note=None):
    return {
        "evidence_id": evidence_id,
        "page": page,
        "sheet": sheet,
        "cell_range": cell_range,
        "paragraph": None,
        "table": None,
        "row": None,
        "quote": quote,
        "visual": visual,
        "note": note,
    }


def verdict(key, v, citations=(), missing=(), subpoints=(), needs_review=False, rationale="r"):
    return {
        "item_key": key,
        "verdict": v,
        "rationale": rationale,
        "missing": list(missing),
        "citations": list(citations),
        "subpoints": list(subpoints),
        "needs_review": needs_review,
        "review_reason": "unclear" if needs_review else None,
    }


def classify(**kw):
    base = {
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
    base.update(kw)
    return base


def evid(call, filename_part):
    """Find the evidence id for a file in a check call's rendered content."""
    import re

    text = "\n".join(b.get("text", "") for b in call.content if b["type"] == "text")
    for m in re.finditer(r'<evidence id="(E\d+)" file="([^"]*)"', text):
        if filename_part in m.group(2):
            return m.group(1)
    raise AssertionError(f"{filename_part} not in evidence: {text[:500]}")


def run_jobs(advance_seconds: int = 0):
    if advance_seconds:
        clock.set_fixed(clock._fixed + timedelta(seconds=advance_seconds))
    return jobs.run_until_idle()


def confirmed_request(env, items=MSA_ITEMS, *, send=True, **prop_kw) -> int:
    """Comment -> fake scope -> confirm -> send. Returns the request id."""
    env.llm.on("scope", lambda call: proposal(items, **prop_kw))
    with session_scope() as s:
        req = scoping.create_from_comment(s, user(s), "Get the signed MSA and the latest insurance certificate from our vendor Jordan Lee.")
        rid = req.id
    run_jobs()
    with session_scope() as s:
        req = s.get(Request, rid)
        v = scoping.latest_proposed(s, req)
        scoping.confirm(s, user(s), req, v.id)
    if send:
        with session_scope() as s:
            req = s.get(Request, rid)
            draft = s.scalars(select(OutboundMessage).where(OutboundMessage.request_id == rid, OutboundMessage.status == "draft")).one()
            scoping.send_draft(s, user(s), req, draft.id)
        run_jobs()
    return rid


def reply_to_of(rid) -> tuple[str, str]:
    """(Reply-To address, last outbound Message-ID) for a request's conversation."""
    with session_scope() as s:
        conv_id = s.scalars(select(ConversationRequest.conversation_id).where(ConversationRequest.request_id == rid).order_by(ConversationRequest.id.desc())).first()
        conv = s.get(Conversation, conv_id)
        msg = s.scalars(select(OutboundMessage).where(OutboundMessage.conversation_id == conv.id).order_by(OutboundMessage.id.desc())).first()
        return reply_address(conv.reply_token), msg.message_id

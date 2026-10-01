"""JSON shapes for the frontend."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .. import clock
from ..config import get_settings
from ..models import (
    AuditLog,
    Check,
    ChecklistVersion,
    Comment,
    Conversation,
    ConversationRequest,
    EvidenceAssignment,
    EvidenceFile,
    InboundMessage,
    OutboundMessage,
    ProviderQuestion,
    Request,
)
from ..workflow import states
from ..workflow.common import dependencies, effective_verdicts, latest_proposed, request_label
from ..workflow.outbox import messages_for_request


def iso(v: datetime | date | None) -> str | None:
    return v.isoformat() if v else None


def version(v: ChecklistVersion | None, verdicts: dict[str, Any] | None = None) -> dict[str, Any] | None:
    if v is None:
        return None
    return {
        "id": v.id,
        "number": v.number,
        "status": v.status,
        "provider_email": v.provider_email,
        "provider_name": v.provider_name,
        "due_date": iso(v.due_date),
        "notes": v.notes,
        "created_by": v.created_by,
        "created_at": iso(v.created_at),
        "confirmed_at": iso(v.confirmed_at),
        "items": [
            {
                "key": i.key,
                "kind": i.kind,
                "description": i.description,
                "criteria": i.criteria,
                "subpoints": i.subpoints,
                **({"verdict": verdicts.get(i.key)} if verdicts is not None else {}),
            }
            for i in v.items
        ],
    }


def file(f: EvidenceFile, method: str | None = None) -> dict[str, Any]:
    ex = f.extraction or {}
    return {
        "id": f.id,
        "filename": f.filename,
        "kind": f.kind,
        "source": f.source,
        "status": f.extraction_status,
        "reason": f.unreadable_reason or f.rejection_reason,
        "accepted": f.accepted,
        "detected_type": f.detected_type,
        "size": f.size,
        "flags": f.flags,
        "created_at": iso(f.created_at),
        "parent_file_id": f.parent_file_id,
        "inbound_id": f.inbound_id,
        "assigned": method,
        "text": ex.get("segments", [{}])[0].get("text") if f.kind == "text" and ex.get("segments") else None,
        "images": [{"index": n, "label": im["label"], "why": im.get("why")} for n, im in enumerate(ex.get("images", []))],
        "pages": (ex.get("meta") or {}).get("pages"),
    }


def outbound(m: OutboundMessage) -> dict[str, Any]:
    return {
        "id": m.id,
        "kind": m.kind,
        "status": m.status,
        "from": f'"{m.from_name}" <{m.from_address}>',
        "reply_to": m.reply_to,
        "to": m.to,
        "cc": m.cc,
        "subject": m.subject,
        "text": m.text_body,
        "message_id": m.message_id,
        "in_reply_to": m.in_reply_to,
        "references": m.references,
        "created_at": iso(m.created_at),
        "sent_at": iso(m.sent_at),
        "last_error": m.last_error,
        "request_ids": m.request_ids,
        "counted_request_ids": m.counted_request_ids,
        "attempts": m.attempts,
    }


def inbound(m: InboundMessage, full: bool = False) -> dict[str, Any]:
    return {
        "id": m.id,
        "from": m.from_address,
        "from_name": m.from_name,
        "to": m.to_addresses,
        "subject": m.subject,
        "message_id": m.message_id,
        "in_reply_to": m.in_reply_to,
        "received_at": iso(m.received_at),
        "status": m.status,
        "match_method": m.match_method,
        "match_notes": m.match_notes,
        "suggested_conversation_ids": m.suggested_conversation_ids,
        "is_auto_reply": m.is_auto_reply,
        "sender_is_owner": m.sender_is_owner,
        "text": (m.new_text if not full else m.text_body) or "",
        "classification": m.classification if full else None,
        "error": m.error,
    }


def request_summary(s: Session, r: Request, today: date | None = None) -> dict[str, Any]:
    today = today or clock.local_date(clock.now(s), get_settings().workspace_timezone)
    verdicts = effective_verdicts(s, r)
    met = sum(1 for v in verdicts.values() if v["verdict"] == "met")
    overdue_days = (today - r.due_date).days if r.due_date and r.state not in states.TERMINAL and today > r.due_date else 0
    return {
        "id": r.id,
        "title": r.title,
        "label": request_label(r),
        "external_id": r.external_id,
        "state": r.state,
        "state_label": states.LABELS.get(r.state, r.state),
        "origin": r.origin,
        "due_date": iso(r.due_date),
        "overdue_days": overdue_days,
        "owners": [{"provider_id": o.provider_id, "email": o.provider.email, "name": o.provider.name, "closed_at": iso(o.closed_at)} for o in r.owners],
        "met": met,
        "total": len(verdicts),
        "auto_contact_count": r.auto_contact_count,
        "flags": r.flags,
        "updated_at": iso(r.updated_at),
        "created_at": iso(r.created_at),
        "import_list_id": r.import_list_id,
    }


def request_detail(s: Session, r: Request) -> dict[str, Any]:
    cfg = get_settings()
    verdicts = effective_verdicts(s, r)
    cur = s.get(ChecklistVersion, r.current_version_id) if r.current_version_id else None
    prop = latest_proposed(s, r)
    assigns = {a.file_id: a.method for a in s.scalars(select(EvidenceAssignment).where(EvidenceAssignment.request_id == r.id))}
    files = [s.get(EvidenceFile, i) for i in sorted(assigns)]
    conv_ids = s.scalars(select(ConversationRequest.conversation_id).where(ConversationRequest.request_id == r.id)).all()
    inbound_rows = s.scalars(select(InboundMessage).where(InboundMessage.conversation_id.in_(conv_ids or [-1])).order_by(InboundMessage.id)).all() if conv_ids else []
    convs = [s.get(Conversation, c) for c in conv_ids]
    return {
        **request_summary(s, r),
        "aliases": r.aliases,
        "instructions": r.instructions,
        "backup_email": r.backup_email,
        "ownership_mode": r.ownership_mode,
        "cc_requester": r.cc_requester,
        "max_auto_contacts": cfg.max_auto_contacts,
        "handback_reason": r.handback_reason,
        "handed_back_at": iso(r.handed_back_at),
        "reminder_sent_at": iso(r.reminder_sent_at),
        "overdue_sent_at": iso(r.overdue_sent_at),
        "escalated_at": iso(r.escalated_at),
        "dependencies": [{"id": d.id, "label": request_label(d), "state": d.state} for d in dependencies(s, r)],
        "current_version": version(cur, verdicts),
        "proposed_version": version(prop) if prop and (cur is None or prop.number > cur.number) else None,
        "versions": [{"id": v.id, "number": v.number, "status": v.status, "created_at": iso(v.created_at), "confirmed_at": iso(v.confirmed_at)} for v in r.versions],
        "comments": [
            {"id": c.id, "author": c.author, "kind": c.kind, "body": c.body, "payload": c.payload, "created_at": iso(c.created_at)}
            for c in s.scalars(select(Comment).where(Comment.request_id == r.id).order_by(Comment.id))
        ],
        "files": [file(f, assigns.get(f.id)) for f in files if f is not None],
        "messages": [outbound(m) for m in messages_for_request(s, r)],
        "inbound": [inbound(m) for m in inbound_rows],
        "conversations": [{"id": c.id, "reply_to": f"{cfg.email_inbound_prefix}+{c.reply_token}@{cfg.email_inbound_domain}", "subject": c.subject} for c in convs if c],
        "questions": [
            {"id": q.id, "question": q.question, "status": q.status, "answer": q.answer, "created_at": iso(q.created_at), "delivered_at": iso(q.delivered_at)}
            for q in s.scalars(select(ProviderQuestion).where(ProviderQuestion.request_id == r.id).order_by(ProviderQuestion.id))
        ],
        "checks": [
            {"id": c.id, "status": c.status, "trigger": c.trigger, "error": c.error, "suspicious": c.suspicious, "created_at": iso(c.created_at), "finished_at": iso(c.finished_at)}
            for c in s.scalars(select(Check).where(Check.request_id == r.id).order_by(Check.id.desc()).limit(10))
        ],
        "audit": [
            {"id": a.id, "at": iso(a.at), "actor": a.actor, "actor_detail": a.actor_detail, "action": a.action, "detail": a.detail}
            for a in s.scalars(select(AuditLog).where(or_(AuditLog.request_id == r.id)).order_by(AuditLog.id.desc()).limit(300))
        ],
    }

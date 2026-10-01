"""Durable outbox.

A message row is written in the same transaction as the decision to send it (and the
follow-up counter reservation). A separate job delivers it. Idempotency keys make every
decision send at most one message. Delivery outcomes:

- retry: requeued with backoff (provider definitely didn't accept it)
- uncertain: we can't know if the provider accepted it (e.g. timeout after the request was
  sent). Never resent automatically; shown to the requester, who can resend.
- A row found in 'sending' state after a crash is also treated as uncertain.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .. import audit, clock
from ..config import get_settings
from ..db import session_scope
from ..email.adapters import OutgoingEmail, get_sender
from ..models import Conversation, InboundMessage, OutboundMessage, Provider, Request
from . import jobs
from .common import add_comment

COUNTED_KINDS = {"followup", "reminder", "overdue", "change_notice"}
MAX_SEND_ATTEMPTS = 5


def reply_address(token: str) -> str:
    s = get_settings()
    return f"{s.email_inbound_prefix}+{token}@{s.email_inbound_domain}"


def new_message_id() -> str:
    domain = get_settings().email_from_address.split("@")[-1]
    return f"<rr.{uuid.uuid4().hex}@{domain}>"


def thread_headers(session: Session, conv: Conversation) -> tuple[str | None, str | None, str]:
    """(In-Reply-To, References, subject) to continue a conversation in the provider's inbox."""
    out = session.scalars(
        select(OutboundMessage)
        .where(OutboundMessage.conversation_id == conv.id, OutboundMessage.status.in_(["sent", "queued", "sending", "uncertain"]))
        .order_by(OutboundMessage.id)
    ).all()
    inbound = session.scalars(
        select(InboundMessage).where(InboundMessage.conversation_id == conv.id, InboundMessage.message_id.is_not(None)).order_by(InboundMessage.id)
    ).all()
    chain = sorted(
        [(m.sent_at or m.created_at, m.message_id) for m in out] + [(m.received_at, m.message_id) for m in inbound],
        key=lambda t: t[0],
    )
    ids = list(dict.fromkeys(mid for _, mid in chain if mid))
    if not ids:
        return None, None, conv.subject
    subject = conv.subject if conv.subject.lower().startswith("re:") else f"Re: {conv.subject}"
    return ids[-1], " ".join(ids[-20:]), subject


def queue_message(
    session: Session,
    *,
    workspace_id: int,
    kind: str,
    idempotency_key: str,
    to: list[str],
    subject: str,
    text: str,
    from_name: str,
    cc: list[str] | None = None,
    reply_to: str | None = None,
    conversation: Conversation | None = None,
    request_id: int | None = None,
    request_ids: list[int] | None = None,
    counted_request_ids: list[int] | None = None,
    in_reply_to: str | None = None,
    references: str | None = None,
    draft: bool = False,
    message_id: str | None = None,
) -> OutboundMessage | None:
    existing = session.scalars(select(OutboundMessage).where(OutboundMessage.idempotency_key == idempotency_key)).first()
    if existing is not None:
        return existing
    counted: list[int] = []
    if kind in COUNTED_KINDS:
        limit = get_settings().max_auto_contacts
        for rid in counted_request_ids or []:
            req = session.get(Request, rid)
            if req is not None and req.auto_contact_count < limit:
                req.auto_contact_count += 1  # reserved in this transaction
                counted.append(rid)
        if counted_request_ids and not counted:
            return None
    now = clock.now(session)
    msg = OutboundMessage(
        workspace_id=workspace_id,
        conversation_id=conversation.id if conversation else None,
        request_id=request_id,
        kind=kind,
        idempotency_key=idempotency_key,
        from_name=from_name,
        from_address=get_settings().email_from_address,
        reply_to=reply_to,
        to=to,
        cc=cc or [],
        subject=subject,
        text_body=text,
        message_id=message_id or new_message_id(),
        in_reply_to=in_reply_to,
        references=references,
        status="draft" if draft else "queued",
        request_ids=request_ids or ([request_id] if request_id else []),
        counted_request_ids=counted,
        created_at=now,
    )
    session.add(msg)
    session.flush()
    audit.log(
        session,
        actor="agent",
        action="email_drafted" if draft else "email_queued",
        workspace_id=workspace_id,
        request_id=request_id,
        message=msg.id,
        kind=kind,
        to=to,
        subject=subject,
        counted_request_ids=counted,
    )
    if not draft:
        jobs.enqueue(session, "send_email", f"send:{msg.id}", {"id": msg.id})
    return msg


def release(session: Session, msg: OutboundMessage, *, actor: str = "requester", actor_detail: str | None = None) -> None:
    if msg.status != "draft":
        return
    msg.status = "queued"
    audit.log(session, actor=actor, actor_detail=actor_detail, action="email_approved", workspace_id=msg.workspace_id, request_id=msg.request_id, message=msg.id)
    jobs.enqueue(session, "send_email", f"send:{msg.id}", {"id": msg.id})


@jobs.handler("send_email")
def send_job(payload: dict) -> None:
    msg_id = payload["id"]
    with session_scope() as s:
        msg = s.get(OutboundMessage, msg_id)
        if msg is None or msg.status in ("sent", "failed", "uncertain", "cancelled", "draft"):
            return
        if msg.status == "sending":
            # a previous attempt crashed after handing the message to the provider (maybe)
            msg.status = "uncertain"
            msg.last_error = "interrupted during send; delivery unknown"
            _notify_uncertain(s, msg)
            return
        msg.status = "sending"
        msg.attempts += 1
        email = OutgoingEmail(
            from_name=msg.from_name,
            from_address=msg.from_address,
            to=list(msg.to),
            cc=list(msg.cc),
            reply_to=msg.reply_to,
            subject=msg.subject,
            text=msg.text_body,
            message_id=msg.message_id,
            in_reply_to=msg.in_reply_to,
            references=msg.references,
            idempotency_key=msg.idempotency_key,
        )
    result = get_sender().send(email)
    with session_scope() as s:
        msg = s.get(OutboundMessage, msg_id)
        assert msg is not None
        now = clock.now(s)
        if result.outcome == "sent":
            msg.status = "sent"
            msg.sent_at = now
            msg.provider_message_id = result.provider_message_id
            msg.last_error = None
            _on_sent(s, msg)
        elif result.outcome == "retry" and msg.attempts < MAX_SEND_ATTEMPTS:
            msg.status = "queued"
            msg.last_error = result.error
            jobs.enqueue(s, "send_email", f"send:{msg.id}:retry{msg.attempts}", {"id": msg.id}, now + timedelta(seconds=30 * msg.attempts))
        elif result.outcome == "uncertain":
            msg.status = "uncertain"
            msg.last_error = result.error
            _notify_uncertain(s, msg)
        else:
            msg.status = "failed"
            msg.last_error = result.error
            audit.log(s, actor="system", action="email_failed", workspace_id=msg.workspace_id, request_id=msg.request_id, message=msg.id, error=result.error)
            for rid in msg.request_ids:
                req = s.get(Request, rid)
                if req:
                    add_comment(s, req, author="system", kind="email_failed", body=f"Email could not be sent: {result.error}", payload={"message_id": msg.id})


def _notify_uncertain(s: Session, msg: OutboundMessage) -> None:
    audit.log(s, actor="system", action="email_uncertain", workspace_id=msg.workspace_id, request_id=msg.request_id, message=msg.id, error=msg.last_error)
    for rid in msg.request_ids:
        req = s.get(Request, rid)
        if req:
            add_comment(
                s,
                req,
                author="system",
                kind="email_uncertain",
                body="We couldn't confirm this email was delivered, so it was not resent automatically. Check the provider's inbox or resend it.",
                payload={"message_id": msg.id},
            )


def _on_sent(s: Session, msg: OutboundMessage) -> None:
    audit.log(
        s,
        actor="agent",
        action="email_sent",
        workspace_id=msg.workspace_id,
        request_id=msg.request_id,
        message=msg.id,
        kind=msg.kind,
        to=msg.to,
        message_id=msg.message_id,
    )
    if msg.conversation_id and msg.kind in COUNTED_KINDS | {"answer", "initial"}:
        conv = s.get(Conversation, msg.conversation_id)
        if conv:
            prov = s.get(Provider, conv.provider_id)
            if prov and msg.kind in COUNTED_KINDS:
                prov.last_auto_contact_at = msg.sent_at
    for rid in msg.request_ids:
        req = s.get(Request, rid)
        if req:
            add_comment(
                s,
                req,
                author="agent",
                kind="email_sent",
                body=f"Sent {msg.kind.replace('_', ' ')} to {', '.join(msg.to)}: “{msg.subject}”",
                payload={"message_id": msg.id, "kind": msg.kind},
            )


def resend(session: Session, msg: OutboundMessage, *, actor_detail: str) -> OutboundMessage:
    """Requester-initiated resend of an uncertain/failed message, as a new row (same thread)."""
    clone = queue_message(
        session,
        workspace_id=msg.workspace_id,
        kind=msg.kind if msg.kind not in COUNTED_KINDS else "manual_followup",
        idempotency_key=f"{msg.idempotency_key}:resend:{uuid.uuid4().hex[:8]}",
        to=list(msg.to),
        cc=list(msg.cc),
        subject=msg.subject,
        text=msg.text_body,
        from_name=msg.from_name,
        reply_to=msg.reply_to,
        conversation=session.get(Conversation, msg.conversation_id) if msg.conversation_id else None,
        request_id=msg.request_id,
        request_ids=list(msg.request_ids),
        in_reply_to=msg.in_reply_to,
        references=msg.references,
    )
    assert clone is not None
    audit.log(session, actor="requester", actor_detail=actor_detail, action="email_resent", workspace_id=msg.workspace_id, request_id=msg.request_id, original=msg.id, message=clone.id)
    return clone


def messages_for_request(session: Session, req: Request) -> list[OutboundMessage]:
    rows = session.scalars(
        select(OutboundMessage).where(or_(OutboundMessage.request_id == req.id)).order_by(OutboundMessage.id)
    ).all()
    extra = [
        m
        for m in session.scalars(
            select(OutboundMessage).where(OutboundMessage.workspace_id == req.workspace_id).order_by(OutboundMessage.id)
        ).all()
        if req.id in (m.request_ids or []) and m not in rows
    ]
    return sorted([*rows, *extra], key=lambda m: m.id)

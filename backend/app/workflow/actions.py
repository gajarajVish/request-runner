"""Requester actions on an existing request (each logged with who did it)."""

from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from .. import audit, clock
from ..models import ChecklistVersion, OutboundMessage, Request, User, VerdictOverride
from . import emails, outbox, states
from .checking import decide, enqueue_check
from .common import add_comment, current_version, request_label
from .followups import _thread_for, queue_change_notice
from .handback import hand_back

VERDICTS = {"met", "partly_met", "not_met", "unreadable"}


class ActionError(Exception):
    pass


def cancel(s: Session, user: User, req: Request, reason: str = "") -> None:
    if req.state in states.TERMINAL:
        raise ActionError(f"request is already {req.state}")
    was_sent = req.state in states.OPEN_WITH_PROVIDER
    states.transition(s, req, states.CANCELLED, actor="requester", reason=reason or "cancelled", actor_detail=user.email)
    for m in s.query(OutboundMessage).filter(OutboundMessage.request_id == req.id, OutboundMessage.status == "draft"):
        m.status = "cancelled"
    if was_sent:
        for o in req.owners:
            conv = _thread_for(s, o.provider, [req])
            irt, refs, subject = outbox.thread_headers(s, conv)
            outbox.queue_message(
                s,
                workspace_id=req.workspace_id,
                kind="closed_notice",
                idempotency_key=f"cancel:{req.id}:{o.provider_id}",
                to=[o.provider.email],
                subject=subject,
                text=emails.closed_notice(user, o.provider.name, o.provider.email, [request_label(req)], "the request was cancelled"),
                from_name=emails.from_name(user),
                reply_to=outbox.reply_address(conv.reply_token),
                conversation=conv,
                request_id=req.id,
                in_reply_to=irt,
                references=refs,
            )
    hand_back(s, req, reason="cancelled")


def accept(s: Session, user: User, req: Request, note: str = "") -> None:
    if req.state not in states.OPEN_WITH_PROVIDER:
        raise ActionError(f"can't accept a request that is {req.state}")
    states.transition(s, req, states.ACCEPTED, actor="requester", reason=note or "accepted as is", actor_detail=user.email)
    hand_back(s, req, reason="accepted")


def override(s: Session, user: User, req: Request, item_key: str, verdict: str, reason: str) -> None:
    if verdict not in VERDICTS:
        raise ActionError("bad verdict")
    if not reason.strip():
        raise ActionError("an override needs a reason")
    v = current_version(s, req)
    if v is None or item_key not in {i.key for i in v.items}:
        raise ActionError("unknown item")
    s.add(VerdictOverride(request_id=req.id, version_id=v.id, item_key=item_key, verdict=verdict, reason=reason, user_id=user.id, created_at=clock.now(s)))
    s.flush()
    audit.log(s, actor="requester", actor_detail=user.email, action="verdict_overridden", workspace_id=req.workspace_id, request_id=req.id, item=item_key, verdict=verdict, reason=reason)
    add_comment(s, req, author="requester", user_id=user.id, kind="override", body=f"Marked item {item_key} as {verdict.replace('_', ' ')}: {reason}")
    if req.state in states.OPEN_WITH_PROVIDER:
        decide(s, req, substantive=False)


def retry_check(s: Session, user: User, req: Request) -> None:
    if req.state not in states.OPEN_WITH_PROVIDER:
        raise ActionError("nothing to check")
    audit.log(s, actor="requester", actor_detail=user.email, action="recheck_requested", workspace_id=req.workspace_id, request_id=req.id)
    enqueue_check(s, req, trigger="requester retry", substantive=False)


def change_due_date(s: Session, user: User, req: Request, new_due: date) -> None:
    if req.state in states.TERMINAL:
        raise ActionError("request is closed")
    old = req.due_date
    if old == new_due:
        return
    req.due_date = new_due
    reset_due_tracking(s, req)
    audit.log(s, actor="requester", actor_detail=user.email, action="due_date_changed", workspace_id=req.workspace_id, request_id=req.id, old=str(old), new=str(new_due))
    add_comment(s, req, author="requester", user_id=user.id, kind="note", body=f"Due date changed from {old or 'none'} to {new_due}.")
    if req.state in states.OPEN_WITH_PROVIDER:
        queue_change_notice(s, req, [f"New due date: {new_due:%b %-d, %Y} (was {old:%b %-d, %Y})" if old else f"Due date: {new_due:%b %-d, %Y}"], key=f"due:{req.id}:{new_due}")


def reset_due_tracking(s: Session, req: Request) -> None:
    """A new due date starts a new reminder/overdue/escalation cycle."""
    today = clock.local_date(clock.now(s), "UTC")
    if req.due_date and req.due_date >= today:
        req.reminder_sent_at = None
        req.overdue_sent_at = None
        req.escalated_at = None


def resend(s: Session, user: User, msg: OutboundMessage) -> OutboundMessage:
    if msg.status not in ("uncertain", "failed"):
        raise ActionError("only uncertain or failed messages can be resent")
    return outbox.resend(s, msg, actor_detail=user.email)


def resume(s: Session, user: User, req: Request) -> None:
    """After a handback, the requester can let the agent keep waiting (no more automatic follow-ups)."""
    if req.state != states.HANDED_BACK:
        raise ActionError("request isn't handed back")
    states.transition(s, req, states.NEEDS_MORE, actor="requester", reason="requester resumed waiting", actor_detail=user.email)


def version_items(v: ChecklistVersion) -> list[dict]:
    return [{"key": i.key, "kind": i.kind, "description": i.description, "criteria": i.criteria, "subpoints": i.subpoints} for i in v.items]

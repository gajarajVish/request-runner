"""Follow-ups, reminders, overdue notices, change notices and escalation.

Counting rule (README "Follow-up limits"): each request has one automatic-contact counter.
The initial email doesn't count. Reminders, deficiency follow-ups, overdue notices and change
notices that name the request each count once per message, reserved in the same transaction
that writes the outbox row. Retries and duplicate processing reuse the same outbox row, so
they never count twice. At the limit, the request is handed back to the requester.

Batching: one message per (provider, requester) per cycle. A request appears in at most one
section of that message (overdue > still-missing > due-soon).

Escalation to the backup owner is a separate message type, sent at most once per escalation
cycle (a new due date starts a new cycle) and never to the provider, so it can't become a
way around the provider follow-up limit.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit, clock
from ..config import get_settings
from ..db import session_scope
from ..models import Conversation, ConversationRequest, EvidenceAssignment, EvidenceFile, Provider, ProviderQuestion, Request, RequestOwner, User
from . import emails, hub, jobs, outbox, states
from .common import add_comment, effective_verdicts, request_label

ACTIVE = {states.WAITING_PROVIDER, states.NEEDS_MORE}


def schedule_provider_cycle(s: Session, req: Request, at: datetime, *, immediate: bool = False) -> None:
    run_at = clock.now(s) if immediate else at
    for o in req.owners:
        if o.closed_at is None:
            jobs.enqueue(s, "provider_cycle", f"cycle:{o.provider_id}", {"provider_id": o.provider_id}, run_at, coalesce=True)


def enqueue_sweep(s: Session) -> None:
    now = clock.now(s)
    jobs.enqueue(s, "sweep", f"sweep:{now.strftime('%Y%m%d%H%M')}", {}, now)


def _missing_entries(s: Session, req: Request) -> list[str]:
    out = []
    for v in effective_verdicts(s, req).values():
        if v["verdict"] != "met":
            out += v.get("missing") or []
    return out[:8]


def _entry(s: Session, req: Request, with_missing: bool) -> dict[str, Any]:
    missing = _missing_entries(s, req) if with_missing else []
    if not missing and with_missing:
        missing = ["not received yet"]
    return {"label": request_label(req), "due": req.due_date, "missing": missing, "request_id": req.id}


def _received_summary(s: Session, reqs: list[Request], since: datetime | None) -> str | None:
    ids = s.scalars(select(EvidenceAssignment.file_id).where(EvidenceAssignment.request_id.in_([r.id for r in reqs]))).all()
    files = [s.get(EvidenceFile, i) for i in set(ids)]
    names = sorted({f.filename for f in files if f and f.kind == "file" and f.parent_file_id is None and (since is None or f.created_at >= since)})
    if not names:
        return None
    return ", ".join(names[:6]) + (f" and {len(names) - 6} more" if len(names) > 6 else "")


def _thread_for(s: Session, provider: Provider, reqs: list[Request]) -> Conversation:
    """The provider's most recent conversation that includes any of these requests."""
    rids = [r.id for r in reqs]
    conv = s.scalars(
        select(Conversation)
        .join(ConversationRequest, ConversationRequest.conversation_id == Conversation.id)
        .where(Conversation.provider_id == provider.id, ConversationRequest.request_id.in_(rids))
        .order_by(Conversation.id.desc())
    ).first()
    if conv is None:  # e.g. a second owner who has no thread yet
        import secrets

        u = s.get(User, reqs[0].requester_id)
        conv = Conversation(
            workspace_id=provider.workspace_id,
            provider_id=provider.id,
            reply_token=secrets.token_urlsafe(12),
            subject=emails.batch_subject(u, len(reqs)) if u else "Requested items",
            created_at=clock.now(s),
        )
        s.add(conv)
        s.flush()
    linked = set(s.scalars(select(ConversationRequest.request_id).where(ConversationRequest.conversation_id == conv.id)).all())
    for r in reqs:
        if r.id not in linked:
            conv.links.append(ConversationRequest(request_id=r.id, version_id=r.current_version_id))
    s.flush()
    return conv


@jobs.handler("provider_cycle")
def provider_cycle_job(payload: dict) -> None:
    with session_scope() as s:
        provider = s.get(Provider, payload["provider_id"])
        if provider is None:
            return
        run_provider_cycle(s, provider)


def run_provider_cycle(s: Session, provider: Provider) -> None:
    cfg = get_settings()
    now = clock.now(s)
    today = clock.local_date(now, cfg.workspace_timezone)
    owners = s.scalars(select(RequestOwner).where(RequestOwner.provider_id == provider.id, RequestOwner.closed_at.is_(None))).all()
    reqs = [o.request for o in owners if o.request.workspace_id == provider.workspace_id]

    answers = s.scalars(
        select(ProviderQuestion).where(
            ProviderQuestion.request_id.in_([r.id for r in reqs] or [-1]),
            ProviderQuestion.status.in_(["answered_from_scope", "answered_by_requester"]),
            ProviderQuestion.delivered_at.is_(None),
        )
    ).all()
    answers = [a for a in answers if a.provider_id in (None, provider.id)]

    sections: dict[int, dict[str, list]] = defaultdict(lambda: {"overdue": [], "outstanding": [], "due_soon": [], "answers": [], "limit": []})
    for r in reqs:
        if r.state not in ACTIVE or r.handed_back_at is not None and r.state == states.HANDED_BACK:
            continue
        sec = sections[r.requester_id]
        cat = None
        if r.due_date and r.overdue_sent_at is None and today >= r.due_date + timedelta(days=cfg.overdue_notice_days_after_due):
            cat = "overdue"
        elif r.state == states.NEEDS_MORE and r.followup_due_at and r.followup_due_at <= now:
            cat = "outstanding"
        elif (
            r.due_date
            and r.reminder_sent_at is None
            and r.due_date - timedelta(days=cfg.reminder_days_before_due) <= today <= r.due_date
        ):
            cat = "due_soon"
        if cat is None:
            continue
        if r.auto_contact_count >= cfg.max_auto_contacts:
            sec["limit"].append(r)
            continue
        sec[cat].append(r)
    for a in answers:
        r = s.get(Request, a.request_id)
        if r is not None:
            sections[r.requester_id]["answers"].append(a)

    # Don't contact the same provider twice in a short window (answers to questions are exempt).
    gap = timedelta(seconds=cfg.provider_min_gap_seconds)
    has_counted = any(sec["overdue"] or sec["outstanding"] or sec["due_soon"] for sec in sections.values())
    if has_counted and provider.last_auto_contact_at and now - provider.last_auto_contact_at < gap:
        jobs.enqueue(s, "provider_cycle", f"cycle:{provider.id}", {"provider_id": provider.id}, provider.last_auto_contact_at + gap, coalesce=True)
        return

    from .handback import hand_back

    for requester_id, sec in sections.items():
        for r in sec["limit"]:
            if r.state in ACTIVE:
                states.transition(s, r, states.HANDED_BACK, actor="agent", reason="follow-up limit reached")
                hand_back(s, r, reason="follow_up_limit")
        counted = sec["overdue"] + sec["outstanding"] + sec["due_soon"]
        if not counted and not sec["answers"]:
            continue
        user = s.get(User, requester_id)
        assert user is not None
        involved = counted + [s.get(Request, a.request_id) for a in sec["answers"]]
        involved = list({r.id: r for r in involved if r is not None}.values())
        conv = _thread_for(s, provider, involved)
        in_reply_to, references, subject = outbox.thread_headers(s, conv)
        link = hub.hub_url(hub.issue_token(s, provider)) if counted else ""
        last_contact = provider.last_auto_contact_at
        text = emails.provider_update(
            requester=user,
            provider_name=provider.name,
            provider_email=provider.email,
            hub_link=link,
            answers=[{"question": a.question, "answer": a.answer or ""} for a in sec["answers"]],
            outstanding=[_entry(s, r, True) for r in sec["outstanding"]],
            overdue=[_entry(s, r, True) for r in sec["overdue"]],
            due_soon=[_entry(s, r, False) for r in sec["due_soon"]],
            received_summary=_received_summary(s, sec["outstanding"], last_contact) if sec["outstanding"] else None,
        )
        kind = "overdue" if sec["overdue"] else "followup" if sec["outstanding"] else "reminder" if sec["due_soon"] else "answer"
        sig = ",".join(f"{r.id}.{r.auto_contact_count}" for r in sorted(counted, key=lambda r: r.id)) + "|" + ",".join(str(a.id) for a in sec["answers"])
        key = f"cycle:{provider.id}:{requester_id}:{hashlib.sha256(sig.encode()).hexdigest()[:16]}"
        msg = outbox.queue_message(
            s,
            workspace_id=provider.workspace_id,
            kind=kind,
            idempotency_key=key,
            to=[provider.email],
            subject=subject,
            text=text,
            from_name=emails.from_name(user),
            reply_to=outbox.reply_address(conv.reply_token),
            conversation=conv,
            request_id=involved[0].id if len(involved) == 1 else None,
            request_ids=[r.id for r in involved],
            counted_request_ids=[r.id for r in counted],
            in_reply_to=in_reply_to,
            references=references,
        )
        if msg is None:
            continue
        for r in sec["overdue"]:
            r.overdue_sent_at = now
            r.reminder_sent_at = r.reminder_sent_at or now
            add_comment(s, r, author="agent", kind="note", body=f"{request_label(r)} is overdue; the provider was notified.")
        for r in sec["outstanding"]:
            r.followup_due_at = None
        for r in sec["due_soon"]:
            r.reminder_sent_at = now
        for r in counted:
            if r.due_date and today >= r.due_date - timedelta(days=cfg.reminder_days_before_due):
                r.reminder_sent_at = r.reminder_sent_at or now
        for a in sec["answers"]:
            a.delivered_at = now


# --------------------------------------------------------------------------- change notices


def queue_change_notice(s: Session, req: Request, lines: list[str], *, key: str) -> None:
    """Tell each open owner about a confirmed change to one request (counts as a contact)."""
    queue_change_notices(s, {req.id: lines}, key=key)


def queue_change_notices(s: Session, changes: dict[int, list[str]], *, key: str) -> None:
    """One consolidated notice per (provider, requester) for a set of confirmed changes."""
    groups: dict[tuple[int, int], list[Request]] = defaultdict(list)
    for rid in changes:
        r = s.get(Request, rid)
        if r is None or r.state not in states.OPEN_WITH_PROVIDER:
            continue
        for o in r.owners:
            if o.closed_at is None:
                groups[(o.provider_id, r.requester_id)].append(r)
    for (pid, uid), reqs in groups.items():
        provider = s.get(Provider, pid)
        user = s.get(User, uid)
        assert provider is not None and user is not None
        conv = _thread_for(s, provider, reqs)
        in_reply_to, references, subject = outbox.thread_headers(s, conv)
        lines = []
        for r in reqs:
            lines.append(request_label(r) + ":")
            lines += [f"   {ln}" for ln in changes[r.id]]
        outbox.queue_message(
            s,
            workspace_id=provider.workspace_id,
            kind="change_notice",
            idempotency_key=f"{key}:p{pid}:u{uid}",
            to=[provider.email],
            subject=subject,
            text=emails.provider_update(
                requester=user,
                provider_name=provider.name,
                provider_email=provider.email,
                hub_link=hub.hub_url(hub.issue_token(s, provider)),
                changes=lines,
            ),
            from_name=emails.from_name(user),
            reply_to=outbox.reply_address(conv.reply_token),
            conversation=conv,
            request_id=reqs[0].id if len(reqs) == 1 else None,
            request_ids=[r.id for r in reqs],
            counted_request_ids=[r.id for r in reqs],
            in_reply_to=in_reply_to,
            references=references,
        )


# --------------------------------------------------------------------------- sweep


@jobs.handler("sweep")
def sweep_job(payload: dict) -> None:
    with session_scope() as s:
        sweep(s)


def sweep(s: Session) -> None:
    cfg = get_settings()
    now = clock.now(s)
    today = clock.local_date(now, cfg.workspace_timezone)
    open_reqs = s.scalars(select(Request).where(Request.state.in_(list(ACTIVE | {states.CHECKING, states.HANDED_BACK})))).all()
    due_providers: set[int] = set()
    for r in open_reqs:
        if r.state in ACTIVE:
            if r.due_date and (
                (r.overdue_sent_at is None and today >= r.due_date + timedelta(days=cfg.overdue_notice_days_after_due))
                or (r.reminder_sent_at is None and r.due_date - timedelta(days=cfg.reminder_days_before_due) <= today <= r.due_date)
            ):
                due_providers.update(o.provider_id for o in r.owners if o.closed_at is None)
            if r.state == states.NEEDS_MORE and r.followup_due_at and r.followup_due_at <= now:
                due_providers.update(o.provider_id for o in r.owners if o.closed_at is None)
        _maybe_escalate(s, r, today)
    for pid in sorted(due_providers):
        jobs.enqueue(s, "provider_cycle", f"cycle:{pid}", {"provider_id": pid}, now, coalesce=False)


def _maybe_escalate(s: Session, r: Request, today) -> None:
    cfg = get_settings()
    if r.escalated_at is not None or r.overdue_sent_at is None or r.state in states.TERMINAL:
        return
    if all(v["verdict"] == "met" for v in effective_verdicts(s, r).values()):
        return
    due_on = clock.add_business_days(clock.local_date(r.overdue_sent_at, cfg.workspace_timezone), cfg.escalation_business_days_after_overdue)
    if today < due_on:
        return
    now = clock.now(s)
    r.escalated_at = now
    user = s.get(User, r.requester_id)
    assert user is not None
    owners = [o.provider for o in r.owners]
    entry = _entry(s, r, True)
    cycle = r.due_date.isoformat() if r.due_date else "nodue"
    if r.backup_email:
        prov = owners[0]
        outbox.queue_message(
            s,
            workspace_id=r.workspace_id,
            kind="escalation",
            idempotency_key=f"escalation:{r.id}:{cycle}",
            to=[r.backup_email],
            subject=f"Overdue: {request_label(r)} (requested by {user.name})",
            text=emails.escalation(requester=user, backup_email=r.backup_email, provider_name=prov.name, provider_email=prov.email, entries=[entry]),
            from_name=emails.from_name(user),
            reply_to=outbox.reply_address(_thread_for(s, prov, [r]).reply_token),
            request_id=r.id,
        )
        note = f"{request_label(r)} is overdue. Escalated to the backup owner {r.backup_email}."
    else:
        note = f"{request_label(r)} is overdue and has no backup owner, so nothing was escalated. You may want to follow up directly."
    add_comment(s, r, author="agent", kind="escalation", body=note)
    audit.log(s, actor="agent", action="escalated", workspace_id=r.workspace_id, request_id=r.id, backup=r.backup_email)
    link = f"{cfg.app_base_url.rstrip('/')}/requests/{r.id}"
    outbox.queue_message(
        s,
        workspace_id=r.workspace_id,
        kind="requester_notice",
        idempotency_key=f"escalation-notice:{r.id}:{cycle}",
        to=[user.email],
        subject=f"[{cfg.app_name}] Overdue: {request_label(r)}",
        text=emails.requester_notice(user, r.title, [note, "", "Still missing:", *[f"  - {m}" for m in entry["missing"]]], link),
        from_name=cfg.app_name,
        request_id=r.id,
    )

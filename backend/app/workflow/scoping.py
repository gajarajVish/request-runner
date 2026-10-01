"""Part 1 front half: comment -> proposed checklist -> requester confirms -> draft -> send."""

from __future__ import annotations

import json
import secrets
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit, clock
from ..config import get_settings
from ..db import session_scope
from ..llm import base as llm
from ..llm import prompts
from ..llm.schemas import DraftItem, ScopeProposal
from ..models import ChecklistItem, ChecklistVersion, Comment, Conversation, ConversationRequest, Request, RequestOwner, User
from . import emails, hub, jobs, outbox, states
from .common import add_comment, current_version, get_or_create_provider, next_version_number


class ScopeError(Exception):
    pass


# --------------------------------------------------------------------------- requester actions


def create_from_comment(session: Session, user: User, text: str) -> Request:
    now = clock.now(session)
    req = Request(workspace_id=user.workspace_id, requester_id=user.id, title="New request", state=states.SCOPING, created_at=now, updated_at=now)
    session.add(req)
    session.flush()
    c = add_comment(session, req, author="requester", body=text, user_id=user.id)
    audit.log(session, actor="requester", actor_detail=user.email, action="request_created", workspace_id=req.workspace_id, request_id=req.id, comment=c.id)
    jobs.enqueue(session, "scope", f"scope:{req.id}:{c.id}", {"request_id": req.id})
    return req


def requester_reply(session: Session, user: User, req: Request, text: str) -> Comment:
    """A requester message in the thread. Before sending it refines scope; after, it's a note
    (or an answer to a pending provider question, handled by the questions module)."""
    c = add_comment(session, req, author="requester", body=text, user_id=user.id)
    audit.log(session, actor="requester", actor_detail=user.email, action="comment", workspace_id=req.workspace_id, request_id=req.id, comment=c.id)
    if req.state in (states.SCOPING, states.WAITING_REQUESTER, states.READY_TO_SEND):
        if req.state != states.SCOPING:
            states.transition(session, req, states.SCOPING, actor="requester", reason="requester replied", actor_detail=user.email)
        jobs.enqueue(session, "scope", f"scope:{req.id}:{c.id}", {"request_id": req.id})
    return c


def request_scope_change(session: Session, user: User, req: Request, text: str) -> Comment:
    """While waiting on the provider: propose a new checklist version from the requester's words."""
    c = add_comment(session, req, author="requester", body=text, user_id=user.id, kind="scope_change_request")
    audit.log(session, actor="requester", actor_detail=user.email, action="scope_change_requested", workspace_id=req.workspace_id, request_id=req.id)
    jobs.enqueue(session, "scope", f"scope:{req.id}:{c.id}", {"request_id": req.id, "amend": True})
    return c


# --------------------------------------------------------------------------- the model step


def _thread_text(session: Session, req: Request) -> str:
    rows = session.scalars(select(Comment).where(Comment.request_id == req.id).order_by(Comment.id)).all()
    lines = []
    for c in rows:
        if c.author == "requester":
            lines.append(f"[requester] {c.body}")
        elif c.kind == "scope_proposal":
            q = c.payload.get("questions") or []
            lines.append(f"[agent] {c.body}" + (f" Questions: {' | '.join(q)}" if q else ""))
        elif c.author == "agent" and c.kind == "message":
            lines.append(f"[agent] {c.body}")
    return "\n".join(lines)


def _checklist_json(version: ChecklistVersion) -> str:
    return json.dumps(
        {
            "provider_name": version.provider_name,
            "provider_email": version.provider_email,
            "due_date": version.due_date.isoformat() if version.due_date else None,
            "items": [{"key": i.key, "kind": i.kind, "description": i.description, "criteria": i.criteria, "subpoints": i.subpoints} for i in version.items],
        },
        indent=1,
    )


def build_scope_call(session: Session, req: Request, requester: User) -> llm.LLMCall:
    today = clock.local_date(clock.now(session), get_settings().workspace_timezone)
    parts = [f"Requester: {requester.name} <{requester.email}>", "<requester_thread>", _thread_text(session, req), "</requester_thread>"]
    cur = current_version(session, req)
    if cur is not None:
        parts += [
            "The checklist below is already confirmed and the provider is working on it. Propose a revised "
            "checklist that applies the requester's latest request and keeps everything else unchanged.",
            "<confirmed_checklist>",
            _checklist_json(cur),
            "</confirmed_checklist>",
        ]
    return llm.LLMCall(
        step="scope",
        system=prompts.SCOPE.format(today=today.isoformat()),
        content=[{"type": "text", "text": "\n".join(parts)}],
        output=ScopeProposal,
        tier="strong",
        context={"request_id": req.id, "comment": _thread_text(session, req)},
    )


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def items_from_drafts(drafts: list[DraftItem], previous: list[ChecklistItem] | None = None) -> list[ChecklistItem]:
    prev_by_desc = {p.description.strip().lower(): p.key for p in previous or []}
    used = set()
    taken = {p.key for p in previous or []}
    out = []
    counter = 1
    for pos, d in enumerate(drafts):
        key = prev_by_desc.get(d.description.strip().lower())
        if key is None or key in used:
            while f"i{counter}" in taken or f"i{counter}" in used:
                counter += 1
            key = f"i{counter}"
        used.add(key)
        out.append(
            ChecklistItem(
                key=key,
                position=pos,
                kind=d.kind,
                description=d.description,
                criteria=d.criteria.model_dump(),
                subpoints=[sp.model_dump() for sp in d.subpoints],
            )
        )
    return out


@jobs.handler("scope")
def scope_job(payload: dict) -> None:
    rid = payload["request_id"]
    with session_scope() as s:
        req = s.get(Request, rid)
        if req is None or req.state in states.TERMINAL:
            return
        requester = s.get(User, req.requester_id)
        assert requester is not None
        call = build_scope_call(s, req, requester)
    try:
        proposal = llm.run(call, ScopeProposal)
    except llm.LLMError as e:
        with session_scope() as s:
            req = s.get(Request, rid)
            assert req is not None
            add_comment(s, req, author="system", kind="error", body=f"The agent couldn't draft a checklist: {e}. Reply to try again.")
            audit.log(s, actor="agent", action="scope_failed", workspace_id=req.workspace_id, request_id=req.id, error=str(e))
            if req.state == states.SCOPING:
                states.transition(s, req, states.WAITING_REQUESTER, actor="system", reason="scoping failed")
        return
    with session_scope() as s:
        req = s.get(Request, rid)
        assert req is not None
        apply_proposal(s, req, proposal, amend=bool(payload.get("amend")))


def apply_proposal(session: Session, req: Request, p: ScopeProposal, *, amend: bool = False) -> ChecklistVersion:
    now = clock.now(session)
    for old in session.scalars(select(ChecklistVersion).where(ChecklistVersion.request_id == req.id, ChecklistVersion.status == "proposed")):
        old.status = "superseded"
    cur = current_version(session, req)
    v = ChecklistVersion(
        request_id=req.id,
        number=next_version_number(session, req),
        status="proposed",
        provider_email=(p.provider_email or (cur.provider_email if cur else None) or None),
        provider_name=p.provider_name or (cur.provider_name if cur else None),
        due_date=_parse_date(p.due_date) or (cur.due_date if cur else None),
        notes=[*p.assumptions, *([f"Provider organization: {p.provider_organization}"] if p.provider_organization else [])],
        created_by="agent",
        created_at=now,
    )
    v.items = items_from_drafts(p.items, cur.items if cur else None)
    session.add(v)
    session.flush()
    if not cur:
        req.title = p.title[:300] or req.title
    ready = p.ready_to_confirm and not p.clarifying_questions and bool(v.items) and bool(v.provider_email)
    add_comment(
        session,
        req,
        author="agent",
        kind="scope_proposal",
        body=p.message_to_requester,
        payload={
            "version_id": v.id,
            "questions": p.clarifying_questions,
            "assumptions": p.assumptions,
            "ready": ready,
            "organization": p.provider_organization,
            "amend": amend,
        },
    )
    audit.log(session, actor="agent", action="checklist_proposed", workspace_id=req.workspace_id, request_id=req.id, version=v.number, items=len(v.items), questions=p.clarifying_questions)
    if req.state == states.SCOPING:
        states.transition(session, req, states.WAITING_REQUESTER, actor="agent", reason="checklist proposed")
    return v


# --------------------------------------------------------------------------- confirm & send


def confirm(session: Session, user: User, req: Request, version_id: int, *, cc_requester: bool = False) -> ChecklistVersion:
    v = session.get(ChecklistVersion, version_id)
    if v is None or v.request_id != req.id:
        raise ScopeError("unknown checklist version")
    if v.status != "proposed":
        raise ScopeError(f"version {v.number} is {v.status}; only a proposed version can be confirmed")
    if not v.items:
        raise ScopeError("the checklist is empty")
    if not v.provider_email:
        raise ScopeError("the provider's email address is missing")
    now = clock.now(session)
    prev = current_version(session, req)
    if prev is not None:
        prev.status = "superseded"
    v.status = "confirmed"
    v.confirmed_at = now
    v.confirmed_by = user.id
    req.current_version_id = v.id
    req.due_date = v.due_date
    req.cc_requester = cc_requester
    session.flush()
    org = next((c.payload.get("organization") for c in session.scalars(select(Comment).where(Comment.request_id == req.id, Comment.kind == "scope_proposal").order_by(Comment.id.desc())) if c.payload.get("version_id") == v.id), None)
    provider = get_or_create_provider(session, req.workspace_id, v.provider_email, v.provider_name, org)
    if not any(o.provider_id == provider.id for o in req.owners):
        if prev is not None and req.origin == "comment":
            req.owners.clear()
            session.flush()
        req.owners.append(RequestOwner(provider_id=provider.id))
    audit.log(session, actor="requester", actor_detail=user.email, action="checklist_confirmed", workspace_id=req.workspace_id, request_id=req.id, version=v.number, items=[i.description for i in v.items])
    add_comment(session, req, author="requester", user_id=user.id, kind="checklist_confirmed", body=f"Confirmed checklist v{v.number}.", payload={"version_id": v.id})
    if prev is None:
        _draft_initial(session, req, v, user, provider)
        states.transition(session, req, states.READY_TO_SEND, actor="requester", reason="checklist confirmed", actor_detail=user.email)
    else:
        from .checking import enqueue_check
        from .followups import queue_change_notice

        queue_change_notice(session, req, [f"The checklist was updated to version {v.number}:"] + [f"   {i + 1}. {it.description}" for i, it in enumerate(v.items)], key=f"change:{req.id}:v{v.number}")
        enqueue_check(session, req, trigger=f"scope v{v.number}")
    return v


def _draft_initial(session: Session, req: Request, v: ChecklistVersion, user: User, provider) -> None:
    token = secrets.token_urlsafe(12)
    conv = Conversation(
        workspace_id=req.workspace_id,
        provider_id=provider.id,
        reply_token=token,
        subject=emails.initial_subject(req, user, provider.organization),
        created_at=clock.now(session),
    )
    session.add(conv)
    session.flush()
    conv.links.append(ConversationRequest(request_id=req.id, version_id=v.id))
    link = hub.hub_url(hub.issue_token(session, provider))
    msg = outbox.queue_message(
        session,
        workspace_id=req.workspace_id,
        kind="initial",
        idempotency_key=f"initial:{req.id}:v{v.number}",
        to=[provider.email],
        cc=[user.email] if req.cc_requester else [],
        subject=conv.subject,
        text=emails.initial_single(req, list(v.items), user, provider.name, provider.email, link),
        from_name=emails.from_name(user),
        reply_to=outbox.reply_address(token),
        conversation=conv,
        request_id=req.id,
        draft=True,
    )
    assert msg is not None
    add_comment(session, req, author="agent", kind="email_draft", body="Here's the email I'll send. Review it and send when ready.", payload={"message_id": msg.id})


def send_draft(session: Session, user: User, req: Request, message_id: int, edited_text: str | None = None) -> None:
    from ..models import OutboundMessage

    msg = session.get(OutboundMessage, message_id)
    if msg is None or msg.request_id != req.id or msg.status != "draft":
        raise ScopeError("no draft to send")
    if req.state != states.READY_TO_SEND:
        raise ScopeError(f"request is {req.state}")
    if edited_text and edited_text.strip() and edited_text != msg.text_body:
        msg.text_body = edited_text
        audit.log(session, actor="requester", actor_detail=user.email, action="email_edited", workspace_id=req.workspace_id, request_id=req.id, message=msg.id)
    outbox.release(session, msg, actor_detail=user.email)
    states.transition(session, req, states.WAITING_PROVIDER, actor="requester", reason="email approved", actor_detail=user.email)

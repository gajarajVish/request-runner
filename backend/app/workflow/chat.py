"""Requester chat about an open request. Answers from the request's own data; any change it
suggests is only a proposal the requester confirms with a button (nothing changes silently)."""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit, clock
from ..config import get_settings
from ..llm import base as llm
from ..llm import prompts
from ..llm.schemas import ChatReply
from ..models import Comment, EvidenceAssignment, EvidenceFile, ProviderQuestion, Request, User
from . import states
from .common import add_comment, current_version, effective_verdicts, request_label


def _context(s: Session, req: Request) -> str:
    v = current_version(s, req)
    verdicts = effective_verdicts(s, req)
    files = [s.get(EvidenceFile, a.file_id) for a in s.scalars(select(EvidenceAssignment).where(EvidenceAssignment.request_id == req.id))]
    data = {
        "request": request_label(req),
        "state": states.LABELS.get(req.state, req.state),
        "due_date": req.due_date.isoformat() if req.due_date else None,
        "providers": [o.provider.email for o in req.owners],
        "automatic_contacts_used": f"{req.auto_contact_count} of {get_settings().max_auto_contacts}",
        "items": [
            {"description": i.description, "verdict": verdicts.get(i.key, {}).get("verdict"), "missing": verdicts.get(i.key, {}).get("missing"), "rationale": verdicts.get(i.key, {}).get("rationale")}
            for i in (v.items if v else [])
        ],
        "files": [{"name": f.filename, "status": f.extraction_status, "received": f.created_at.isoformat()} for f in files if f],
        "open_questions": [q.question for q in s.scalars(select(ProviderQuestion).where(ProviderQuestion.request_id == req.id, ProviderQuestion.status == "waiting_requester"))],
    }
    return json.dumps(data, indent=1)


def ask(s: Session, user: User, req: Request, text: str) -> dict:
    add_comment(s, req, author="requester", user_id=user.id, kind="chat", body=text)
    recent = s.scalars(select(Comment).where(Comment.request_id == req.id, Comment.kind.in_(["chat", "chat_reply"])).order_by(Comment.id.desc()).limit(8)).all()
    history = "\n".join(f"[{c.author}] {c.body}" for c in reversed(recent))
    today = clock.local_date(clock.now(s), get_settings().workspace_timezone)
    call = llm.LLMCall(
        step="chat",
        system=prompts.CHAT.format(today=today.isoformat()),
        content=[{"type": "text", "text": f"<request_data>\n{_context(s, req)}\n</request_data>\n\nConversation:\n{history}"}],
        output=ChatReply,
        tier="fast",
        context={"request_id": req.id, "text": text},
    )
    try:
        out = llm.run(call, ChatReply)
    except llm.LLMError as e:
        c = add_comment(s, req, author="system", kind="chat_reply", body=f"Sorry, I couldn't answer that ({e}).")
        return {"comment_id": c.id}
    payload = {}
    if out.proposed_action != "none":
        payload = {"proposed_action": out.proposed_action, "new_due_date": out.new_due_date}
    c = add_comment(s, req, author="agent", kind="chat_reply", body=out.reply, payload=payload)
    audit.log(s, actor="agent", action="chat_answered", workspace_id=req.workspace_id, request_id=req.id, proposed_action=out.proposed_action)
    return {"comment_id": c.id}

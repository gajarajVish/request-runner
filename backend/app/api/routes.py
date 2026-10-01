"""Requester-facing API. Every route is scoped to the signed-in user's workspace."""

from __future__ import annotations

import asyncio
import json
from datetime import date

import bcrypt
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit, clock
from ..config import get_settings
from ..db import new_session
from ..models import (
    AuditLog,
    ChecklistVersion,
    Conversation,
    EvidenceFile,
    Event,
    InboundMessage,
    OutboundMessage,
    Provider,
    Request as RequestModel,
    User,
)
from ..storage import get_store
from ..workflow import actions, inbound, scoping, states
from . import serialize
from .deps import current_user, db, owned_request

router = APIRouter(prefix="/api")


# --------------------------------------------------------------------------- auth


class LoginIn(BaseModel):
    email: str
    password: str


@router.post("/login")
def login(body: LoginIn, request: Request, s: Session = Depends(db)):
    u = s.scalars(select(User).where(User.email == body.email.strip().lower())).first()
    if u is None or not u.password_hash or not bcrypt.checkpw(body.password.encode(), u.password_hash.encode()):
        raise HTTPException(401, "wrong email or password")
    request.session["user_id"] = u.id
    return {"id": u.id, "name": u.name, "email": u.email}


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return {"ok": True}


@router.get("/me")
def me(request: Request, s: Session = Depends(db)):
    cfg = get_settings()
    uid = request.session.get("user_id")
    u = s.get(User, uid) if uid else None
    return {
        "user": {"id": u.id, "name": u.name, "email": u.email} if u else None,
        "dev": cfg.is_dev,
        "app_name": cfg.app_name,
        "now": serialize.iso(clock.now(s)),
        "inbound_domain": cfg.email_inbound_domain,
        "email_provider": cfg.email_provider,
        "llm_provider": cfg.llm_provider,
    }


@router.get("/dev/users")
def dev_users(s: Session = Depends(db)):
    if not get_settings().is_dev:
        raise HTTPException(404)
    return [{"id": u.id, "name": u.name, "email": u.email} for u in s.scalars(select(User).order_by(User.id))]


@router.post("/dev/switch-user/{uid}")
def dev_switch(uid: int, request: Request, s: Session = Depends(db)):
    if not get_settings().is_dev:
        raise HTTPException(404)
    u = s.get(User, uid)
    if u is None:
        raise HTTPException(404)
    request.session["user_id"] = u.id
    return {"id": u.id, "name": u.name, "email": u.email}


# --------------------------------------------------------------------------- requests


@router.get("/requests")
def list_requests(user: User = Depends(current_user), s: Session = Depends(db)):
    rows = s.scalars(select(RequestModel).where(RequestModel.workspace_id == user.workspace_id).order_by(RequestModel.id.desc())).all()
    today = clock.local_date(clock.now(s), get_settings().workspace_timezone)
    return [serialize.request_summary(s, r, today) for r in rows]


class TextIn(BaseModel):
    text: str


@router.post("/requests")
def create_request(body: TextIn, user: User = Depends(current_user), s: Session = Depends(db)):
    if not body.text.strip():
        raise HTTPException(400, "empty comment")
    req = scoping.create_from_comment(s, user, body.text.strip())
    return {"id": req.id}


@router.get("/requests/{rid}")
def get_request(rid: int, user: User = Depends(current_user), s: Session = Depends(db)):
    return serialize.request_detail(s, owned_request(rid, user, s))


@router.post("/requests/{rid}/comments")
def post_comment(rid: int, body: TextIn, user: User = Depends(current_user), s: Session = Depends(db)):
    req = owned_request(rid, user, s)
    if not body.text.strip():
        raise HTTPException(400, "empty comment")
    if req.state in states.OPEN_WITH_PROVIDER:
        scoping.request_scope_change(s, user, req, body.text.strip())
    else:
        scoping.requester_reply(s, user, req, body.text.strip())
    return {"ok": True}


class ItemsIn(BaseModel):
    items: list[dict]
    provider_email: str | None = None
    provider_name: str | None = None
    due_date: str | None = None


@router.put("/requests/{rid}/versions/{vid}")
def edit_proposed(rid: int, vid: int, body: ItemsIn, user: User = Depends(current_user), s: Session = Depends(db)):
    """Requester edits a proposed checklist. Saved as a new proposed version (created_by=requester)."""
    from ..llm.schemas import DraftItem

    req = owned_request(rid, user, s)
    v = s.get(ChecklistVersion, vid)
    if v is None or v.request_id != req.id or v.status != "proposed":
        raise HTTPException(400, "only a proposed version can be edited")
    try:
        drafts = [DraftItem.model_validate(i) for i in body.items]
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"invalid items: {e}") from e
    v.status = "superseded"
    from ..workflow.common import current_version, next_version_number

    nv = ChecklistVersion(
        request_id=req.id,
        number=next_version_number(s, req),
        status="proposed",
        provider_email=(body.provider_email or v.provider_email or "").strip().lower() or None,
        provider_name=body.provider_name or v.provider_name,
        due_date=date.fromisoformat(body.due_date) if body.due_date else v.due_date,
        notes=v.notes,
        created_by="requester",
        created_at=clock.now(s),
    )
    cur = current_version(s, req)
    nv.items = scoping.items_from_drafts(drafts, cur.items if cur else v.items)
    s.add(nv)
    s.flush()
    audit.log(s, actor="requester", actor_detail=user.email, action="checklist_edited", workspace_id=req.workspace_id, request_id=req.id, version=nv.number)
    from ..workflow.common import add_comment

    add_comment(s, req, author="requester", user_id=user.id, kind="scope_proposal", body=f"Edited the checklist (v{nv.number}).", payload={"version_id": nv.id, "questions": [], "assumptions": [], "ready": bool(nv.provider_email and nv.items), "edited": True})
    return {"version_id": nv.id}


class ConfirmIn(BaseModel):
    version_id: int
    cc_requester: bool = False


@router.post("/requests/{rid}/confirm")
def confirm(rid: int, body: ConfirmIn, user: User = Depends(current_user), s: Session = Depends(db)):
    req = owned_request(rid, user, s)
    try:
        scoping.confirm(s, user, req, body.version_id, cc_requester=body.cc_requester)
    except scoping.ScopeError as e:
        raise HTTPException(400, str(e)) from e
    return {"ok": True}


class SendIn(BaseModel):
    message_id: int
    text: str | None = None


@router.post("/requests/{rid}/send")
def send(rid: int, body: SendIn, user: User = Depends(current_user), s: Session = Depends(db)):
    req = owned_request(rid, user, s)
    try:
        scoping.send_draft(s, user, req, body.message_id, body.text)
    except scoping.ScopeError as e:
        raise HTTPException(400, str(e)) from e
    return {"ok": True}


class ReasonIn(BaseModel):
    reason: str = ""


def _act(fn, *args):
    try:
        fn(*args)
    except (actions.ActionError, states.InvalidTransition, ValueError) as e:
        raise HTTPException(400, str(e)) from e
    return {"ok": True}


@router.post("/requests/{rid}/cancel")
def cancel(rid: int, body: ReasonIn, user: User = Depends(current_user), s: Session = Depends(db)):
    return _act(actions.cancel, s, user, owned_request(rid, user, s), body.reason)


@router.post("/requests/{rid}/accept")
def accept(rid: int, body: ReasonIn, user: User = Depends(current_user), s: Session = Depends(db)):
    return _act(actions.accept, s, user, owned_request(rid, user, s), body.reason)


@router.post("/requests/{rid}/resume")
def resume(rid: int, user: User = Depends(current_user), s: Session = Depends(db)):
    return _act(actions.resume, s, user, owned_request(rid, user, s))


@router.post("/requests/{rid}/manual-followup")
def manual_followup(rid: int, user: User = Depends(current_user), s: Session = Depends(db)):
    return _act(actions.manual_followup, s, user, owned_request(rid, user, s))


@router.post("/requests/{rid}/recheck")
def recheck(rid: int, user: User = Depends(current_user), s: Session = Depends(db)):
    return _act(actions.retry_check, s, user, owned_request(rid, user, s))


class OverrideIn(BaseModel):
    item_key: str
    verdict: str
    reason: str


@router.post("/requests/{rid}/override")
def override(rid: int, body: OverrideIn, user: User = Depends(current_user), s: Session = Depends(db)):
    return _act(actions.override, s, user, owned_request(rid, user, s), body.item_key, body.verdict, body.reason)


class DueIn(BaseModel):
    due_date: date


@router.post("/requests/{rid}/due-date")
def due_date(rid: int, body: DueIn, user: User = Depends(current_user), s: Session = Depends(db)):
    return _act(actions.change_due_date, s, user, owned_request(rid, user, s), body.due_date)


class AnswerIn(BaseModel):
    question_id: int
    answer: str


@router.post("/requests/{rid}/answer-question")
def answer_question(rid: int, body: AnswerIn, user: User = Depends(current_user), s: Session = Depends(db)):
    return _act(inbound.answer_from_requester, s, user.email, owned_request(rid, user, s), body.question_id, body.answer)


@router.post("/requests/{rid}/chat")
def chat(rid: int, body: TextIn, user: User = Depends(current_user), s: Session = Depends(db)):
    from ..workflow import chat as chat_mod

    req = owned_request(rid, user, s)
    return chat_mod.ask(s, user, req, body.text)


@router.post("/messages/{mid}/resend")
def resend(mid: int, user: User = Depends(current_user), s: Session = Depends(db)):
    m = s.get(OutboundMessage, mid)
    if m is None or m.workspace_id != user.workspace_id:
        raise HTTPException(404)
    try:
        clone = actions.resend(s, user, m)
    except actions.ActionError as e:
        raise HTTPException(400, str(e)) from e
    return {"id": clone.id}


@router.get("/messages")
def list_messages(user: User = Depends(current_user), s: Session = Depends(db)):
    rows = s.scalars(select(OutboundMessage).where(OutboundMessage.workspace_id == user.workspace_id).order_by(OutboundMessage.id.desc()).limit(300)).all()
    return [serialize.outbound(m) for m in rows]


# --------------------------------------------------------------------------- files


def _file_for(fid: int, user: User, s: Session) -> EvidenceFile:
    f = s.get(EvidenceFile, fid)
    if f is None or f.workspace_id != user.workspace_id:
        raise HTTPException(404)
    return f


@router.get("/files/{fid}/download")
def download(fid: int, user: User = Depends(current_user), s: Session = Depends(db)):
    f = _file_for(fid, user, s)
    if f.kind == "text" or not f.blob:
        raise HTTPException(404)
    audit.log(s, actor="requester", actor_detail=user.email, action="file_downloaded", workspace_id=user.workspace_id, file=f.id)
    safe = "".join(c for c in f.filename if c.isalnum() or c in "._- ")[:150] or "file"
    return Response(
        get_store().get(f.blob),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{safe}"', "X-Content-Type-Options": "nosniff"},
    )


@router.get("/files/{fid}/images/{idx}")
def file_image(fid: int, idx: int, user: User = Depends(current_user), s: Session = Depends(db)):
    """Rendered page images (our own PNG renders, never the provider's original bytes)."""
    f = _file_for(fid, user, s)
    imgs = (f.extraction or {}).get("images", [])
    if not 0 <= idx < len(imgs):
        raise HTTPException(404)
    return Response(get_store().get(imgs[idx]["blob"]), media_type="image/png", headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=3600"})


@router.get("/files/{fid}")
def file_detail(fid: int, user: User = Depends(current_user), s: Session = Depends(db)):
    f = _file_for(fid, user, s)
    out = serialize.file(f)
    out["segments"] = [{"label": sg["label"], "text": sg["text"][:20000]} for sg in (f.extraction or {}).get("segments", [])]
    return out


# --------------------------------------------------------------------------- inbound queue


@router.get("/inbound")
def list_inbound(status: str | None = None, user: User = Depends(current_user), s: Session = Depends(db)):
    q = select(InboundMessage).order_by(InboundMessage.id.desc()).limit(200)
    rows = s.scalars(q).all()
    out = []
    for m in rows:
        # unmatched mail has no workspace yet; show it only if a suggestion points into this workspace (or none at all in dev)
        if m.workspace_id not in (None, user.workspace_id):
            continue
        if m.workspace_id is None and not get_settings().is_dev:
            suggested = [s.get(Conversation, cid) for cid in m.suggested_conversation_ids or []]
            if not any(x is not None and x.workspace_id == user.workspace_id for x in suggested):
                continue
        if status and m.status != status:
            continue
        d = serialize.inbound(m, full=True)
        d["suggestions"] = []
        for cid in m.suggested_conversation_ids or []:
            c = s.get(Conversation, cid)
            if c and c.workspace_id == user.workspace_id:
                d["suggestions"].append({"conversation_id": c.id, "subject": c.subject, "provider": s.get(Provider, c.provider_id).email})
        out.append(d)
    return out


class AssignIn(BaseModel):
    conversation_id: int


@router.post("/inbound/{iid}/assign")
def assign_inbound(iid: int, body: AssignIn, user: User = Depends(current_user), s: Session = Depends(db)):
    m = s.get(InboundMessage, iid)
    c = s.get(Conversation, body.conversation_id)
    if m is None or c is None or c.workspace_id != user.workspace_id or m.workspace_id not in (None, user.workspace_id):
        raise HTTPException(404)
    if m.workspace_id is None and not get_settings().is_dev:
        # mail we couldn't place in any workspace: only reachable through a suggestion into this one
        suggested = [s.get(Conversation, cid) for cid in m.suggested_conversation_ids or []]
        if not any(x is not None and x.workspace_id == user.workspace_id for x in suggested):
            raise HTTPException(404)
    if m.status != "unmatched":
        raise HTTPException(400, "message is not in the unmatched queue")
    audit.log(s, actor="requester", actor_detail=user.email, action="inbound_assigned", workspace_id=user.workspace_id, inbound=m.id, conversation=c.id)
    inbound.assign_unmatched(s, m, c.id)
    return {"ok": True}


@router.get("/conversations")
def list_conversations(user: User = Depends(current_user), s: Session = Depends(db)):
    rows = s.scalars(select(Conversation).where(Conversation.workspace_id == user.workspace_id).order_by(Conversation.id.desc())).all()
    return [{"id": c.id, "subject": c.subject, "provider": s.get(Provider, c.provider_id).email} for c in rows]


# --------------------------------------------------------------------------- audit & events


@router.get("/audit")
def audit_log(user: User = Depends(current_user), s: Session = Depends(db)):
    rows = s.scalars(select(AuditLog).where(AuditLog.workspace_id == user.workspace_id).order_by(AuditLog.id.desc()).limit(500)).all()
    return [{"id": a.id, "at": serialize.iso(a.at), "actor": a.actor, "actor_detail": a.actor_detail, "action": a.action, "request_id": a.request_id, "detail": a.detail} for a in rows]


@router.get("/events")
async def events(request: Request, user: User = Depends(current_user)):
    """Server-Sent Events: polls the cross-process change feed for this workspace."""
    ws = user.workspace_id
    with new_session() as s:
        last = s.scalars(select(Event.id).order_by(Event.id.desc()).limit(1)).first() or 0

    async def stream():
        nonlocal last
        yield "retry: 2000\n\n"
        idle = 0
        while not await request.is_disconnected():
            with new_session() as s:
                rows = s.scalars(select(Event).where(Event.id > last).order_by(Event.id).limit(200)).all()
                batch = [{"id": e.id, "topic": e.topic, "request_id": e.request_id, "data": e.data} for e in rows if e.workspace_id == ws]
                if rows:
                    last = rows[-1].id
            if batch:
                yield f"data: {json.dumps(batch)}\n\n"
                idle = 0
            else:
                idle += 1
                if idle % 15 == 0:
                    yield ": ping\n\n"
            await asyncio.sleep(0.7)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# --------------------------------------------------------------------------- demo / dev


class AdvanceIn(BaseModel):
    seconds: int
    key: str


@router.post("/dev/clock/advance")
def advance_clock(body: AdvanceIn, user: User = Depends(current_user), s: Session = Depends(db)):
    if not get_settings().is_dev:
        raise HTTPException(404)
    applied = clock.advance(s, body.seconds, body.key)
    audit.log(s, actor="requester", actor_detail=user.email, action="demo_clock_advanced", workspace_id=user.workspace_id, seconds=body.seconds, applied=applied)
    from ..workflow.followups import enqueue_sweep

    s.flush()
    enqueue_sweep(s)
    return {"applied": applied, "now": serialize.iso(clock.now(s))}


@router.post("/dev/sweep")
def run_sweep(user: User = Depends(current_user), s: Session = Depends(db)):
    from ..workflow.followups import enqueue_sweep

    enqueue_sweep(s)
    return {"ok": True}


@router.post("/dev/inject")
async def dev_inject(file: UploadFile = File(...), request_id: int | None = Form(None), user: User = Depends(current_user)):
    """Inject a raw .eml through the same pipeline as real inbound mail (dev only)."""
    if not get_settings().is_dev:
        raise HTTPException(404)
    from ..cli import retarget

    raw = await file.read()
    if request_id:
        with new_session() as s:
            req = owned_request(request_id, user, s)
            raw = retarget(s, raw, req)
    iid, created = inbound.ingest_raw(raw, source="inject")
    return {"inbound_id": iid, "created": created}


# --------------------------------------------------------------------------- imports (Part 2)


def _batch(bid: int, user: User, s: Session):
    from ..models import ImportBatch, ImportList

    b = s.get(ImportBatch, bid)
    lst = s.get(ImportList, b.import_list_id) if b else None
    if b is None or lst is None or lst.workspace_id != user.workspace_id:
        raise HTTPException(404, "not found")
    return b


@router.get("/imports")
def list_imports(user: User = Depends(current_user), s: Session = Depends(db)):
    from ..models import ImportBatch, ImportList
    from ..workflow.imports import summary

    lists = s.scalars(select(ImportList).where(ImportList.workspace_id == user.workspace_id).order_by(ImportList.id.desc())).all()
    out = []
    for lst in lists:
        batches = s.scalars(select(ImportBatch).where(ImportBatch.import_list_id == lst.id).order_by(ImportBatch.id.desc())).all()
        out.append(
            {
                "id": lst.id,
                "name": lst.name,
                "batches": [{"id": b.id, "filename": b.filename, "status": b.status, "created_at": serialize.iso(b.created_at), "applied_at": serialize.iso(b.applied_at), "summary": summary(b)} for b in batches],
            }
        )
    return out


@router.post("/imports")
async def upload_import(file: UploadFile = File(...), list_name: str = Form(""), user: User = Depends(current_user), s: Session = Depends(db)):
    from ..workflow import imports

    data = await file.read(5 * 1024 * 1024 + 1)
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(413, "CSV is larger than 5 MB")
    name = list_name.strip() or (file.filename or "Request list").rsplit(".", 1)[0]
    batch = imports.start_import(s, user, list_name=name, filename=file.filename or "import.csv", data=data)
    return {"id": batch.id}


@router.get("/imports/batches/{bid}")
def get_batch(bid: int, user: User = Depends(current_user), s: Session = Depends(db)):
    from ..workflow import imports

    return imports.batch_view(s, _batch(bid, user, s))


class RowEditIn(BaseModel):
    include: bool | None = None
    ownership_mode: str | None = None
    due_date: str | None = None
    instructions: str | None = None
    items: list[dict] | None = None
    merge_into: str | None = None


@router.patch("/imports/batches/{bid}/rows/{row_id}")
def edit_import_row(bid: int, row_id: int, body: RowEditIn, user: User = Depends(current_user), s: Session = Depends(db)):
    from ..models import ImportRow
    from ..workflow import imports

    b = _batch(bid, user, s)
    row = s.get(ImportRow, row_id)
    if row is None or row.batch_id != b.id:
        raise HTTPException(404, "not found")
    try:
        imports.edit_row(s, user, b, row, body.model_dump(exclude_unset=True))
    except imports.ImportError_ as e:
        raise HTTPException(400, str(e)) from e
    return imports.row_view(row)


@router.post("/imports/batches/{bid}/apply")
def apply_import(bid: int, user: User = Depends(current_user), s: Session = Depends(db)):
    from ..workflow import imports

    try:
        return imports.apply(s, user, _batch(bid, user, s))
    except imports.ImportError_ as e:
        raise HTTPException(400, str(e)) from e


@router.post("/imports/batches/{bid}/discard")
def discard_import(bid: int, user: User = Depends(current_user), s: Session = Depends(db)):
    b = _batch(bid, user, s)
    if b.status not in ("analyzing", "review", "error"):
        raise HTTPException(400, f"this import is {b.status}")
    b.status = "discarded"
    audit.log(s, actor="requester", actor_detail=user.email, action="import_discarded", workspace_id=user.workspace_id, batch=b.id)
    return {"ok": True}


class SendAllIn(BaseModel):
    message_ids: list[int] | None = None


@router.post("/imports/batches/{bid}/send")
def send_import(bid: int, body: SendAllIn, user: User = Depends(current_user), s: Session = Depends(db)):
    from ..workflow import imports

    try:
        return {"sent": imports.send_all(s, user, _batch(bid, user, s), body.message_ids)}
    except imports.ImportError_ as e:
        raise HTTPException(400, str(e)) from e


class DraftEditIn(BaseModel):
    text: str


@router.put("/messages/{mid}/draft")
def edit_draft(mid: int, body: DraftEditIn, user: User = Depends(current_user), s: Session = Depends(db)):
    m = s.get(OutboundMessage, mid)
    if m is None or m.workspace_id != user.workspace_id:
        raise HTTPException(404, "not found")
    if m.status != "draft":
        raise HTTPException(400, "only a draft can be edited")
    if body.text.strip() and body.text != m.text_body:
        m.text_body = body.text
        audit.log(s, actor="requester", actor_detail=user.email, action="email_edited", workspace_id=user.workspace_id, request_id=m.request_id, message=m.id)
    return serialize.outbound(m)


# --------------------------------------------------------------------------- dashboard


@router.get("/dashboard")
def dashboard(
    provider: str | None = None,
    status: str | None = None,
    overdue: bool = False,
    list_id: int | None = None,
    user: User = Depends(current_user),
    s: Session = Depends(db),
):
    """Who is behind: open items grouped by provider, with days overdue. Filters: provider
    email, request state (or 'open'), overdue only, import list."""
    today = clock.local_date(clock.now(s), get_settings().workspace_timezone)
    q = select(RequestModel).where(RequestModel.workspace_id == user.workspace_id)
    if list_id:
        q = q.where(RequestModel.import_list_id == list_id)
    reqs = s.scalars(q.order_by(RequestModel.due_date, RequestModel.id)).all()
    groups: dict[int, dict] = {}
    counts: dict[str, int] = {}
    for r in reqs:
        counts[r.state] = counts.get(r.state, 0) + 1
        if status == "open" and r.state in states.TERMINAL:
            continue
        if status and status != "open" and r.state != status:
            continue
        summ = serialize.request_summary(s, r, today)
        if overdue and not summ["overdue_days"]:
            continue
        for o in r.owners:
            if provider and o.provider.email != provider.lower():
                continue
            g = groups.setdefault(
                o.provider_id,
                {"provider": {"id": o.provider_id, "email": o.provider.email, "name": o.provider.name}, "open": 0, "overdue": 0, "max_days_overdue": 0, "items": []},
            )
            g["items"].append(summ)
            if r.state not in states.TERMINAL:
                g["open"] += 1
            if summ["overdue_days"]:
                g["overdue"] += 1
                g["max_days_overdue"] = max(g["max_days_overdue"], summ["overdue_days"])
    providers = sorted(groups.values(), key=lambda g: (-g["max_days_overdue"], -g["overdue"], -g["open"], g["provider"]["email"]))
    return {
        "today": today.isoformat(),
        "counts": counts,
        "providers_behind": sum(1 for g in providers if g["overdue"]),
        "providers": providers,
        "all_providers": sorted({o.provider.email for r in reqs for o in r.owners}),
    }

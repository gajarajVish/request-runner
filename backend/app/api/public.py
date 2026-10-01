"""Unauthenticated endpoints: the provider upload hub and inbound email webhooks."""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
from collections import defaultdict, deque

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit, clock
from ..config import get_settings
from ..models import EvidenceAssignment, EvidenceFile, Request as RequestModel, RequestOwner, User
from ..workflow import evidence, hub, inbound, states
from ..workflow.checking import enqueue_check
from ..workflow.common import add_comment, effective_verdicts, request_label
from . import serialize
from .deps import db

router = APIRouter()

# --------------------------------------------------------------------------- rate limiting


class RateLimiter:
    def __init__(self) -> None:
        self.hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str, limit: int, window: float) -> None:
        now = time.monotonic()
        q = self.hits[key]
        while q and now - q[0] > window:
            q.popleft()
        if len(q) >= limit:
            raise HTTPException(429, "too many requests; try again shortly")
        q.append(now)


limiter = RateLimiter()


def _client(request: Request) -> str:
    return request.client.host if request.client else "?"


def _hub(token: str, request: Request, s: Session, *, limit: int = 120, window: float = 60):
    limiter.check(f"hub:{_client(request)}", limit, window)
    limiter.check(f"hubtok:{hashlib.sha256(token.encode()).hexdigest()[:16]}", limit, window)
    res = hub.resolve(s, token)
    if res is None:
        s.commit()  # persist revocation if resolve() just revoked it
        raise HTTPException(404, "This link has expired or is no longer active.")
    return res


# --------------------------------------------------------------------------- upload hub


@router.get("/api/hub/{token}")
def hub_view(token: str, request: Request, s: Session = Depends(db)):
    tok, provider, reqs = _hub(token, request, s)
    today = clock.local_date(clock.now(s), get_settings().workspace_timezone)
    items = []
    for r in reqs:
        verdicts = effective_verdicts(s, r)
        requester = s.get(User, r.requester_id)
        mine = s.scalars(
            select(EvidenceFile)
            .join(EvidenceAssignment, EvidenceAssignment.file_id == EvidenceFile.id)
            .where(EvidenceAssignment.request_id == r.id, EvidenceFile.provider_id == provider.id)
            .order_by(EvidenceFile.id)
        ).all()
        from ..workflow.common import current_version

        v = current_version(s, r)
        items.append(
            {
                "request_id": r.id,
                "label": request_label(r),
                "title": r.title,
                "requester": requester.name if requester else "",
                "due_date": serialize.iso(r.due_date),
                "overdue_days": (today - r.due_date).days if r.due_date and today > r.due_date else 0,
                "shared": len(r.owners) > 1,
                "checklist": [
                    {
                        "key": i.key,
                        "kind": i.kind,
                        "description": i.description,
                        "subpoints": [sp["text"] + (f" ({sp['condition']})" if sp.get("condition") else "") for sp in i.subpoints],
                        "status": "received" if verdicts.get(i.key, {}).get("verdict") == "met" else "outstanding",
                        "missing": verdicts.get(i.key, {}).get("missing", []) if verdicts.get(i.key, {}).get("verdict") not in ("met", "pending") else [],
                    }
                    for i in (v.items if v else [])
                ],
                # only this provider's own submissions; a co-owner's files are never shown
                "submitted": [{"filename": f.filename, "kind": f.kind, "at": serialize.iso(f.created_at), "status": f.extraction_status} for f in mine if f.parent_file_id is None],
            }
        )
    audit.log(s, actor="provider", actor_detail=provider.email, action="upload_page_viewed", workspace_id=provider.workspace_id)
    return {"provider": {"name": provider.name, "email": provider.email}, "items": items, "app_name": get_settings().app_name}


def _eligible(reqs: list[RequestModel], request_id: int | None) -> list[RequestModel]:
    if request_id is None:
        return reqs
    sel = [r for r in reqs if r.id == request_id]
    if not sel:
        raise HTTPException(400, "that item isn't open on this page")
    return sel


@router.post("/api/hub/{token}/upload")
async def hub_upload(token: str, request: Request, file: UploadFile = File(...), request_id: int | None = Form(None), s: Session = Depends(db)):
    cfg = get_settings()
    tok, provider, reqs = _hub(token, request, s, limit=40, window=600)
    targets = _eligible(reqs, request_id)
    chunks, size = [], 0
    while chunk := await file.read(1024 * 1024):
        size += len(chunk)
        if size > cfg.upload_max_file_bytes:
            raise HTTPException(413, f"files must be under {cfg.upload_max_file_bytes // (1024 * 1024)} MB")
        chunks.append(chunk)
    data = b"".join(chunks)
    files = evidence.store_file(
        s, workspace_id=provider.workspace_id, data=data, filename=file.filename or "upload", declared_type=file.content_type, source="upload", provider_id=provider.id
    )
    top = files[0]
    now = clock.now(s)
    for r in targets:
        for f in files:
            s.add(EvidenceAssignment(file_id=f.id, request_id=r.id, method="upload" if request_id else "upload_unassigned", created_at=now))
        add_comment(
            s, r, author="provider", kind="provider_upload",
            body=f"{provider.email} uploaded {top.filename}" + ("" if top.accepted else f" (rejected: {top.rejection_reason})"),
            payload={"file_ids": [f.id for f in files], "from": provider.email},
        )
        if r.state != states.CHECKING:
            states.transition(s, r, states.CHECKING, actor="provider", reason="upload received", actor_detail=provider.email)
        enqueue_check(s, r, trigger=f"upload {top.id}", substantive=True)
    return {"ok": True, "accepted": top.accepted, "reason": top.rejection_reason or top.unreadable_reason, "filename": top.filename}


class AnswerIn(BaseModel):
    request_id: int
    text: str


@router.post("/api/hub/{token}/answer")
def hub_answer(token: str, body: AnswerIn, request: Request, s: Session = Depends(db)):
    tok, provider, reqs = _hub(token, request, s, limit=60, window=600)
    (r,) = _eligible(reqs, body.request_id)
    text = body.text.strip()
    if not text:
        raise HTTPException(400, "empty answer")
    if len(text) > 20000:
        raise HTTPException(413, "answer too long")
    ef = evidence.store_text(s, workspace_id=provider.workspace_id, text=text, label=f"Answer typed on the upload page by {provider.email}", source="upload", inbound_id=None, provider_id=provider.id)
    s.add(EvidenceAssignment(file_id=ef.id, request_id=r.id, method="upload", created_at=clock.now(s)))
    add_comment(s, r, author="provider", kind="provider_answer", body=text[:4000], payload={"file_ids": [ef.id], "from": provider.email})
    if r.state != states.CHECKING:
        states.transition(s, r, states.CHECKING, actor="provider", reason="answer received", actor_detail=provider.email)
    enqueue_check(s, r, trigger=f"answer {ef.id}", substantive=True)
    return {"ok": True}


class CloseIn(BaseModel):
    request_id: int | None = None
    note: str = ""


@router.post("/api/hub/{token}/close")
def hub_close(token: str, body: CloseIn, request: Request, s: Session = Depends(db)):
    """'That's all I have' for one item, or for everything on the page."""
    tok, provider, reqs = _hub(token, request, s, limit=30, window=600)
    targets = _eligible(reqs, body.request_id)
    now = clock.now(s)
    for r in targets:
        o = s.scalars(select(RequestOwner).where(RequestOwner.request_id == r.id, RequestOwner.provider_id == provider.id)).one()
        o.closed_at = now
        audit.log(s, actor="provider", actor_detail=provider.email, action="provider_closed", workspace_id=r.workspace_id, request_id=r.id, via="upload page", note=body.note[:1000])
        add_comment(s, r, author="provider", kind="provider_closed", body=f"{provider.email} said that's everything they have." + (f" Note: {body.note[:1000]}" if body.note else ""))
        enqueue_check(s, r, trigger="provider closed", substantive=False)
    return {"ok": True, "closed": [r.id for r in targets]}


# --------------------------------------------------------------------------- inbound webhooks


def _check_basic_auth(request: Request) -> None:
    expected = get_settings().email_inbound_basic_auth
    if not expected:
        if get_settings().is_dev:
            return
        raise HTTPException(503, "inbound webhook auth is not configured")
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("basic "):
        raise HTTPException(401, headers={"WWW-Authenticate": "Basic"})
    try:
        got = base64.b64decode(header[6:]).decode()
    except Exception:  # noqa: BLE001
        raise HTTPException(401) from None
    if not secrets.compare_digest(got, expected):
        raise HTTPException(401, headers={"WWW-Authenticate": "Basic"})


@router.post("/webhooks/postmark/inbound")
async def postmark_inbound(request: Request):
    _check_basic_auth(request)
    raw = await request.body()
    if len(raw) > 40 * 1024 * 1024:
        raise HTTPException(413)
    payload = json.loads(raw)
    iid, created = inbound.ingest_postmark(payload, raw)
    return {"ok": True, "inbound_id": iid, "duplicate": not created}


@router.post("/webhooks/sendgrid/inbound")
async def sendgrid_inbound(request: Request):
    """SendGrid Inbound Parse with 'POST the raw, full MIME message' enabled."""
    _check_basic_auth(request)
    form = await request.form()
    raw = form.get("email")
    if raw is None:
        raise HTTPException(400, "enable 'POST the raw, full MIME message' in Inbound Parse")
    data = raw.encode("utf-8", "surrogateescape") if isinstance(raw, str) else await raw.read()
    iid, created = inbound.ingest_raw(data, source="sendgrid")
    return {"ok": True, "inbound_id": iid, "duplicate": not created}

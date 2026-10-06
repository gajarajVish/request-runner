"""Inbound mail: persist first, then match and process in a job.

Matching order:
  1. the opaque reply token in the recipient address (req+TOKEN@in.domain)
  2. In-Reply-To / References against Message-IDs we sent
  3. sender address -> open conversations, used only as *suggestions* in the unmatched queue
A token/header conflict goes to the unmatched queue for the requester to resolve.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import audit, clock
from ..config import get_settings
from ..db import session_scope
from ..email.mime import InboundEmail, auto_reply_reason, parse_postmark, parse_raw, reference_ids, strip_quoted
from ..llm import base as llm
from ..llm import prompts
from ..llm.schemas import QuestionAnswer, ReplyClassification
from ..models import (
    Conversation,
    ConversationRequest,
    EvidenceAssignment,
    EvidenceFile,
    InboundMessage,
    OutboundMessage,
    Provider,
    ProviderQuestion,
    Request,
    RequestOwner,
)
from ..storage import get_store
from . import evidence, jobs, states
from .common import add_comment, add_flag, current_version, request_label

# --------------------------------------------------------------------------- ingest


def ingest_raw(raw: bytes, source: str = "inject", dedupe_hint: str | None = None) -> tuple[int, bool]:
    """Persist a raw RFC 822 message and queue processing. Returns (inbound id, created)."""
    em = parse_raw(raw)
    return _persist(em, raw, source, dedupe_hint)


def ingest_postmark(payload: dict[str, Any], raw_json: bytes) -> tuple[int, bool]:
    em = parse_postmark(payload)
    hint = f"postmark:{payload.get('MessageID')}" if payload.get("MessageID") else None
    return _persist(em, raw_json, "postmark", hint)


def same_mailbox(a: str, b: str) -> bool:
    """`x+tag@d` is delivered to `x@d`, so whoever reads one reads the other."""

    def base(addr: str) -> str:
        local, _, domain = addr.strip().lower().partition("@")
        return f"{local.split('+', 1)[0]}@{domain}"

    return base(a) == base(b)


def _dedupe_key(em: InboundEmail, raw: bytes, hint: str | None) -> str:
    if hint:
        return hint
    if em.message_id:
        rcpts = ",".join(sorted(set(em.all_recipients)))
        return "mid:" + hashlib.sha256(f"{em.message_id}|{rcpts}".encode()).hexdigest()
    return "raw:" + hashlib.sha256(raw).hexdigest()


def _persist(em: InboundEmail, raw: bytes, source: str, hint: str | None) -> tuple[int, bool]:
    key = _dedupe_key(em, raw, hint)
    blob = get_store().put(raw)
    with session_scope() as s:
        existing = s.scalars(select(InboundMessage).where(InboundMessage.dedupe_key == key)).first()
        if existing is not None:
            audit.log(s, actor="system", action="inbound_duplicate_ignored", workspace_id=existing.workspace_id, inbound=existing.id, source=source)
            return existing.id, False
        row = InboundMessage(
            dedupe_key=key,
            source=source,
            raw_blob=blob,
            from_address=em.from_address,
            from_name=em.from_name,
            to_addresses=em.all_recipients,
            subject=em.subject[:400],
            message_id=em.message_id,
            in_reply_to=em.in_reply_to,
            references=em.references,
            text_body=em.text,
            new_text=strip_quoted(em.text),
            status="received",
            received_at=clock.now(s),
        )
        try:
            with s.begin_nested():
                s.add(row)
        except IntegrityError:  # concurrent duplicate delivery
            dup = s.scalars(select(InboundMessage).where(InboundMessage.dedupe_key == key)).one()
            return dup.id, False
        s.flush()
        audit.log(s, actor="provider", actor_detail=em.from_address, action="email_received", workspace_id=None, inbound=row.id, subject=em.subject, attachments=len(em.attachments))
        jobs.enqueue(s, "process_inbound", f"inbound:{row.id}", {"id": row.id})
        return row.id, True


def _load_email(row: InboundMessage) -> InboundEmail:
    raw = get_store().get(row.raw_blob)
    if row.source == "postmark":
        import json

        return parse_postmark(json.loads(raw))
    return parse_raw(raw)


# --------------------------------------------------------------------------- matching


def _tokens(em: InboundEmail) -> list[str]:
    s = get_settings()
    pat = re.compile(rf"^{re.escape(s.email_inbound_prefix)}\+([A-Za-z0-9_-]+)@(.+)$", re.I)
    out = []
    if em.mailbox_hash:
        out.append(em.mailbox_hash)
    for addr in em.all_recipients:
        m = pat.match(addr)
        if m and m.group(2).lower() == s.email_inbound_domain.lower():
            out.append(m.group(1))
    return list(dict.fromkeys(out))


def match(session: Session, em: InboundEmail) -> tuple[Conversation | None, str | None, list[str], list[int]]:
    """Returns (conversation, method, notes, suggested conversation ids)."""
    notes: list[str] = []
    by_token: Conversation | None = None
    for t in _tokens(em):
        c = session.scalars(select(Conversation).where(Conversation.reply_token == t)).first()
        if c is not None:
            by_token = c
            break
        notes.append(f"unknown reply token {t!r}")
    by_header: Conversation | None = None
    for mid in reversed(reference_ids(em)):
        om = session.scalars(
            select(OutboundMessage).where((OutboundMessage.message_id == mid) | (OutboundMessage.provider_message_id == mid.strip("<>")))
        ).first()
        if om is not None and om.conversation_id:
            by_header = session.get(Conversation, om.conversation_id)
            break
    if by_token and by_header and by_token.id != by_header.id:
        notes.append(f"reply token points to conversation {by_token.id} but headers point to {by_header.id}")
        return None, None, notes, [by_token.id, by_header.id]
    if by_token:
        return by_token, "token", notes, []
    if by_header:
        return by_header, "headers", notes, []
    # sender-based suggestions only
    provs = session.scalars(select(Provider).where(Provider.email == em.from_address)).all()
    sugg = []
    for p in provs:
        sugg += session.scalars(select(Conversation.id).where(Conversation.provider_id == p.id).order_by(Conversation.id.desc())).all()
    notes.append("no reply token or thread headers matched" + ("; sender has open conversations" if sugg else ""))
    return None, None, notes, sugg[:10]


# --------------------------------------------------------------------------- processing


@jobs.handler("process_inbound")
def process_job(payload: dict) -> None:
    process(payload["id"])


def process(inbound_id: int, *, forced_conversation_id: int | None = None) -> None:
    with session_scope() as s:
        row = s.get(InboundMessage, inbound_id)
        if row is None or (row.status not in ("received", "processing", "unmatched") and forced_conversation_id is None):
            return
        row.status = "processing"
        row.attempts += 1
        em = _load_email(row)
        if forced_conversation_id is not None:
            conv, method, notes, sugg = s.get(Conversation, forced_conversation_id), "requester", ["assigned by requester"], []
        else:
            conv, method, notes, sugg = match(s, em)
        row.match_notes = notes
        reason = auto_reply_reason(em)
        if conv is not None:
            row.conversation_id = conv.id
            row.workspace_id = conv.workspace_id
            row.match_method = method
        if reason:
            row.is_auto_reply = True
            row.status = "auto_reply"
            row.processed_at = clock.now(s)
            audit.log(s, actor="system", action="auto_reply_logged", workspace_id=row.workspace_id, inbound=row.id, reason=reason)
            for rid in _conv_request_ids(s, conv):
                req = s.get(Request, rid)
                if req:
                    add_comment(s, req, author="system", kind="auto_reply", body=f"Automatic reply from {em.from_address} ({reason}) - logged, no action taken.", payload={"inbound_id": row.id})
            return
        if conv is None:
            row.status = "unmatched"
            row.suggested_conversation_ids = sugg
            if sugg:
                c0 = s.get(Conversation, sugg[0])
                row.workspace_id = c0.workspace_id if c0 else None
            audit.log(s, actor="system", action="inbound_unmatched", workspace_id=row.workspace_id, inbound=row.id, notes=notes)
            return
        provider = s.get(Provider, conv.provider_id)
        assert provider is not None
        reqs = [s.get(Request, rid) for rid in _conv_request_ids(s, conv)]
        reqs = [r for r in reqs if r is not None]
        owners = [o.provider for r in reqs for o in r.owners]
        sender_provider = next((p for p in owners if p.email == em.from_address), None) or next(
            (p for p in owners if same_mailbox(p.email, em.from_address or "")), None
        )
        row.sender_is_owner = sender_provider is not None
        row.provider_id = sender_provider.id if sender_provider else provider.id
        open_reqs = [r for r in reqs if r.state in states.OPEN_WITH_PROVIDER]
        # store everything first (evidence is kept even for closed requests)
        files = []
        for a in em.attachments:
            files += evidence.store_file(
                s, workspace_id=conv.workspace_id, data=a.data, filename=a.filename, declared_type=a.content_type, source="email", inbound_id=row.id, provider_id=row.provider_id
            )
        body = (row.new_text or "").strip()
        text_ev = None
        if body:
            text_ev = evidence.store_text(
                s,
                workspace_id=conv.workspace_id,
                text=body,
                label=f"Email from {em.from_address} - {em.subject}"[:300],
                source="email",
                inbound_id=row.id,
                provider_id=row.provider_id,
            )
        if not open_reqs:
            row.status = "closed_target"
            row.processed_at = clock.now(s)
            audit.log(s, actor="system", action="reply_to_closed_request", workspace_id=conv.workspace_id, inbound=row.id)
            for r in reqs:
                add_comment(
                    s, r, author="system", kind="late_reply",
                    body=f"{em.from_address} replied after this request was {states.LABELS[r.state].lower()}. The message and {len(files)} file(s) were stored; nothing was sent back.",
                    payload={"inbound_id": row.id, "file_ids": [f.id for f in files]},
                )
            return
        if len(open_reqs) == 1:  # nothing to classify for attribution: show it as checking now
            _mark_received(s, row, open_reqs[0], [f.id for f in files])
        file_ids = [f.id for f in files]
        text_id = text_ev.id if text_ev else None
        open_ids = [r.id for r in open_reqs]
        call = _classify_call(s, em, open_reqs, files, body) if (len(open_reqs) > 1 or body or files) else None
    classification = None
    if call is not None:
        try:
            classification = llm.run(call, ReplyClassification)
        except llm.LLMError as e:
            with session_scope() as s:
                for rid in open_ids:
                    r = s.get(Request, rid)
                    if r:
                        add_comment(s, r, author="system", kind="error", body=f"Couldn't classify the reply ({e}); checking all attachments against every item instead.")
    with session_scope() as s:
        row = s.get(InboundMessage, inbound_id)
        assert row is not None
        row.classification = classification.model_dump() if classification else {}
        _apply_classification(s, row, open_ids, file_ids, text_id, classification, call.context if call else {})
        row.status = "processed"
        row.processed_at = clock.now(s)


def _mark_received(s: Session, row: InboundMessage, r: Request, file_ids: list[int]) -> None:
    """Show the reply in this request's thread and move it to checking."""
    if not row.sender_is_owner:
        add_flag(r, "unknown_sender", f"A reply came from {row.from_address}, who isn't a listed provider. Its content was accepted and checked.")
    add_comment(
        s, r, author="provider", kind="provider_email",
        body=(row.new_text or "").strip()[:4000] or "(no message text)",
        payload={"inbound_id": row.id, "from": row.from_address, "subject": row.subject, "file_ids": file_ids, "sender_is_owner": row.sender_is_owner},
    )
    if r.state != states.CHECKING:
        states.transition(s, r, states.CHECKING, actor="provider", reason="reply received", actor_detail=row.from_address)


def _conv_request_ids(session: Session, conv: Conversation | None) -> list[int]:
    if conv is None:
        return []
    return list(session.scalars(select(ConversationRequest.request_id).where(ConversationRequest.conversation_id == conv.id)).all())


def _classify_call(session: Session, em: InboundEmail, reqs: list[Request], files: list[EvidenceFile], body: str) -> llm.LLMCall:
    refs = {f"Q{i + 1}": r.id for i, r in enumerate(reqs)}
    lines = ["Requests in this thread:"]
    for ref, rid in refs.items():
        r = session.get(Request, rid)
        assert r is not None
        v = current_version(session, r)
        items = "; ".join(i.description for i in v.items) if v else ""
        lines.append(f"- {ref}: {request_label(r)} -- {items}")
    lines.append("\nAttachments:")
    for f in files:
        status = "readable" if f.extraction_status == "ok" else f"unreadable ({f.unreadable_reason})"
        first = ""
        segs = (f.extraction or {}).get("segments") or []
        if segs:
            first = segs[0]["text"][:300].replace("\n", " ")
        lines.append(f'- {evidence.eid(f)}: "{f.filename}" [{status}] begins: {first}')
    if not files:
        lines.append("- (none)")
    lines += ["", f"<provider_message from=\"{em.from_address}\" subject=\"{em.subject}\">", evidence._neutralize(body or "(empty)"), "</provider_message>"]
    return llm.LLMCall(
        step="classify",
        system=prompts.CLASSIFY,
        content=[{"type": "text", "text": "\n".join(lines)}],
        output=ReplyClassification,
        tier="fast",
        context={"refs": refs, "file_ids": [f.id for f in files], "body": body},
    )


def _apply_classification(
    s: Session,
    row: InboundMessage,
    open_ids: list[int],
    file_ids: list[int],
    text_id: int | None,
    cl: ReplyClassification | None,
    ctx: dict[str, Any],
) -> None:
    from .checking import enqueue_check

    refs: dict[str, int] = ctx.get("refs") or {}
    now = clock.now(s)
    single = len(open_ids) == 1

    def assign(fid: int, rid: int, method: str) -> None:
        if not s.scalars(select(EvidenceAssignment).where(EvidenceAssignment.file_id == fid, EvidenceAssignment.request_id == rid)).first():
            s.add(EvidenceAssignment(file_id=fid, request_id=rid, method=method, created_at=now))

    # attachments (and files nested in attached .eml)
    all_files = s.scalars(select(EvidenceFile).where(EvidenceFile.inbound_id == row.id, EvidenceFile.kind == "file")).all()
    by_parent: dict[int, list[int]] = {}
    for f in all_files:
        if f.parent_file_id:
            by_parent.setdefault(f.parent_file_id, []).append(f.id)
    explicit: dict[int, list[int]] = {}
    if cl and not single:
        for a in cl.attachment_assignments:
            try:
                fid = int(a.evidence_id.lstrip("E"))
            except ValueError:
                continue
            explicit[fid] = [refs[r] for r in a.request_refs if r in refs]
    # Which requests is this reply about? In a multi-request thread, only those the classifier
    # names (attachments, answers, questions, closing). If it can't tell, every open request.
    touched: list[int] = list(open_ids)
    if cl and not single:
        named = {rid for ids in explicit.values() for rid in ids}
        named |= {refs[r] for r in [*cl.answered_refs, *cl.closing_refs, *[q.request_ref or "" for q in cl.questions]] if r in refs}
        unplaced = any(not explicit.get(f.id if not f.parent_file_id else f.parent_file_id) for f in all_files)
        if named and not unplaced:
            touched = [rid for rid in open_ids if rid in named]
    for f in all_files:
        top = f.id if not f.parent_file_id else f.parent_file_id
        targets = explicit.get(top) or touched
        for rid in targets:
            assign(f.id, rid, "single" if single else ("classifier" if explicit.get(top) else "unassigned_broadcast"))
    # message text: to each request the reply is about (each check judges relevance)
    if text_id:
        for rid in touched:
            assign(text_id, rid, "single" if single else "thread")
    s.flush()
    if not single:
        for rid in touched:
            r = s.get(Request, rid)
            if r is not None:
                _mark_received(s, row, r, file_ids)

    sender = row.from_address or ""
    closing_ok = bool(
        cl
        and cl.closes_request
        and cl.closing_quote
        and row.sender_is_owner
        and evidence._contains(row.new_text or "", cl.closing_quote)
    )
    if cl and cl.closes_request and not closing_ok:
        for rid in open_ids:
            r = s.get(Request, rid)
            if r:
                add_comment(s, r, author="system", kind="note", body="The reply looked like it might close the request, but the closing words weren't found in the sender's own message (or the sender isn't a listed provider), so the request stays open.")
    if closing_ok:
        close_ids = [refs[r] for r in cl.closing_refs if r in refs] or touched
        for rid in close_ids:
            r = s.get(Request, rid)
            if r is None:
                continue
            for o in r.owners:
                if o.provider.email == sender and o.closed_at is None:
                    o.closed_at = now
            audit.log(s, actor="provider", actor_detail=sender, action="provider_closed", workspace_id=r.workspace_id, request_id=r.id, quote=cl.closing_quote)
    if cl and cl.mentions_attachments and not file_ids:
        for rid in touched:
            r = s.get(Request, rid)
            if r:
                add_flag(r, "missing_attachments", "The provider's reply says files are attached, but none arrived.")
                add_comment(s, r, author="system", kind="note", body="The reply mentions attachments, but the email had none.")

    # questions
    if cl:
        for q in cl.questions:
            rid = refs.get(q.request_ref or "") or (open_ids[0] if single else None)
            targets = [rid] if rid else open_ids[:1]
            for t in targets:
                pq = ProviderQuestion(
                    request_id=t, inbound_id=row.id, provider_id=row.provider_id, question=q.question, status="new", created_at=now
                )
                s.add(pq)
                s.flush()
                jobs.enqueue(s, "answer_question", f"question:{pq.id}", {"id": pq.id})

    # check every request the reply is about
    for rid in touched:
        r = s.get(Request, rid)
        if r is not None:
            enqueue_check(s, r, trigger=f"email {row.id}", substantive=bool(file_ids) or bool(cl is None or cl.substantive), inbound_id=row.id)


# --------------------------------------------------------------------------- provider questions


@jobs.handler("answer_question")
def answer_question_job(payload: dict) -> None:
    from .scoping import _checklist_json

    with session_scope() as s:
        pq = s.get(ProviderQuestion, payload["id"])
        if pq is None or pq.status != "new":
            return
        req = s.get(Request, pq.request_id)
        assert req is not None
        v = current_version(s, req)
        assert v is not None
        notes = "\n".join(v.notes or [])
        content = (
            f"Confirmed checklist:\n{_checklist_json(v)}\n\nRequester notes:\n{notes or '(none)'}\n\n"
            f"<untrusted>\nProvider question: {evidence._neutralize(pq.question)}\n</untrusted>"
        )
        call = llm.LLMCall(
            step="answer_question",
            system=prompts.ANSWER_QUESTION,
            content=[{"type": "text", "text": content}],
            output=QuestionAnswer,
            tier="strong",
            context={"question": pq.question, "item_keys": [i.key for i in v.items]},
        )
    try:
        qa = llm.run(call, QuestionAnswer)
    except llm.LLMError:
        qa = QuestionAnswer(in_scope=False, answer=None, basis_item_keys=[], reason="model error")
    with session_scope() as s:
        pq = s.get(ProviderQuestion, payload["id"])
        assert pq is not None
        req = s.get(Request, pq.request_id)
        assert req is not None
        now = clock.now(s)
        if qa.in_scope and qa.answer:
            pq.status = "answered_from_scope"
            pq.answer = qa.answer
            pq.basis = qa.basis_item_keys
            pq.answered_at = now
            add_comment(
                s, req, author="agent", kind="question_answered",
                body=f"The provider asked: “{pq.question}”. The confirmed checklist covers this, so I'll reply: “{qa.answer}”",
                payload={"question_id": pq.id, "basis": qa.basis_item_keys},
            )
            audit.log(s, actor="agent", action="question_answered_from_scope", workspace_id=req.workspace_id, request_id=req.id, question=pq.question, answer=qa.answer)
            from .followups import schedule_provider_cycle

            schedule_provider_cycle(s, req, now)
        else:
            pq.status = "waiting_requester"
            add_comment(
                s, req, author="agent", kind="question_for_requester",
                body=f"The provider asked: “{pq.question}”. The checklist doesn't answer this, so I need you to. Your answer will be emailed to them.",
                payload={"question_id": pq.id, "reason": qa.reason},
            )
            audit.log(s, actor="agent", action="question_escalated_to_requester", workspace_id=req.workspace_id, request_id=req.id, question=pq.question, reason=qa.reason)


def answer_from_requester(session: Session, user_email: str, req: Request, question_id: int, answer: str) -> None:
    from .followups import schedule_provider_cycle

    pq = session.get(ProviderQuestion, question_id)
    if pq is None or pq.request_id != req.id or pq.status != "waiting_requester":
        raise ValueError("no open question")
    pq.status = "answered_by_requester"
    pq.answer = answer
    pq.answered_at = clock.now(session)
    audit.log(session, actor="requester", actor_detail=user_email, action="question_answered_by_requester", workspace_id=req.workspace_id, request_id=req.id, question=pq.question, answer=answer)
    add_comment(session, req, author="requester", kind="question_answer", body=answer, payload={"question_id": pq.id})
    schedule_provider_cycle(session, req, clock.now(session), immediate=True)


def assign_unmatched(session: Session, inbound: InboundMessage, conversation_id: int) -> None:
    inbound.status = "received"
    jobs.enqueue(session, "assign_inbound", f"assign:{inbound.id}:{conversation_id}", {"id": inbound.id, "conversation_id": conversation_id})


@jobs.handler("assign_inbound")
def assign_job(payload: dict) -> None:
    process(payload["id"], forced_conversation_id=payload["conversation_id"])


def owners_of(session: Session, req: Request) -> list[RequestOwner]:
    return list(req.owners)

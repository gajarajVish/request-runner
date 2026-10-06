"""Reply matching, duplicate inbound delivery, uncertain outbound delivery."""

from __future__ import annotations

import base64
import json

from sqlalchemy import select

from app.db import session_scope
from app.email.adapters import SendResult
from app.models import (
    Check,
    Comment,
    ConversationRequest,
    EvidenceAssignment,
    EvidenceFile,
    InboundMessage,
    OutboundMessage,
    Request,
)
from app.workflow import actions, inbound, states

from .conftest import make_eml, user
from .helpers import check_out, cite, confirmed_request, evid, reply_to_of, run_jobs, verdict


def _conv_id(rid: int) -> int:
    with session_scope() as s:
        return s.scalars(select(ConversationRequest.conversation_id).where(ConversationRequest.request_id == rid)).first()


# --------------------------------------------------------------------------- matching


def test_token_and_header_conflict_goes_to_unmatched_then_requester_assigns(env):
    a = confirmed_request(env, title="Request A")
    b = confirmed_request(env, title="Request B")
    reply_a, _ = reply_to_of(a)
    _, mid_b = reply_to_of(b)
    env.llm.on("check", lambda c: check_out([verdict("i1", "not_met"), verdict("i2", "not_met")]))
    iid, created = inbound.ingest_raw(make_eml(to=reply_a, body="Which one is this for?", headers={"In-Reply-To": mid_b, "References": mid_b}))
    assert created
    run_jobs()
    with session_scope() as s:
        row = s.get(InboundMessage, iid)
        assert row.status == "unmatched"
        assert sorted(row.suggested_conversation_ids) == sorted([_conv_id(a), _conv_id(b)])
        assert any("headers point to" in n for n in row.match_notes)
        assert s.scalars(select(EvidenceAssignment)).first() is None
        assert s.get(Request, a).state == states.WAITING_PROVIDER
        assert s.get(Request, b).state == states.WAITING_PROVIDER

    with session_scope() as s:
        inbound.assign_unmatched(s, s.get(InboundMessage, iid), _conv_id(a))
    run_jobs()
    with session_scope() as s:
        row = s.get(InboundMessage, iid)
        assert row.status == "processed" and row.match_method == "requester"
        assigned = s.scalars(select(EvidenceAssignment.request_id)).all()
        assert set(assigned) == {a}
        assert s.scalars(select(Check).where(Check.request_id == a)).first() is not None
        assert s.scalars(select(Check).where(Check.request_id == b)).first() is None


def test_sender_address_alone_never_assigns(env):
    rid = confirmed_request(env)
    iid, _ = inbound.ingest_raw(make_eml(to="sam@example.com", frm="Jordan Lee <jordan@example.com>", body="Here you go"))
    run_jobs()
    with session_scope() as s:
        row = s.get(InboundMessage, iid)
        assert row.status == "unmatched" and row.conversation_id is None
        assert row.suggested_conversation_ids == [_conv_id(rid)]
        assert s.scalars(select(EvidenceFile)).first() is None
        assert s.get(Request, rid).state == states.WAITING_PROVIDER


def test_headers_alone_match_when_token_missing(env):
    rid = confirmed_request(env)
    _, mid = reply_to_of(rid)
    env.llm.on("check", lambda c: check_out([verdict("i1", "not_met"), verdict("i2", "not_met")]))
    iid, _ = inbound.ingest_raw(make_eml(to="someone-else@example.com", body="Working on it.", headers={"In-Reply-To": mid}))
    run_jobs()
    with session_scope() as s:
        row = s.get(InboundMessage, iid)
        assert row.match_method == "headers" and row.status == "processed"


# --------------------------------------------------------------------------- duplicate delivery


def _counts(s):
    return (
        s.query(InboundMessage).count(),
        s.query(EvidenceFile).count(),
        s.query(EvidenceAssignment).count(),
        s.query(Check).count(),
        s.query(OutboundMessage).count(),
    )


def test_same_message_twice_is_processed_once(env):
    from .conftest import STARTER

    rid = confirmed_request(env)
    reply_to, _ = reply_to_of(rid)
    cert = (STARTER / "part1/A_msa-and-insurance/acme-logistics-llc_certificate-of-insurance_2026-2027.pdf").read_bytes()
    env.llm.on("check", lambda c: check_out([verdict("i1", "met", [cite(evid(c, "certificate"), "Policy period 03/01/2026 to 03/01/2027", page=1)]), verdict("i2", "not_met", missing=["Signed MSA"])]))
    raw = make_eml(to=reply_to, body="Certificate attached.", attachments=[("certificate.pdf", cert, "application/pdf")], message_id="<dup-1@example.com>")
    first = inbound.ingest_raw(raw)
    run_jobs()
    run_jobs(advance_seconds=120)  # the follow-up goes out
    with session_scope() as s:
        before = _counts(s)
        count_before = s.get(Request, rid).auto_contact_count
    second = inbound.ingest_raw(raw)
    assert second == (first[0], False)
    run_jobs()
    run_jobs(advance_seconds=120)
    with session_scope() as s:
        assert _counts(s) == before
        assert s.get(Request, rid).auto_contact_count == count_before == 1


def test_postmark_webhook_retry_is_deduplicated_and_authenticated(env, monkeypatch):
    from fastapi.testclient import TestClient

    from app.config import get_settings
    from app.main import create_app

    monkeypatch.setenv("EMAIL_INBOUND_BASIC_AUTH", "pm:secret")
    get_settings.cache_clear()
    rid = confirmed_request(env)
    reply_to, _ = reply_to_of(rid)
    env.llm.on("check", lambda c: check_out([verdict("i1", "not_met"), verdict("i2", "not_met")]))
    payload = {
        "MessageID": "pm-123",
        "FromFull": {"Email": "jordan@example.com", "Name": "Jordan Lee"},
        "ToFull": [{"Email": reply_to}],
        "Subject": "Re: request",
        "TextBody": "Still looking for the MSA.",
        "Headers": [{"Name": "Message-ID", "Value": "<pm-123@example.com>"}],
        "Attachments": [],
    }
    client = TestClient(create_app())
    assert client.post("/webhooks/postmark/inbound", content=json.dumps(payload)).status_code == 401
    auth = {"Authorization": "Basic " + base64.b64encode(b"pm:wrong").decode()}
    assert client.post("/webhooks/postmark/inbound", content=json.dumps(payload), headers=auth).status_code == 401
    auth = {"Authorization": "Basic " + base64.b64encode(b"pm:secret").decode()}
    r1 = client.post("/webhooks/postmark/inbound", content=json.dumps(payload), headers=auth).json()
    r2 = client.post("/webhooks/postmark/inbound", content=json.dumps(payload), headers=auth).json()
    assert r1["duplicate"] is False and r2["duplicate"] is True and r1["inbound_id"] == r2["inbound_id"]
    run_jobs()
    with session_scope() as s:
        assert s.query(InboundMessage).count() == 1
        assert s.query(Check).count() == 1
        assert s.get(InboundMessage, r1["inbound_id"]).match_method == "token"


# --------------------------------------------------------------------------- uncertain send


def test_uncertain_send_is_not_retried_and_requester_can_resend(env):
    env.sender.script = [SendResult("uncertain", error="timeout after request was sent")]
    rid = confirmed_request(env)
    run_jobs(advance_seconds=3600)
    assert env.sender.sent == []  # never resent automatically
    with session_scope() as s:
        msg = s.scalars(select(OutboundMessage).where(OutboundMessage.request_id == rid)).one()
        assert msg.status == "uncertain" and msg.attempts == 1
        assert s.scalars(select(Comment).where(Comment.request_id == rid, Comment.kind == "email_uncertain")).first() is not None
        clone = actions.resend(s, user(s), msg)
        clone_id = clone.id
        assert clone.message_id != msg.message_id
    run_jobs()
    assert len(env.sender.sent) == 1
    with session_scope() as s:
        assert s.get(OutboundMessage, clone_id).status == "sent"
        assert s.get(Request, rid).auto_contact_count == 0  # the initial email never counts


def test_crash_mid_send_becomes_uncertain(env):
    rid = confirmed_request(env, send=False)
    with session_scope() as s:
        req = s.get(Request, rid)
        draft = s.scalars(select(OutboundMessage).where(OutboundMessage.request_id == rid)).one()
        from app.workflow import scoping

        scoping.send_draft(s, user(s), req, draft.id)
        draft.status = "sending"  # as if the process died after handing it to the provider
    run_jobs()
    assert env.sender.sent == []
    with session_scope() as s:
        assert s.scalars(select(OutboundMessage).where(OutboundMessage.request_id == rid)).one().status == "uncertain"


def test_plus_address_of_the_provider_counts_as_the_provider(env):
    assert inbound.same_mailbox("jordan+acme@example.com", "Jordan@example.com")
    assert not inbound.same_mailbox("jordan@example.com", "jordan@other.com")
    assert not inbound.same_mailbox("jordanx@example.com", "jordan@example.com")

    rid = confirmed_request(env)
    reply, _ = reply_to_of(rid)
    env.llm.on("check", lambda c: check_out([verdict("i1", "not_met"), verdict("i2", "not_met")]))
    iid, _ = inbound.ingest_raw(make_eml(to=reply, frm="Jordan Lee <jordan+work@example.com>", body="On it."))
    run_jobs()
    with session_scope() as s:
        assert s.get(InboundMessage, iid).sender_is_owner
        assert not any(f["code"] == "unknown_sender" for f in s.get(Request, rid).flags or [])

    iid, _ = inbound.ingest_raw(make_eml(to=reply, frm="Someone <someone@example.com>", body="Forwarded to me."))
    run_jobs()
    with session_scope() as s:
        assert not s.get(InboundMessage, iid).sender_is_owner
        assert any(f["code"] == "unknown_sender" for f in s.get(Request, rid).flags or [])

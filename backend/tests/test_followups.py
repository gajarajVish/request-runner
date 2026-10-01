"""Follow-up limit, batching, debounce, overdue notices and escalation."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import select

from app import clock
from app.db import session_scope
from app.models import Comment, OutboundMessage, Request
from app.workflow import actions, inbound, states
from app.workflow.followups import enqueue_sweep

from .conftest import make_eml, user
from .helpers import confirmed_request, reply_to_of, run_jobs


def at(dt: datetime) -> None:
    clock.set_fixed(dt)


def sweep() -> None:
    with session_scope() as s:
        enqueue_sweep(s)
    run_jobs()


def provider_msgs(kind: str | None = None) -> list[OutboundMessage]:
    with session_scope() as s:
        q = select(OutboundMessage).where(OutboundMessage.to == ["jordan@example.com"], OutboundMessage.kind != "initial")
        rows = s.scalars(q.order_by(OutboundMessage.id)).all()
        for r in rows:
            s.expunge(r)
    return [r for r in rows if kind is None or r.kind == kind]


def req(rid) -> Request:
    with session_scope() as s:
        r = s.get(Request, rid)
        s.expunge(r)
        return r


def incomplete_reply(rid, body="Here's part of it."):
    reply_to, _ = reply_to_of(rid)
    inbound.ingest_raw(make_eml(to=reply_to, body=body))
    run_jobs()


def test_three_automatic_contacts_then_handback_never_a_fourth(env):
    rid = confirmed_request(env)  # the fake checker says nothing is met
    for n in range(1, 4):
        incomplete_reply(rid, body=f"Attempt {n}")
        run_jobs(advance_seconds=120)
        assert len(provider_msgs("followup")) == n
        assert req(rid).auto_contact_count == n
    incomplete_reply(rid, body="Attempt 4")
    run_jobs(advance_seconds=3600)
    assert len(provider_msgs()) == 3
    r = req(rid)
    assert r.state == states.HANDED_BACK and r.handback_reason == "follow_up_limit"
    # time passing (reminders, overdue) still can't contact the provider again
    at(datetime(2026, 10, 25, 15, 0))
    sweep()
    assert len(provider_msgs()) == 3
    assert req(rid).auto_contact_count == 3


def test_due_soon_items_for_one_provider_are_batched_into_one_reminder(env):
    a = confirmed_request(env, title="Item A", due="2026-10-05")
    b = confirmed_request(env, title="Item B", due="2026-10-06")
    at(datetime(2026, 10, 4, 14, 0))
    sweep()
    msgs = provider_msgs()
    assert len(msgs) == 1 and msgs[0].kind == "reminder"
    assert sorted(msgs[0].counted_request_ids) == sorted([a, b])
    assert "Item A" in msgs[0].text_body and "Item B" in msgs[0].text_body
    assert req(a).auto_contact_count == 1 and req(b).auto_contact_count == 1
    sweep()  # same cycle: nothing repeats
    run_jobs(advance_seconds=3600)
    sweep()
    assert len(provider_msgs()) == 1


def test_replies_close_together_produce_one_follow_up(env):
    rid = confirmed_request(env)
    incomplete_reply(rid, body="First file coming.")
    run_jobs(advance_seconds=30)
    incomplete_reply(rid, body="And another note.")
    run_jobs(advance_seconds=40)  # 70s after the first reply, 40s after the second
    assert provider_msgs() == []
    run_jobs(advance_seconds=60)
    assert len(provider_msgs("followup")) == 1
    assert req(rid).auto_contact_count == 1
    run_jobs(advance_seconds=600)
    assert len(provider_msgs()) == 1


def _with_backup(rid, backup):
    with session_scope() as s:
        s.get(Request, rid).backup_email = backup


def test_overdue_then_escalation_to_backup_once_per_cycle(env):
    rid = confirmed_request(env, due="2026-10-02")  # Friday
    _with_backup(rid, "leo@example.com")
    at(datetime(2026, 10, 3, 15, 0))  # Saturday: the day after the due date
    sweep()
    overdue = provider_msgs("overdue")
    assert len(overdue) == 1 and "past their due date" in overdue[0].text_body
    assert req(rid).auto_contact_count == 1

    at(datetime(2026, 10, 5, 15, 0))  # Monday: one business day after
    sweep()
    with session_scope() as s:
        assert s.scalars(select(OutboundMessage).where(OutboundMessage.kind == "escalation")).first() is None

    at(datetime(2026, 10, 6, 15, 0))  # Tuesday: two business days after the overdue notice
    sweep()
    sweep()
    at(datetime(2026, 10, 9, 15, 0))
    sweep()
    with session_scope() as s:
        esc = s.scalars(select(OutboundMessage).where(OutboundMessage.kind == "escalation")).all()
        assert len(esc) == 1 and esc[0].to == ["leo@example.com"]
        assert esc[0].counted_request_ids == []  # escalation never uses the provider's counter
        notice = s.scalars(select(OutboundMessage).where(OutboundMessage.kind == "requester_notice")).all()
        assert len(notice) == 1 and notice[0].to == ["sam@example.com"]
        assert "leo@example.com" in notice[0].text_body
    assert len(provider_msgs("overdue")) == 1

    # a new due date starts a new cycle
    with session_scope() as s:
        actions.change_due_date(s, user(s), s.get(Request, rid), date(2026, 10, 12))
    at(datetime(2026, 10, 13, 15, 0))
    sweep()
    at(datetime(2026, 10, 15, 15, 0))
    sweep()
    with session_scope() as s:
        assert len(s.scalars(select(OutboundMessage).where(OutboundMessage.kind == "escalation")).all()) == 2


def test_no_backup_notifies_requester_only(env):
    rid = confirmed_request(env, due="2026-10-02")
    at(datetime(2026, 10, 3, 15, 0))
    sweep()
    at(datetime(2026, 10, 6, 15, 0))
    sweep()
    with session_scope() as s:
        assert s.scalars(select(OutboundMessage).where(OutboundMessage.kind == "escalation")).first() is None
        notice = s.scalars(select(OutboundMessage).where(OutboundMessage.kind == "requester_notice")).one()
        assert notice.to == ["sam@example.com"] and "no backup owner" in notice.text_body
        assert s.scalars(select(Comment).where(Comment.request_id == rid, Comment.kind == "escalation")).one()


def test_complete_request_is_not_escalated(env):
    from .helpers import MSA_ITEMS, check_out, cite, evid, verdict

    rid = confirmed_request(env, items=[MSA_ITEMS[0]], due="2026-10-02")
    _with_backup(rid, "leo@example.com")
    from .conftest import STARTER

    cert = (STARTER / "part1/A_msa-and-insurance/acme-logistics-llc_certificate-of-insurance_2026-2027.pdf").read_bytes()
    env.llm.on("check", lambda c: check_out([verdict("i1", "met", [cite(evid(c, "cert"), "Policy period 03/01/2026 to 03/01/2027", page=1)])]))
    reply_to, _ = reply_to_of(rid)
    inbound.ingest_raw(make_eml(to=reply_to, body="Attached.", attachments=[("cert.pdf", cert, "application/pdf")]))
    run_jobs()
    assert req(rid).state == states.COMPLETE
    at(datetime(2026, 10, 9, 15, 0))
    sweep()
    assert provider_msgs() == []
    with session_scope() as s:
        assert s.scalars(select(OutboundMessage).where(OutboundMessage.kind == "escalation")).first() is None

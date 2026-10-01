"""Shared items (R-18) and dependent items (R-12 -> R-11), set up through the import path."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import session_scope
from app.models import Conversation, ImportBatch, Provider, Request, RequestOwner
from app.workflow import hub, imports, inbound, states
from app.workflow.outbox import reply_address

from .conftest import make_eml, user
from .helpers import check_out, cite, evid, run_jobs, verdict

HEADER = "request_id,title,instructions,due_date,owner_name,owner_email,backup_email"
R18 = 'R-18,Credit memos,"All credit memos over $5,000 issued in Q3 2026, with the reason and approver for each.",2026-10-19,Carlos Ruiz; Priya Shah,carlos@example.com; priya@example.com,leo@example.com'
R11 = 'R-11,Leavers Q3,"A list of everyone who left from July 1 to September 30 2026, with last working day.",2026-10-14,Aisha Karim,aisha@example.com,dan@example.com'
R12 = 'R-12,Access removal for leavers,"For each person on the R-11 list, the date their system access was removed. If any removal took more than 3 business days, explain why.",2026-10-28,Mei Lin,mei@example.com,aisha@example.com'


def import_and_send(*rows: str, mode: dict[str, str] | None = None) -> None:
    data = ("\n".join([HEADER, *rows]) + "\n").encode()
    with session_scope() as s:
        bid = imports.start_import(s, user(s), list_name="PBC", filename="pbc.csv", data=data).id
    run_jobs()
    with session_scope() as s:
        b = s.get(ImportBatch, bid)
        for row in b.rows:
            if mode and row.external_id in mode:
                imports.edit_row(s, user(s), b, row, {"ownership_mode": mode[row.external_id]})
        imports.apply(s, user(s), b)
        imports.send_all(s, user(s), b)
    run_jobs()


def rid_of(ext: str) -> int:
    with session_scope() as s:
        return s.scalars(select(Request.id).where(Request.external_id == ext)).one()


def reply_to_for(email: str) -> str:
    with session_scope() as s:
        p = s.scalars(select(Provider).where(Provider.email == email)).one()
        conv = s.scalars(select(Conversation).where(Conversation.provider_id == p.id).order_by(Conversation.id.desc())).first()
        return reply_address(conv.reply_token)


def met_from_message(quote: str, sender: str):
    return lambda c: check_out([verdict("i1", "met", [cite(evid(c, f"Email from {sender}"), quote)])])


def state_and_flags(ext: str):
    with session_scope() as s:
        r = s.scalars(select(Request).where(Request.external_id == ext)).one()
        return r.state, {f["code"] for f in r.flags or []}


CARLOS_TEXT = "Q3 credit memos over $5,000: CM-301 $7,200 pricing error approved by Leo Park."
PRIYA_TEXT = "From AP: CM-305 $6,100 duplicate billing approved by Leo Park."


def test_shared_item_either_owner_can_satisfy(env):
    import_and_send(R18)
    rid = rid_of("R-18")
    with session_scope() as s:
        assert len(s.get(Request, rid).owners) == 2
    env.llm.on("check", met_from_message("CM-305 $6,100 duplicate billing approved by Leo Park", "priya@"))
    inbound.ingest_raw(make_eml(to=reply_to_for("priya@example.com"), frm="Priya Shah <priya@example.com>", body=PRIYA_TEXT))
    run_jobs()
    assert state_and_flags("R-18")[0] == states.COMPLETE


def test_shared_item_both_must_respond_waits_for_each_owner(env):
    import_and_send(R18, mode={"R-18": "all"})
    rid = rid_of("R-18")
    env.llm.on("check", met_from_message("CM-301 $7,200 pricing error approved by Leo Park", "carlos@"))
    inbound.ingest_raw(make_eml(to=reply_to_for("carlos@example.com"), frm="Carlos Ruiz <carlos@example.com>", body=CARLOS_TEXT))
    run_jobs()
    st, flags = state_and_flags("R-18")
    assert st == states.WAITING_PROVIDER and "waiting_on_owner" in flags

    env.llm.on("check", met_from_message("CM-305 $6,100 duplicate billing approved by Leo Park", "priya@"))
    inbound.ingest_raw(make_eml(to=reply_to_for("priya@example.com"), frm="Priya Shah <priya@example.com>", body=PRIYA_TEXT))
    run_jobs()
    st, flags = state_and_flags("R-18")
    assert st == states.COMPLETE and "waiting_on_owner" not in flags
    with session_scope() as s:
        assert all(o.closed_at is None for o in s.scalars(select(RequestOwner).where(RequestOwner.request_id == rid)))


def test_co_owner_hub_never_shows_the_other_owners_files(env):
    from app.main import create_app

    import_and_send(R18, mode={"R-18": "all"})
    with session_scope() as s:
        carlos = s.scalars(select(Provider).where(Provider.email == "carlos@example.com")).one()
        priya = s.scalars(select(Provider).where(Provider.email == "priya@example.com")).one()
        t_carlos, t_priya = hub.issue_token(s, carlos), hub.issue_token(s, priya)
    client = TestClient(create_app())
    up = client.post(f"/api/hub/{t_carlos}/upload", files={"file": ("carlos-memos.csv", b"memo,amount\nCM-301,7200\n", "text/csv")}, data={"request_id": str(rid_of("R-18"))})
    assert up.status_code == 200 and up.json()["accepted"]
    run_jobs()
    mine = client.get(f"/api/hub/{t_carlos}").json()["items"][0]
    theirs = client.get(f"/api/hub/{t_priya}").json()["items"][0]
    assert [f["filename"] for f in mine["submitted"]] == ["carlos-memos.csv"]
    assert theirs["submitted"] == [] and theirs["shared"] is True
    assert "carlos-memos" not in str(theirs)


def test_dependent_waits_for_prerequisite_then_completes(env):
    import_and_send(R11, R12)
    r11, r12 = rid_of("R-11"), rid_of("R-12")
    with session_scope() as s:
        from app.workflow.common import dependencies

        assert [d.id for d in dependencies(s, s.get(Request, r12))] == [r11]

    calls = []

    def check(c):
        calls.append(c.context["request_id"])
        if c.context["request_id"] == r12:
            return check_out([verdict("i1", "met", [cite(evid(c, "mei@"), "Jordan Pike access removed 2026-08-14")])])
        return check_out([verdict("i1", "met", [cite(evid(c, "aisha@"), "Jordan Pike, last day 2026-08-13")])])

    env.llm.on("check", check)
    inbound.ingest_raw(make_eml(to=reply_to_for("mei@example.com"), frm="Mei Lin <mei@example.com>", body="Jordan Pike access removed 2026-08-14 (1 business day)."))
    run_jobs()
    st, flags = state_and_flags("R-12")
    assert st == states.WAITING_PROVIDER and "waiting_on_dependency" in flags

    inbound.ingest_raw(make_eml(to=reply_to_for("aisha@example.com"), frm="Aisha Karim <aisha@example.com>", body="Leavers: Jordan Pike, last day 2026-08-13."))
    run_jobs()
    assert state_and_flags("R-11")[0] == states.COMPLETE
    st, flags = state_and_flags("R-12")
    assert st == states.COMPLETE and "waiting_on_dependency" not in flags
    assert calls.count(r12) == 2  # rechecked when the prerequisite completed


def test_dependent_check_sees_prerequisite_evidence(env):
    import_and_send(R11, R12)
    r12 = rid_of("R-12")
    seen = {}

    def check(c):
        text = "\n".join(b.get("text", "") for b in c.content if b["type"] == "text")
        seen[c.context["request_id"]] = text
        return check_out([verdict("i1", "not_met")])

    env.llm.on("check", check)
    inbound.ingest_raw(make_eml(to=reply_to_for("aisha@example.com"), frm="Aisha Karim <aisha@example.com>", body="Leavers: Jordan Pike, last day 2026-08-13."))
    run_jobs()
    inbound.ingest_raw(make_eml(to=reply_to_for("mei@example.com"), frm="Mei Lin <mei@example.com>", body="Access removed 2026-08-14."))
    run_jobs()
    assert "This request depends on: R-11 Leavers Q3" in seen[r12]
    assert "Jordan Pike, last day 2026-08-13" in seen[r12]
    assert "prerequisite request evidence" in seen[r12]

"""Part 2: importing the request list, review, batch send, re-import."""

from __future__ import annotations

from sqlalchemy import select

from app.db import session_scope
from app.models import ImportBatch, OutboundMessage, Request, RequestDependency
from app.workflow import imports, states

from .conftest import STARTER, user
from .helpers import run_jobs

CSV = (STARTER / "requests.csv").read_bytes()


def vague_r25(env):
    """The fake marks rows vague by word count; make R-25 vague the way the real model would."""
    default = env.llm._default_scope_row

    def handler(call):
        out = default(call)
        if call.context["row"]["request_id"] == "R-25":
            out.update(vague=True, vague_reason="'the usual stuff' doesn't say what to send", items=[])
        return out

    env.llm.on("scope_row", handler)


def upload(data: bytes, name: str = "Q3 audit PBC") -> int:
    with session_scope() as s:
        bid = imports.start_import(s, user(s), list_name=name, filename="requests.csv", data=data).id
    run_jobs()
    return bid


def rows(bid) -> dict[str, dict]:
    with session_scope() as s:
        b = s.get(ImportBatch, bid)
        return {r.external_id: imports.row_view(r) for r in b.rows}


def codes(row) -> set[str]:
    return {f["code"] for f in row["flags"]}


def apply(bid) -> dict:
    with session_scope() as s:
        return imports.apply(s, user(s), s.get(ImportBatch, bid))


def send_all(bid) -> int:
    with session_scope() as s:
        n = imports.send_all(s, user(s), s.get(ImportBatch, bid))
    run_jobs()
    return n


def by_ext(ext) -> Request:
    with session_scope() as s:
        r = s.scalars(select(Request).where(Request.external_id == ext)).one()
        s.expunge(r)
        return r


def edit_csv(fn) -> bytes:
    lines = CSV.decode().splitlines()
    return ("\n".join(fn(lines)) + "\n").encode()


def test_review_flags_the_tricky_rows(env):
    vague_r25(env)
    bid = upload(CSV)
    r = rows(bid)
    with session_scope() as s:
        assert s.get(ImportBatch, bid).status == "review"
    assert r["R-08"]["action"] == "duplicate" and r["R-08"]["merged_into"] == "R-07"
    assert r["R-25"]["blocked"] and "vague" in codes(r["R-25"])
    assert "past_due" in codes(r["R-28"])
    assert "no_backup" in codes(r["R-27"])
    assert "shared" in codes(r["R-18"]) and len(r["R-18"]["owners"]) == 2 and r["R-18"]["ownership_mode"] == "any"
    assert r["R-06"]["depends_on"] == ["R-05"]
    assert r["R-12"]["depends_on"] == ["R-11"]
    assert not any(x["action"] == "error" for x in r.values())
    blocked = {k for k, v in r.items() if v["blocked"]}
    assert blocked == {"R-25"}


def test_apply_and_send_one_email_per_provider(env):
    vague_r25(env)
    bid = upload(CSV)
    res = apply(bid)
    assert len(res["created"]) == 28 and len(res["blocked"]) == 1
    owners = {"hannah", "priya", "dan", "aisha", "mei", "carlos", "tom", "leo"}
    assert len(res["drafts"]) == len(owners)
    assert send_all(bid) == len(owners)
    sent = env.sender.sent
    assert sorted(e.to[0].split("@")[0] for e in sent) == sorted(owners)
    priya = next(e for e in sent if e.to == ["priya@example.com"])
    assert "[R-18] Credit memos" in priya.text and "shared with Carlos Ruiz" in priya.text
    assert "[R-06]" in priya.text and "relates to R-05 Vendor master changes" in priya.text
    leo = next(e for e in sent if e.to == ["leo@example.com"])
    assert "R-25" not in leo.text  # vague row is held back
    assert len({e.reply_to for e in sent}) == len(owners)

    assert by_ext("R-07").aliases == ["R-08"]
    assert by_ext("R-25").state == states.WAITING_REQUESTER
    assert by_ext("R-01").state == states.WAITING_PROVIDER
    assert {f["code"] for f in by_ext("R-28").flags} >= {"past_due"}
    with session_scope() as s:
        deps = {(s.get(Request, d.request_id).external_id, s.get(Request, d.depends_on_id).external_id) for d in s.scalars(select(RequestDependency))}
    assert deps == {("R-06", "R-05"), ("R-12", "R-11")}


def test_reimport_unchanged_is_a_no_op(env):
    vague_r25(env)
    bid = upload(CSV)
    apply(bid)
    send_all(bid)
    calls_before = len(env.llm.calls)
    with session_scope() as s:
        msgs_before = s.query(OutboundMessage).count()
        states_before = {r.id: r.state for r in s.scalars(select(Request))}

    bid2 = upload(CSV)
    r = rows(bid2)
    assert {v["action"] for k, v in r.items() if k != "R-08"} == {"unchanged"}
    assert len(env.llm.calls) == calls_before  # nothing re-scoped
    res = apply(bid2)
    assert res["created"] == [] and res["updated"] == [] and res["drafts"] == []
    run_jobs()
    with session_scope() as s:
        assert s.query(OutboundMessage).count() == msgs_before
        assert {r.id: r.state for r in s.scalars(select(Request))} == states_before


def test_reimport_changes_send_one_consolidated_notice(env):
    vague_r25(env)
    bid = upload(CSV)
    apply(bid)
    send_all(bid)
    env.sender.sent.clear()

    def change(lines):
        out = []
        for ln in lines:
            if ln.startswith("R-01,"):
                ln = ln.replace("2026-10-16,Hannah", "2026-10-21,Hannah")
            elif ln.startswith("R-02,"):
                ln = ln.replace("the date of each.", "the date of each, signed by the reviewer.")
            elif ln.startswith("R-30,"):
                continue
            out.append(ln)
        return out

    bid2 = upload(edit_csv(change))
    r = rows(bid2)
    assert r["R-01"]["action"] == "changed" and [c["field"] for c in r["R-01"]["changes"]] == ["due_date"]
    assert r["R-02"]["action"] == "changed" and [c["field"] for c in r["R-02"]["changes"]] == ["instructions"]
    assert r["R-30"]["action"] == "removed"
    assert r["R-03"]["action"] == "unchanged"
    res = apply(bid2)
    assert res["change_notices"] == 2 and res["drafts"] == []
    run_jobs()
    hannah = [e for e in env.sender.sent if e.to == ["hannah@example.com"]]
    assert len(hannah) == 1, [e.subject for e in env.sender.sent]
    assert "New due date: Oct 21, 2026" in hannah[0].text and "signed by the reviewer" in hannah[0].text
    assert hannah[0].in_reply_to  # threaded under the original batch email
    assert by_ext("R-01").auto_contact_count == 1 and by_ext("R-02").auto_contact_count == 1
    assert str(by_ext("R-01").due_date) == "2026-10-21"
    with session_scope() as s:
        r02 = s.scalars(select(Request).where(Request.external_id == "R-02")).one()
        assert [v.status for v in r02.versions] == ["superseded", "confirmed"]
    r30 = by_ext("R-30")
    assert r30.state == states.WAITING_PROVIDER and "removed_from_list" in {f["code"] for f in r30.flags}

    # applying the same file again changes nothing more
    env.sender.sent.clear()
    bid3 = upload(edit_csv(change))
    assert {v["action"] for k, v in rows(bid3).items() if k not in ("R-08", "R-30")} == {"unchanged"}
    apply(bid3)
    run_jobs()
    assert env.sender.sent == []
    with session_scope() as s:
        from app.models import Comment

        r30 = s.scalars(select(Request).where(Request.external_id == "R-30")).one()
        assert s.query(Comment).filter(Comment.request_id == r30.id, Comment.body.contains("wasn't in the latest import")).count() == 1


def test_conflicting_ids_block_apply_until_excluded(env):
    def dup(lines):
        return [*lines, "R-03,Something else,A different request entirely for the same id.,2026-10-30,Hannah Brooks,hannah@example.com,leo@example.com"]

    bid = upload(edit_csv(dup))
    r = rows(bid)
    assert r["R-03"]["action"] == "error" and "conflicting_id" in codes(r["R-03"])
    try:
        apply(bid)
        raise AssertionError("apply should refuse")
    except imports.ImportError_ as e:
        assert "R-03" in str(e)
    with session_scope() as s:
        b = s.get(ImportBatch, bid)
        for row in b.rows:
            if row.external_id == "R-03":
                imports.edit_row(s, user(s), b, row, {"include": False})
    res = apply(bid)
    assert res["created"]
    with session_scope() as s:
        assert s.scalars(select(Request).where(Request.external_id == "R-03")).first() is None


def test_invalid_rows_and_bad_headers(env):
    bid = upload(b"id,name\n1,2\n")
    with session_scope() as s:
        b = s.get(ImportBatch, bid)
        assert b.status == "error" and "Missing column" in b.errors[0]
    bad = edit_csv(lambda lines: lines[:2] + ["R-99,Bad,Some instructions here please.,13/10/2026,Al,not-an-email,"])
    r = rows(upload(bad, name="other"))
    assert r["R-99"]["action"] == "error"
    msg = r["R-99"]["flags"][0]["message"]
    assert "invalid owner email" in msg and "YYYY-MM-DD" in msg


def test_review_edits_unblock_vague_row_and_survive_reimport(env):
    vague_r25(env)
    bid = upload(CSV)
    with session_scope() as s:
        b = s.get(ImportBatch, bid)
        row = next(r for r in b.rows if r.external_id == "R-25")
        imports.edit_row(s, user(s), b, row, {"items": [{"kind": "document", "description": "Q3 trial balance", "criteria": {"period": "Q3 2026", "entity": None, "format": None, "required_elements": [], "signature": None, "currency_rule": None}, "subpoints": []}]})
        r28 = next(r for r in b.rows if r.external_id == "R-28")
        imports.edit_row(s, user(s), b, r28, {"due_date": "2026-10-09"})
    r = rows(bid)
    assert not r["R-25"]["blocked"] and "past_due" not in codes(r["R-28"])
    res = apply(bid)
    assert res["blocked"] == []
    assert by_ext("R-25").state == states.READY_TO_SEND
    assert str(by_ext("R-28").due_date) == "2026-10-09"
    # the original CSV again: the requester's edit to R-28 is not reverted
    bid2 = upload(CSV)
    assert rows(bid2)["R-28"]["action"] == "unchanged"

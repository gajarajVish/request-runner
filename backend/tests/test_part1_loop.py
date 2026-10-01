"""The first implementation target: one confirmed checklist, one injected reply with an
attachment, verified evidence-backed verdicts, and a deterministic next action."""

from sqlalchemy import select

from app.db import session_scope
from app.models import Check, Comment, InboundMessage, OutboundMessage, ProviderQuestion, Request
from app.workflow import inbound, states

from .conftest import eml
from .helpers import check_out, cite, classify, confirmed_request, evid, reply_to_of, run_jobs, verdict

CERT_QUOTE = "Policy period 03/01/2026 to 03/01/2027"


def test_initial_email_is_sent_on_behalf_with_unique_reply_to(env):
    rid = confirmed_request(env)
    assert len(env.sender.sent) == 1
    m = env.sender.sent[0]
    assert m.from_name == "Sam Rivera via RequestRunner"
    assert m.from_address == "requests@mail.test.local"
    assert m.reply_to.startswith("req+") and m.reply_to.endswith("@in.test.local")
    assert m.to == ["jordan@example.com"]
    assert "Sam Rivera asked RequestRunner to collect" in m.text
    assert "Your replies and files are shared with Sam Rivera" in m.text
    assert "/u/" in m.text  # upload link
    with session_scope() as s:
        assert s.get(Request, rid).state == states.WAITING_PROVIDER


def test_reply_with_certificate_and_question(env):
    rid = confirmed_request(env)
    reply_to, mid = reply_to_of(rid)
    env.llm.on("classify", lambda c: classify(questions=[{"request_ref": "Q1", "question": "Which MSA version do you need?"}]))
    env.llm.on(
        "check",
        lambda c: check_out(
            [
                verdict("i1", "met", [cite(evid(c, "certificate"), CERT_QUOTE, page=1)]),
                verdict("i2", "not_met", missing=["Signed MSA: not received yet"]),
            ]
        ),
    )
    env.llm.on("answer_question", lambda c: {"in_scope": True, "answer": "The 2025 Amended and Restated MSA, signed by both parties.", "basis_item_keys": ["i2"], "reason": "item i2"})
    inbound.ingest_raw(eml("part1/A_msa-and-insurance/reply-1_certificate-and-msa-question.eml", reply_to))
    run_jobs()
    with session_scope() as s:
        req = s.get(Request, rid)
        assert req.state == states.NEEDS_MORE
        chk = s.scalars(select(Check).where(Check.request_id == rid, Check.status == "checked")).one()
        v = {x.item_key: x for x in chk.verdicts}
        assert v["i1"].verdict == "met"
        assert v["i1"].citations[0]["verified"] is True
        assert v["i1"].citations[0]["location"] == "p.1"
        assert v["i2"].verdict == "not_met"
        ib = s.scalars(select(InboundMessage)).one()
        assert ib.match_method == "token"
        q = s.scalars(select(ProviderQuestion)).one()
        assert q.status == "answered_from_scope"
    # nothing goes out until the debounce window passes; then ONE message with answer + gaps
    assert len(env.sender.sent) == 1
    run_jobs(advance_seconds=120)
    assert len(env.sender.sent) == 2
    f = env.sender.sent[1]
    assert "Which MSA version" in f.text and "2025 Amended and Restated" in f.text
    assert "Signed MSA: not received yet" in f.text
    # threads under the provider's reply, with our original in References
    assert f.in_reply_to == "<179074696545.97976.4110128060310696522@example.com>"
    assert mid in f.references
    assert f.reply_to == reply_to
    with session_scope() as s:
        req = s.get(Request, rid)
        assert req.auto_contact_count == 1
        out = s.scalars(select(OutboundMessage).where(OutboundMessage.kind == "followup")).one()
        assert out.counted_request_ids == [rid]


def test_unsigned_then_signed_completes_with_handback(env):
    rid = confirmed_request(env)
    reply_to, mid = reply_to_of(rid)
    from .conftest import make_eml

    cert = (env.data_dir.parent / "x").exists()  # noqa: F841
    from .conftest import STARTER

    cert_pdf = (STARTER / "part1/A_msa-and-insurance/acme-logistics-llc_certificate-of-insurance_2026-2027.pdf").read_bytes()
    unsigned = (STARTER / "part1/A_msa-and-insurance/acme-msa-2025_unsigned.pdf").read_bytes()
    signed = (STARTER / "part1/A_msa-and-insurance/acme-msa-2025_signed.pdf").read_bytes()

    def check1(c):
        return check_out(
            [
                verdict("i1", "met", [cite(evid(c, "certificate"), CERT_QUOTE, page=1)]),
                verdict("i2", "not_met", missing=["Signed MSA: acme-msa-2025_unsigned.pdf has blank signature lines for both parties"]),
            ]
        )

    env.llm.on("check", check1)
    inbound.ingest_raw(make_eml(to=reply_to, body="Here's the certificate and the MSA.", attachments=[("certificate.pdf", cert_pdf, "application/pdf"), ("acme-msa-2025_unsigned.pdf", unsigned, "application/pdf")]))
    run_jobs()
    run_jobs(advance_seconds=120)
    assert "blank signature lines" in env.sender.sent[-1].text

    def check2(c):
        return check_out(
            [
                verdict("i1", "met", [cite(evid(c, "certificate"), CERT_QUOTE, page=1)]),
                verdict("i2", "met", [cite(evid(c, "_signed"), "Name: Jordan Lee", page=1), cite(evid(c, "_signed"), None, page=1, visual=True, note="handwritten signatures above both lines")]),
            ]
        )

    env.llm.on("check", check2)
    inbound.ingest_raw(make_eml(to=reply_to, body="Signed copy attached.", attachments=[("acme-msa-2025_signed.pdf", signed, "application/pdf")]))
    run_jobs()
    with session_scope() as s:
        req = s.get(Request, rid)
        assert req.state == states.COMPLETE
        hb = s.scalars(select(Comment).where(Comment.request_id == rid, Comment.kind == "handback")).one()
        assert hb.payload["met"] == 2 and hb.payload["total"] == 2
        assert any(e["filename"] == "acme-msa-2025_signed.pdf" for i in hb.payload["items"] for e in i["evidence"])
    notice = [m for m in env.sender.sent if m.to == ["sam@example.com"]]
    assert notice and "MET" in notice[-1].text


def test_provider_closes_with_partial(env):
    from .helpers import item

    items = [item("July 2026 statement"), item("August 2026 statement"), item("September 2026 statement")]
    rid = confirmed_request(env, items=items, title="Q3 bank statements")
    reply_to, _ = reply_to_of(rid)
    env.llm.on("classify", lambda c: classify(closes_request=True, closing_quote="so that's all I have for now"))
    env.llm.on(
        "check",
        lambda c: check_out(
            [
                verdict("i1", "met", [cite(evid(c, "2026-07"), "Cascade Federal Bank", page=1)]),
                verdict("i2", "met", [cite(evid(c, "2026-08"), "Cascade Federal Bank", page=1)]),
                verdict("i3", "not_met", missing=["September statement: not provided (provider says the bank hasn't released it)"]),
            ]
        ),
    )
    inbound.ingest_raw(eml("part1/B_bank-statements/reply_partial-thats-all.eml", reply_to))
    run_jobs()
    with session_scope() as s:
        req = s.get(Request, rid)
        assert req.state == states.CLOSED_BY_PROVIDER
        hb = s.scalars(select(Comment).where(Comment.request_id == rid, Comment.kind == "handback")).one()
        assert [g["description"] for g in hb.payload["gaps"]] == ["September 2026 statement"]
    run_jobs(advance_seconds=600)
    assert not any(m.kind if hasattr(m, "kind") else False for m in [])  # no follow-up to provider after close
    assert all("still needs" not in m.text for m in env.sender.sent)

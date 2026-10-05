"""Spend limits: a daily token budget, a per-request check cap, a size cap on one check,
and a row cap on imports. Each bounds how many tokens one actor can make the app spend."""

from __future__ import annotations

import pytest
from pydantic import BaseModel
from sqlalchemy import select

from app.config import get_settings
from app.db import session_scope
from app.llm import base
from app.models import Check, EvidenceFile, Request
from app.workflow import actions, evidence, imports, states

from .conftest import STARTER, make_eml, user
from .helpers import confirmed_request, reply_to_of, run_jobs

CERT = STARTER / "part1/A_msa-and-insurance/acme-logistics-llc_certificate-of-insurance_2026-2027.pdf"


def _set(monkeypatch, **env):
    for k, v in env.items():
        monkeypatch.setenv(k, str(v))
    get_settings.cache_clear()


# --------------------------------------------------------------------------- daily budget


class _Out(BaseModel):
    x: int = 1


def test_calls_are_refused_once_the_daily_budget_is_used(env, monkeypatch):
    _set(monkeypatch, LLM_DAILY_TOKEN_BUDGET=1000)
    call = base.LLMCall(step="chat", system="", content=[], output=_Out)
    env.llm.on("chat", lambda c: _Out())
    base.record_usage("check", 600, 300)
    base.run(call, _Out)  # 900 < 1000: allowed
    base.record_usage("check", 100, 0)
    with pytest.raises(base.LLMError, match="daily LLM token budget"):
        base.run(call, _Out)
    u = base.usage_today()
    assert (u["input"], u["output"], u["calls"]) == (700, 300, 2)
    assert u["by_step"] == {"check": 1000}


def test_zero_budget_means_no_cap(env, monkeypatch):
    _set(monkeypatch, LLM_DAILY_TOKEN_BUDGET=0)
    env.llm.on("chat", lambda c: _Out())
    base.record_usage("check", 10**9, 0)
    base.run(base.LLMCall(step="chat", system="", content=[], output=_Out), _Out)


# --------------------------------------------------------------------------- checks per request


def test_checks_per_request_are_capped_per_day(env, monkeypatch):
    _set(monkeypatch, MAX_CHECKS_PER_REQUEST_PER_DAY=2)
    rid = confirmed_request(env)
    reply_to, _ = reply_to_of(rid)
    from app.workflow import inbound

    inbound.ingest_raw(make_eml(to=reply_to, body="See attached.", attachments=[("certificate.pdf", CERT.read_bytes(), "application/pdf")]))
    run_jobs()
    for _ in range(2):
        with session_scope() as s:
            actions.retry_check(s, user(s), s.get(Request, rid))
        run_jobs()

    assert sum(1 for c in env.llm.calls if c.step == "check") == 2
    with session_scope() as s:
        checks = s.scalars(select(Check).where(Check.request_id == rid).order_by(Check.id)).all()
        assert [c.status for c in checks] == ["checked", "checked", "error"]
        assert "MAX_CHECKS_PER_REQUEST_PER_DAY" in checks[-1].error
        assert s.get(Request, rid).state == states.NEEDS_MORE

    # a day later the cap has rolled off
    run_jobs(advance_seconds=86400 + 60)
    with session_scope() as s:
        actions.retry_check(s, user(s), s.get(Request, rid))
    run_jobs()
    assert sum(1 for c in env.llm.calls if c.step == "check") == 3


# --------------------------------------------------------------------------- size of one check


def _file(i: int, text: str, name: str) -> EvidenceFile:
    return EvidenceFile(
        id=i, kind="file", filename=name, detected_type="pdf", accepted=True, extraction_status="ok", source="upload",
        extraction={"segments": [{"loc": {"type": "pdf", "page": 1}, "label": "p.1", "text": text}], "images": []},
    )


def test_evidence_text_is_capped_per_check_and_the_cut_is_noted(monkeypatch):
    monkeypatch.setattr(evidence, "MAX_TEXT_PER_FILE", 100)
    monkeypatch.setattr(evidence, "MAX_TEXT_PER_CALL", 150)
    files = [_file(1, "a" * 120, "one.pdf"), _file(2, "b" * 120, "two.pdf"), _file(3, "c" * 120, "three.pdf")]
    blocks, notes = evidence.render(files, {})
    text = "\n".join(b["text"] for b in blocks if b["type"] == "text")
    assert "a" * 100 in text and "a" * 101 not in text  # per-file cap
    assert "b" * 50 in text and "b" * 51 not in text  # what's left of the per-call cap
    assert '<evidence id="E3" file="three.pdf"' in text and 'status="not_shown"' in text and "c" * 10 not in text
    assert notes == ["one.pdf: text truncated at 100 characters", "two.pdf: text truncated at 50 characters", "three.pdf: not shown (text limit for one check)"]


# --------------------------------------------------------------------------- imports


def _csv(n: int) -> bytes:
    lines = ["request_id,title,instructions,due_date,owner_email"]
    lines += [f"R-{i},Title {i},Send the thing {i},2026-10-30,p{i}@example.com" for i in range(n)]
    return "\n".join(lines).encode()


def test_import_rejects_more_rows_than_the_cap(env, monkeypatch):
    _set(monkeypatch, MAX_IMPORT_ROWS=3)
    rows, errors = imports.parse_csv(_csv(3))
    assert len(rows) == 3 and not errors
    rows, errors = imports.parse_csv(_csv(4))
    assert rows == [] and "more than 3 requests" in errors[0]

"""Upload-hub tokens, workspace isolation, the demo clock, and restart-safe jobs."""

from __future__ import annotations

from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import bootstrap, clock
from app.config import get_settings
from app.db import session_scope
from app.models import (
    ClockState,
    EvidenceAssignment,
    EvidenceFile,
    InboundMessage,
    Job,
    Provider,
    Request,
    UploadToken,
    User,
    Workspace,
)
from app.workflow import actions, hub, inbound, jobs, states

from .conftest import STARTER, make_eml, user
from .helpers import check_out, cite, confirmed_request, evid, reply_to_of, run_jobs, verdict

CERT = (STARTER / "part1/A_msa-and-insurance/acme-logistics-llc_certificate-of-insurance_2026-2027.pdf").read_bytes()


def client():
    from app.main import create_app

    return TestClient(create_app())


def jordan_token() -> str:
    with session_scope() as s:
        p = s.scalars(select(Provider).where(Provider.email == "jordan@example.com")).one()
        return hub.issue_token(s, p)


def resolves(token: str) -> bool:
    with session_scope() as s:
        return hub.resolve(s, token) is not None


# --------------------------------------------------------------------------- upload hub


def test_hub_upload_assigns_and_checks(env):
    rid = confirmed_request(env)
    tok = jordan_token()
    env.llm.on("check", lambda c: check_out([verdict("i1", "met", [cite(evid(c, "cert"), "Policy period 03/01/2026 to 03/01/2027", page=1)]), verdict("i2", "not_met")]))
    c = client()
    view = c.get(f"/api/hub/{tok}").json()
    assert [i["request_id"] for i in view["items"]] == [rid]
    assert view["items"][0]["checklist"][0]["status"] == "outstanding"
    r = c.post(f"/api/hub/{tok}/upload", files={"file": ("cert.pdf", CERT, "application/pdf")}, data={"request_id": str(rid)})
    assert r.status_code == 200 and r.json()["accepted"]
    run_jobs()
    with session_scope() as s:
        f = s.scalars(select(EvidenceFile).where(EvidenceFile.filename == "cert.pdf")).one()
        assert f.source == "upload"
        assert s.scalars(select(EvidenceAssignment).where(EvidenceAssignment.file_id == f.id)).one().request_id == rid
    view = c.get(f"/api/hub/{tok}").json()
    assert view["items"][0]["checklist"][0]["status"] == "received"
    # a disallowed type is rejected, not stored
    bad = c.post(f"/api/hub/{tok}/upload", files={"file": ("run.exe", b"MZ\x90\x00" + b"\x00" * 100, "application/octet-stream")}, data={"request_id": str(rid)})
    assert bad.status_code == 200 and bad.json()["accepted"] is False
    # an item that isn't on this page can't be targeted
    assert c.post(f"/api/hub/{tok}/answer", json={"request_id": 99999, "text": "hi"}).status_code == 400


def test_hub_token_expires_per_item_deadline(env):
    confirmed_request(env, due="2026-10-17")
    tok = jordan_token()  # issued 2026-10-01; deadline = max(issue+14d, due+7d) -> end of Oct 24
    clock.set_fixed(datetime(2026, 10, 24, 20, 0))
    assert resolves(tok)
    clock.set_fixed(datetime(2026, 10, 25, 5, 0))
    assert not resolves(tok)
    with session_scope() as s:
        row = s.scalars(select(UploadToken)).all()[-1]
        assert row.revoked_at is not None and row.revoked_reason == "no eligible items"
    assert client().get(f"/api/hub/{tok}").status_code == 404


def test_hub_token_revoked_manually_and_when_nothing_is_open(env):
    rid = confirmed_request(env)
    tok = jordan_token()
    assert resolves(tok)
    with session_scope() as s:
        p = s.scalars(select(Provider).where(Provider.email == "jordan@example.com")).one()
        assert hub.revoke_all(s, p, "requester revoked") >= 1
    assert not resolves(tok)
    assert client().get(f"/api/hub/{tok}").status_code == 404

    tok2 = jordan_token()
    assert resolves(tok2)
    with session_scope() as s:
        actions.cancel(s, user(s), s.get(Request, rid), "no longer needed")
    assert not resolves(tok2)
    assert not resolves("not-a-real-token")


# --------------------------------------------------------------------------- workspace isolation


def _other_workspace_user() -> None:
    with session_scope() as s:
        ws = Workspace(name="Other Co", timezone="America/New_York")
        s.add(ws)
        s.flush()
        s.add(User(workspace_id=ws.id, name="Eve Other", email="eve@other.example", password_hash=bootstrap.hash_password("pw")))


def _login(c, email):
    r = c.post("/api/login", json={"email": email, "password": "pw"})
    assert r.status_code == 200


def test_other_workspace_cannot_see_requests_files_or_imports(env):
    from app.workflow import imports

    rid = confirmed_request(env)
    reply_to, _ = reply_to_of(rid)
    inbound.ingest_raw(make_eml(to=reply_to, body="Attached.", attachments=[("cert.pdf", CERT, "application/pdf")]))
    run_jobs()
    with session_scope() as s:
        fid = s.scalars(select(EvidenceFile.id).where(EvidenceFile.filename == "cert.pdf")).one()
        bid = imports.start_import(s, user(s), list_name="L", filename="r.csv", data=(STARTER / "requests.csv").read_bytes()).id
    run_jobs()
    _other_workspace_user()

    owner, eve = client(), client()
    _login(owner, "sam@example.com")
    _login(eve, "eve@other.example")
    assert owner.get(f"/api/requests/{rid}").status_code == 200
    assert owner.get(f"/api/files/{fid}/download").status_code == 200
    assert owner.get(f"/api/files/{fid}/download").headers["content-disposition"].startswith("attachment")
    assert owner.get(f"/api/imports/batches/{bid}").status_code == 200

    for path in (f"/api/requests/{rid}", f"/api/files/{fid}/download", f"/api/files/{fid}", f"/api/imports/batches/{bid}"):
        assert eve.get(path).status_code == 404, path
    assert eve.post(f"/api/requests/{rid}/cancel", json={"reason": "x"}).status_code == 404
    assert eve.post(f"/api/imports/batches/{bid}/apply").status_code == 404
    assert eve.get("/api/requests").json() == []
    assert eve.get("/api/audit").json() == []
    assert eve.get("/api/messages").json() == []
    assert eve.get("/api/dashboard").json()["providers"] == []
    assert client().get(f"/api/requests/{rid}").status_code == 401  # signed out


def test_events_feed_is_filtered_by_workspace(env):
    """The SSE stream filters on Event.workspace_id; every event a request emits carries it."""
    from app.models import Event

    confirmed_request(env)
    with session_scope() as s:
        ws = user(s).workspace_id
        rows = s.scalars(select(Event)).all()
        assert rows and all(e.workspace_id == ws for e in rows)


# --------------------------------------------------------------------------- demo clock


def test_clock_advance_is_idempotent_per_key(env):
    clock.set_fixed(None)
    with session_scope() as s:
        before = clock.now(s)
        assert clock.advance(s, 86400, key="k1") is True
    with session_scope() as s:
        assert clock.advance(s, 86400, key="k1") is False  # a double-click or retried request
        assert s.get(ClockState, 1).offset_seconds == 86400
        assert 86000 < (clock.now(s) - before).total_seconds() < 87000
        assert clock.advance(s, 3600, key="k2") is True
        assert s.get(ClockState, 1).offset_seconds == 90000


def test_clock_and_dev_routes_disabled_in_production(env, monkeypatch):
    c = client()
    _login(c, "sam@example.com")
    assert c.post("/api/dev/clock/advance", json={"seconds": 60, "key": "a"}).status_code == 200
    monkeypatch.setenv("APP_ENV", "production")
    get_settings.cache_clear()
    clock.set_fixed(None)
    with session_scope() as s, pytest.raises(PermissionError):
        clock.advance(s, 60, key="b")
    assert c.post("/api/dev/clock/advance", json={"seconds": 60, "key": "c"}).status_code == 404
    assert c.get("/api/dev/users").status_code == 404
    with session_scope() as s:
        # production time ignores the stored offset
        assert abs((clock.now(s) - clock.real_utcnow()).total_seconds()) < 5


# --------------------------------------------------------------------------- restart safety


def test_job_left_running_by_a_crash_is_recovered_and_idempotent(env):
    rid = confirmed_request(env)
    reply_to, _ = reply_to_of(rid)
    iid, _ = inbound.ingest_raw(make_eml(to=reply_to, body="Attached.", attachments=[("cert.pdf", CERT, "application/pdf")]))
    with session_scope() as s:
        job = s.scalars(select(Job).where(Job.kind == "process_inbound")).one()
        job.status = "running"  # the worker died mid-job
    assert jobs.run_until_idle() == 0  # a running job is not picked up again on its own
    jobs.recover_interrupted()
    run_jobs()
    with session_scope() as s:
        assert s.get(InboundMessage, iid).status == "processed"
        n_files = s.query(EvidenceFile).count()
        n_assign = s.query(EvidenceAssignment).count()
    inbound.process(iid)  # the same work again (e.g. the job ran but its finish wasn't recorded)
    run_jobs()
    with session_scope() as s:
        assert s.query(EvidenceFile).count() == n_files
        assert s.query(EvidenceAssignment).count() == n_assign
        assert s.get(Request, rid).state in states.OPEN_WITH_PROVIDER


def test_scheduled_follow_up_survives_a_restart(env):
    rid = confirmed_request(env)
    reply_to, _ = reply_to_of(rid)
    inbound.ingest_raw(make_eml(to=reply_to, body="Partial."))
    run_jobs()
    with session_scope() as s:
        pending = s.scalars(select(Job).where(Job.kind == "provider_cycle", Job.status == "pending")).all()
        assert pending  # persisted, not in memory
    # "restart": a fresh engine over the same database
    from app import db

    db.init_engine()
    jobs.recover_interrupted()
    run_jobs(advance_seconds=120)
    assert any(m.to == ["jordan@example.com"] and "still needs" in m.text for m in env.sender.sent)


def test_production_refuses_unsafe_settings(env, monkeypatch):
    from app.config import Settings, production_problems

    bad = Settings(app_env="production", email_provider="postmark", llm_provider="anthropic", app_base_url="http://x")
    problems = " ".join(production_problems(bad))
    for needle in ("SESSION_SECRET", "APP_BASE_URL", "EMAIL_INBOUND_BASIC_AUTH", "POSTMARK_SERVER_TOKEN", "ANTHROPIC_API_KEY"):
        assert needle in problems
    good = Settings(
        app_env="production",
        session_secret="x" * 40,
        app_base_url="https://rr.example.com",
        email_provider="postmark",
        email_inbound_basic_auth="hook:secret",
        postmark_server_token="t",
        llm_provider="anthropic",
        anthropic_api_key="k",
    )
    assert production_problems(good) == []


def test_production_does_not_seed_demo_accounts(env, monkeypatch):
    from app import bootstrap
    from app.config import get_settings
    from app.db import session_scope
    from app.models import User

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("SEED_USERS", raising=False)
    get_settings.cache_clear()
    with session_scope() as s:
        before = s.query(User).count()
    bootstrap.seed()
    with session_scope() as s:
        assert s.query(User).count() == before
        assert s.query(User).filter(User.email == "sam@example.com").first().password_hash  # test fixture user, untouched

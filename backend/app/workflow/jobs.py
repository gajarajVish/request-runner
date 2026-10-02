"""Durable job queue + in-process worker.

Jobs live in the database, so they survive restarts. Enqueueing is idempotent by `key`.
Handlers must be idempotent: a job interrupted mid-run is retried after restart.
"""

from __future__ import annotations

import logging
import threading
import time
import traceback
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import clock
from ..config import get_settings
from ..db import session_scope
from ..models import Job

log = logging.getLogger(__name__)

Handler = Callable[[dict[str, Any]], None]
HANDLERS: dict[str, Handler] = {}
MAX_ATTEMPTS = 4


def handler(kind: str) -> Callable[[Handler], Handler]:
    def deco(fn: Handler) -> Handler:
        HANDLERS[kind] = fn
        return fn

    return deco


def enqueue(
    session: Session,
    kind: str,
    key: str,
    payload: dict[str, Any] | None = None,
    run_at: datetime | None = None,
    *,
    coalesce: bool = False,
) -> Job:
    """Create a job unless one with this key exists.

    coalesce=True: if a *pending* job with this key exists, push its run_at to the new time
    (debounce). Finished jobs get their key suffixed, so a coalescing key can be reused.
    """
    run_at = run_at or clock.now(session)
    existing = session.scalars(select(Job).where(Job.key == key)).first()
    if existing is not None:
        if coalesce and existing.status == "pending" and run_at > existing.run_at:
            existing.run_at = run_at
            existing.payload = payload or existing.payload
        return existing
    job = Job(key=key, kind=kind, payload=payload or {}, run_at=run_at, status="pending", created_at=clock.now(session))
    try:
        with session.begin_nested():
            session.add(job)
    except IntegrityError:
        return session.scalars(select(Job).where(Job.key == key)).one()
    return job


def _claim_due(limit: int = 20) -> list[tuple[int, str, dict, str]]:
    with session_scope() as s:
        now = clock.now(s)
        rows = s.scalars(
            select(Job).where(Job.status == "pending", Job.run_at <= now).order_by(Job.run_at, Job.id).limit(limit)
        ).all()
        claimed = []
        for j in rows:
            res = s.execute(update(Job).where(Job.id == j.id, Job.status == "pending").values(status="running", attempts=Job.attempts + 1))
            if res.rowcount == 1:
                claimed.append((j.id, j.kind, dict(j.payload), j.key))
        return claimed


def _finish(job_id: int, key: str, error: str | None) -> None:
    with session_scope() as s:
        job = s.get(Job, job_id)
        if job is None:
            return
        now = clock.now(s)
        if error is None:
            job.status = "done"
            job.finished_at = now
            job.key = f"{key}#done{job_id}"
        elif job.attempts < MAX_ATTEMPTS:
            job.status = "pending"
            job.last_error = error
            job.run_at = now + timedelta(seconds=10 * 2**job.attempts)
        else:
            job.status = "failed"
            job.last_error = error
            job.finished_at = now
            job.key = f"{key}#failed{job_id}"


def run_due(limit: int = 20) -> int:
    """Run all jobs due now. Returns how many ran."""
    ran = 0
    for job_id, kind, payload, key in _claim_due(limit):
        fn = HANDLERS.get(kind)
        err = None
        try:
            if fn is None:
                raise RuntimeError(f"no handler for job kind {kind}")
            fn(payload)
        except Exception:  # noqa: BLE001 - recorded on the job
            err = traceback.format_exc(limit=8)
            log.exception("job %s (%s) failed", job_id, kind)
        _finish(job_id, key, err)
        ran += 1
    return ran


def run_until_idle(max_rounds: int = 200) -> int:
    total = 0
    for _ in range(max_rounds):
        n = run_due()
        total += n
        if n == 0:
            break
    return total


def recover_interrupted() -> None:
    """On startup: jobs left 'running' by a crash go back to pending (handlers are idempotent)."""
    with session_scope() as s:
        s.execute(update(Job).where(Job.status == "running").values(status="pending"))


class Worker(threading.Thread):
    def __init__(self) -> None:
        super().__init__(daemon=True, name="rr-worker")
        self._stop = threading.Event()
        self._last_sweep = 0.0
        self._last_gmail = 0.0

    def stop(self) -> None:
        self._stop.set()

    def _poll_gmail(self) -> None:
        s = get_settings()
        if s.email_provider != "gmail" or time.monotonic() - self._last_gmail < s.gmail_poll_seconds:
            return
        self._last_gmail = time.monotonic()
        from ..email import gmail

        try:
            n = gmail.poll_once()
            if n:
                log.info("gmail: queued %d new repl%s", n, "y" if n == 1 else "ies")
        except Exception:  # noqa: BLE001
            log.exception("gmail poll failed")

    def run(self) -> None:
        from .followups import enqueue_sweep

        recover_interrupted()
        poll = get_settings().worker_poll_seconds
        while not self._stop.is_set():
            try:
                if time.monotonic() - self._last_sweep > 30:
                    with session_scope() as s:
                        enqueue_sweep(s)
                    self._last_sweep = time.monotonic()
                self._poll_gmail()
                if run_due() == 0:
                    self._stop.wait(poll)
            except Exception:  # noqa: BLE001
                log.exception("worker loop error")
                self._stop.wait(poll * 5)

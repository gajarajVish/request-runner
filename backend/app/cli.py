"""Command line: `uv run rr <command>`.

  rr migrate                     apply database migrations
  rr seed                        create the workspace and requester accounts
  rr inject-eml FILE [--request ID | --to ADDR] [--from ADDR] [--no-thread] [--new-id] [--process]
                                 feed a raw .eml through the real inbound pipeline
  rr run-jobs                    run due jobs once (when the server's worker isn't running)
  rr advance-clock --days N      move the demo clock forward (development only)
  rr sweep                       queue a reminder/overdue/escalation sweep
"""

from __future__ import annotations

import argparse
import re
import sys
import uuid
from email.utils import make_msgid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session


def retarget(s: Session, raw: bytes, req, *, thread: bool = True, new_id: bool = False, from_addr: str | None = None, to: str | None = None) -> bytes:
    """Point a starter .eml at a request: set To to its reply address, thread it under our last email."""
    from .models import ConversationRequest, Conversation, OutboundMessage
    from .workflow.outbox import reply_address

    reply = to
    last_mid = None
    if req is not None:
        conv_id = s.scalars(select(ConversationRequest.conversation_id).where(ConversationRequest.request_id == req.id).order_by(ConversationRequest.id.desc())).first()
        if conv_id is None:
            raise SystemExit(f"request {req.id} has no email conversation yet (send it first)")
        conv = s.get(Conversation, conv_id)
        reply = reply or reply_address(conv.reply_token)
        last = s.scalars(select(OutboundMessage).where(OutboundMessage.conversation_id == conv.id, OutboundMessage.status == "sent").order_by(OutboundMessage.id.desc())).first()
        last_mid = last.message_id if last else None
    head, sep, body = raw.replace(b"\r\n", b"\n").partition(b"\n\n")
    lines = head.split(b"\n")

    def set_header(name: str, value: str) -> None:
        nonlocal lines
        pat = re.compile(rb"^" + name.encode() + rb":", re.I)
        out, skip = [], False
        for ln in lines:
            if pat.match(ln):
                skip = True
                continue
            if skip and ln[:1] in (b" ", b"\t"):
                continue
            skip = False
            out.append(ln)
        out.append(f"{name}: {value}".encode())
        lines = out

    if reply:
        set_header("To", reply)
    if thread and last_mid:
        set_header("In-Reply-To", last_mid)
        set_header("References", last_mid)
    if new_id:
        set_header("Message-ID", make_msgid(domain="inject.local"))
    if from_addr:
        set_header("From", from_addr)
    return b"\n".join(lines) + sep + body


def main(argv: list[str] | None = None) -> None:
    from . import bootstrap
    from .db import session_scope
    from .workflow import jobs, registry  # noqa: F401

    p = argparse.ArgumentParser(prog="rr")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("migrate")
    sub.add_parser("seed")
    sub.add_parser("run-jobs")
    sub.add_parser("sweep")
    adv = sub.add_parser("advance-clock")
    adv.add_argument("--days", type=float, default=0)
    adv.add_argument("--hours", type=float, default=0)
    inj = sub.add_parser("inject-eml")
    inj.add_argument("file", type=Path)
    inj.add_argument("--request", type=int)
    inj.add_argument("--to")
    inj.add_argument("--from", dest="from_addr")
    inj.add_argument("--no-thread", action="store_true")
    inj.add_argument("--new-id", action="store_true", help="give the message a fresh Message-ID (re-injecting the same file)")
    inj.add_argument("--process", action="store_true", help="also run jobs now (when no server worker is running)")
    a = p.parse_args(argv)

    bootstrap.ensure_dirs()
    if a.cmd == "migrate":
        bootstrap.migrate()
        print("migrated")
    elif a.cmd == "seed":
        bootstrap.migrate()
        bootstrap.seed()
        print("seeded")
    elif a.cmd == "run-jobs":
        print(f"ran {jobs.run_until_idle()} job(s)")
    elif a.cmd == "sweep":
        from .workflow.followups import enqueue_sweep

        with session_scope() as s:
            enqueue_sweep(s)
        print("sweep queued")
    elif a.cmd == "advance-clock":
        from . import clock

        secs = int(a.days * 86400 + a.hours * 3600)
        with session_scope() as s:
            clock.advance(s, secs, key=f"cli:{uuid.uuid4()}")
            print("now", clock.now(s).isoformat())
    elif a.cmd == "inject-eml":
        from .models import Request
        from .workflow import inbound

        raw = a.file.read_bytes()
        with session_scope() as s:
            req = s.get(Request, a.request) if a.request else None
            if a.request and req is None:
                sys.exit(f"no request {a.request}")
            raw = retarget(s, raw, req, thread=not a.no_thread, new_id=a.new_id, from_addr=a.from_addr, to=a.to)
        iid, created = inbound.ingest_raw(raw, source="inject")
        print(f"inbound {iid} {'queued' if created else 'was a duplicate (already received) - use --new-id to inject again'}")
        if a.process:
            print(f"ran {jobs.run_until_idle()} job(s)")


if __name__ == "__main__":
    main()

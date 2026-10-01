from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import select

from app import bootstrap, clock, db, storage
from app.config import get_settings
from app.email.adapters import MemorySender, set_sender
from app.llm.base import set_llm
from app.llm.fake import FakeLLM
from app.models import User
from app.workflow import registry  # noqa: F401  (registers job handlers)

STARTER = Path(__file__).resolve().parents[2] / "data" / "starter"
T0 = datetime(2026, 10, 1, 14, 0)  # 10am New York


@dataclass
class Env:
    llm: FakeLLM
    sender: MemorySender
    data_dir: Path


@pytest.fixture
def env(tmp_path, monkeypatch) -> Env:
    for k, v in {
        "DATA_DIR": str(tmp_path),
        "DATABASE_URL": "",
        "APP_ENV": "development",
        "LLM_PROVIDER": "fake",
        "EMAIL_PROVIDER": "file",
        "EMAIL_INBOUND_DOMAIN": "in.test.local",
        "EMAIL_FROM_ADDRESS": "requests@mail.test.local",
        "FOLLOWUP_DEBOUNCE_SECONDS": "60",
        "CHECK_DEBOUNCE_SECONDS": "0",
        "PROVIDER_MIN_GAP_SECONDS": "0",
        "APP_BASE_URL": "http://app.test",
        "SEED_USERS": "",
    }.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()
    db.init_engine()
    storage.set_store(None)
    bootstrap.create_all()
    bootstrap.seed([("Sam Rivera", "sam@example.com", "pw"), ("Alex Chen", "alex@example.com", "pw")])
    fake = FakeLLM()
    set_llm(fake)
    sender = MemorySender()
    set_sender(sender)
    clock.set_fixed(T0)
    yield Env(fake, sender, tmp_path)
    clock.set_fixed(None)
    set_llm(None)
    set_sender(None)
    get_settings.cache_clear()


def user(s, email="sam@example.com") -> User:
    return s.scalars(select(User).where(User.email == email)).one()


def eml(path: str, to: str, *, in_reply_to: str | None = None, from_addr: str | None = None, message_id: str | None = None) -> bytes:
    """Load a starter .eml and point it at a request (the packet leaves To/In-Reply-To blank)."""
    raw = (STARTER / path).read_bytes()
    raw = raw.replace(b"req+REPLACE@in.yourapp.com", to.encode())
    head, sep, body = raw.partition(b"\n\n")
    if in_reply_to:
        head += f"\nIn-Reply-To: {in_reply_to}\nReferences: {in_reply_to}".encode()
    if from_addr:
        head = re.sub(rb"^From: .*$", f"From: {from_addr}".encode(), head, flags=re.M)
    if message_id:
        head = re.sub(rb"^Message-ID: .*$", f"Message-ID: {message_id}".encode(), head, flags=re.M)
    return head + sep + body


def make_eml(*, to: str, frm: str = "Jordan Lee <jordan@example.com>", subject: str = "Re: request", body: str = "", attachments: list[tuple[str, bytes, str]] = (), headers: dict | None = None, message_id: str | None = None) -> bytes:
    from email.message import EmailMessage
    from email.utils import make_msgid

    m = EmailMessage()
    m["From"] = frm
    m["To"] = to
    m["Subject"] = subject
    m["Message-ID"] = message_id or make_msgid(domain="example.com")
    for k, v in (headers or {}).items():
        m[k] = v
    m.set_content(body)
    for name, data, ctype in attachments:
        maintype, subtype = ctype.split("/")
        m.add_attachment(data, maintype=maintype, subtype=subtype, filename=name)
    return m.as_bytes()

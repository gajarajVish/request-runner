"""Gmail as the mail provider: plus-addressed replies, read-only inbox polling, SMTP sending."""

from __future__ import annotations

from email import message_from_bytes

from sqlalchemy import select

from app.config import Settings, get_settings
from app.db import session_scope
from app.email import gmail
from app.email.adapters import OutgoingEmail
from app.models import InboundMessage

from .conftest import make_eml
from .helpers import confirmed_request, reply_to_of, run_jobs


def use_gmail(monkeypatch):
    monkeypatch.setenv("EMAIL_PROVIDER", "gmail")
    monkeypatch.setenv("GMAIL_ADDRESS", "Me@Gmail.com")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "abcd efgh ijkl mnop")
    get_settings.cache_clear()


def test_gmail_settings_derive_sending_and_reply_addresses():
    s = Settings(email_provider="gmail", gmail_address="Me@Gmail.com", gmail_app_password="x")
    assert s.email_from_address == "me@gmail.com"
    assert s.email_inbound_domain == "gmail.com" and s.email_inbound_prefix == "me+req"


class FakeIMAP:
    """Just enough IMAP for poll_once: one INBOX, UID SEARCH and BODY.PEEK fetches."""

    def __init__(self, messages: dict[int, bytes], validity: str = "42"):
        self.messages = messages
        self.untagged_responses = {"UIDVALIDITY": [validity.encode()]}
        self.readonly = None
        self.fetched_full: list[int] = []

    def select(self, box, readonly=False):
        self.readonly = readonly
        return "OK", [str(len(self.messages)).encode()]

    def uid(self, cmd, *args):
        if cmd == "SEARCH":
            crit = args[-1]
            uids = sorted(self.messages)
            if crit.startswith("UID "):
                lo = int(crit.split()[1].split(":")[0])
                uids = [u for u in uids if u >= lo] or uids[-1:]  # like IMAP, "N:*" returns the newest when nothing is newer
            return "OK", [" ".join(map(str, uids)).encode()]
        uid, what = int(args[0]), args[1]
        raw = self.messages[uid]
        if "HEADER.FIELDS" in what:
            head = raw.split(b"\n\n", 1)[0]
            keep = b"\n".join(line for line in head.split(b"\n") if line.split(b":")[0].lower() in (b"to", b"cc", b"delivered-to"))
            return "OK", [(b"hdr", keep + b"\n\n"), b")"]
        self.fetched_full.append(uid)
        return "OK", [(b"full", raw), b")"]


def test_poller_ingests_only_replies_to_the_app_and_remembers_where_it_stopped(env, monkeypatch):
    use_gmail(monkeypatch)
    rid = confirmed_request(env)
    reply_to, last_mid = reply_to_of(rid)
    assert reply_to.startswith("me+req+") and reply_to.endswith("@gmail.com")

    personal = make_eml(to="me@gmail.com", body="Dinner on Friday?")
    reply = make_eml(to=reply_to, body="Certificate attached.", headers={"In-Reply-To": last_mid})
    imap = FakeIMAP({5: personal, 7: reply})
    assert gmail.poll_once(imap) == 1
    assert imap.readonly is True and imap.fetched_full == [7]  # the personal mail is never downloaded
    run_jobs()
    with session_scope() as s:
        rows = s.scalars(select(InboundMessage)).all()
        assert len(rows) == 1 and rows[0].conversation_id is not None

    # the next poll starts after the last seen message
    assert gmail.poll_once(imap) == 0
    imap.messages[9] = make_eml(to=f"Jordan <{reply_to}>", body="And the MSA.")
    assert gmail.poll_once(imap) == 1 and imap.fetched_full == [7, 9]


def test_gmail_sender_sends_from_the_account_with_the_reply_address(monkeypatch):
    sent = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            sent["host"] = host

        def starttls(self):
            pass

        def login(self, user, password):
            sent["login"] = (user, password)

        def send_message(self, msg):
            sent["msg"] = msg
            return {}

        def quit(self):
            pass

    monkeypatch.setattr(gmail.smtplib, "SMTP", FakeSMTP)
    out = gmail.GmailSender("me@gmail.com", "abcd efgh ijkl mnop").send(
        OutgoingEmail(
            from_name="Sam Rivera via RequestRunner", from_address="ignored@example.com", to=["jordan@example.com"], cc=[],
            reply_to="me+req+tok123@gmail.com", subject="Documents", text="Hi", message_id="<m1@x>", in_reply_to=None, references=None, idempotency_key="k",
        )
    )
    assert out.outcome == "sent"
    assert sent["login"] == ("me@gmail.com", "abcdefghijklmnop")
    msg = message_from_bytes(sent["msg"].as_bytes())
    assert "me@gmail.com" in msg["From"] and "Sam Rivera via RequestRunner" in msg["From"]
    assert msg["Reply-To"] == "me+req+tok123@gmail.com"

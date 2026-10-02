"""Gmail as the mail provider: send over SMTP, read replies over IMAP.

Replies go to <you>+req+<token>@gmail.com. Gmail delivers those to the account's inbox, and
`poll_once` picks out only messages sent to such an address and feeds them through the same
pipeline as a webhook. The inbox is opened read-only: nothing is marked read, moved or deleted.
Needs an app password (2-step verification on, then Google Account -> Security -> App passwords).
"""

from __future__ import annotations

import imaplib
import json
import logging
import re
import smtplib
import socket
from datetime import timedelta
from email import message_from_bytes
from email.utils import getaddresses

from ..config import get_settings
from .adapters import OutgoingEmail, SendResult
from .mime import build_mime

log = logging.getLogger(__name__)

SMTP_HOST, SMTP_PORT = "smtp.gmail.com", 587
IMAP_HOST = "imap.gmail.com"
FIRST_POLL_DAYS = 7  # on the first poll, look this far back
BATCH = 200


class GmailSender:
    name = "gmail"

    def __init__(self, address: str, app_password: str):
        self.address = address
        self.password = app_password.replace(" ", "")  # Google shows it in groups of four

    def send(self, email: OutgoingEmail) -> SendResult:
        msg = build_mime(
            from_name=email.from_name,
            from_address=self.address,
            to=email.to,
            cc=email.cc,
            reply_to=email.reply_to,
            subject=email.subject,
            text=email.text,
            message_id=email.message_id,
            in_reply_to=email.in_reply_to,
            references=email.references,
        )
        try:
            smtp = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30)
            smtp.starttls()
            smtp.login(self.address, self.password)
        except smtplib.SMTPAuthenticationError as e:
            return SendResult("failed", error=f"Gmail rejected the login ({e.smtp_code}). Check GMAIL_ADDRESS and the app password.")
        except (OSError, smtplib.SMTPException) as e:
            return SendResult("retry", error=f"connect: {e}")  # nothing was handed over yet
        try:
            refused = smtp.send_message(msg)
        except smtplib.SMTPRecipientsRefused as e:
            return SendResult("failed", error=f"recipients refused: {e.recipients}")
        except (smtplib.SMTPSenderRefused, smtplib.SMTPDataError) as e:
            code = getattr(e, "smtp_code", 0)
            return SendResult("retry" if 400 <= code < 500 else "failed", error=f"{type(e).__name__} {code}: {e}")
        except (OSError, smtplib.SMTPException) as e:
            return SendResult("uncertain", error=f"{type(e).__name__}: {e}")  # may have been accepted
        finally:
            try:
                smtp.quit()
            except Exception:  # noqa: BLE001
                pass
        if refused:
            return SendResult("failed", error=f"recipients refused: {refused}")
        return SendResult("sent", provider_message_id=email.message_id)


# --------------------------------------------------------------------------- inbound


def _state_path():
    return get_settings().data_dir / "gmail-state.json"


def _load_state() -> dict:
    try:
        return json.loads(_state_path().read_text())
    except (OSError, ValueError):
        return {}


def _save_state(state: dict) -> None:
    _state_path().write_text(json.dumps(state))


def is_reply_address(addr: str) -> bool:
    s = get_settings()
    return bool(re.match(rf"^{re.escape(s.email_inbound_prefix)}\+[A-Za-z0-9_-]+@{re.escape(s.email_inbound_domain)}$", addr.strip(), re.I))


def _addressed_to_app(header_block: bytes) -> bool:
    msg = message_from_bytes(header_block)
    fields = [*msg.get_all("To", []), *msg.get_all("Cc", []), *msg.get_all("Delivered-To", [])]
    return any(is_reply_address(a) for _, a in getaddresses(fields))


def connect_imap(address: str, password: str) -> imaplib.IMAP4:
    imap = imaplib.IMAP4_SSL(IMAP_HOST, timeout=30)
    imap.login(address, password.replace(" ", ""))
    return imap


def poll_once(imap: imaplib.IMAP4 | None = None) -> int:
    """Ingest new replies addressed to the app. Returns how many new messages were queued."""
    from ..workflow import inbound

    s = get_settings()
    own = imap is None
    if own:
        imap = connect_imap(s.gmail_address, s.gmail_app_password)
    try:
        typ, data = imap.select("INBOX", readonly=True)
        if typ != "OK":
            raise RuntimeError(f"cannot open INBOX: {data}")
        validity = (imap.untagged_responses.get("UIDVALIDITY") or [b"0"])[0].decode()
        state = _load_state()
        if state.get("uidvalidity") == validity and state.get("last_uid"):
            typ, data = imap.uid("SEARCH", None, f"UID {int(state['last_uid']) + 1}:*")
        else:
            from .. import clock

            since = (clock.real_utcnow() - timedelta(days=FIRST_POLL_DAYS)).strftime("%d-%b-%Y")
            typ, data = imap.uid("SEARCH", None, f"SINCE {since}")
        uids = sorted(int(u) for u in (data[0] or b"").split())
        last = int(state.get("last_uid") or 0) if state.get("uidvalidity") == validity else 0
        uids = [u for u in uids if u > last][:BATCH]  # "N:*" also returns the newest message when there's nothing newer
        queued = 0
        for uid in uids:
            typ, hdr = imap.uid("FETCH", str(uid), "(BODY.PEEK[HEADER.FIELDS (TO CC DELIVERED-TO)])")
            block = next((part[1] for part in hdr if isinstance(part, tuple)), b"")
            if typ == "OK" and _addressed_to_app(block):
                typ, full = imap.uid("FETCH", str(uid), "(BODY.PEEK[])")
                raw = next((part[1] for part in full if isinstance(part, tuple)), None)
                if typ == "OK" and raw:
                    _, created = inbound.ingest_raw(raw, source="gmail")
                    queued += int(created)
            last = uid
        _save_state({"uidvalidity": validity, "last_uid": last})
        return queued
    finally:
        if own:
            try:
                imap.logout()
            except Exception:  # noqa: BLE001
                pass


def check_connection() -> list[str]:
    """Log in to SMTP and IMAP without sending anything. Returns problems (empty = fine)."""
    s = get_settings()
    problems = []
    if not (s.gmail_address and s.gmail_app_password):
        return ["Set GMAIL_ADDRESS and GMAIL_APP_PASSWORD in .env"]
    try:
        smtp = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20)
        smtp.starttls()
        smtp.login(s.gmail_address, s.gmail_app_password.replace(" ", ""))
        smtp.quit()
    except (smtplib.SMTPAuthenticationError, smtplib.SMTPServerDisconnected):
        # Gmail often just hangs up on a bad password instead of answering 535
        problems.append("Sending: Gmail rejected the login. Use an app password, not your normal password.")
    except (OSError, socket.timeout, smtplib.SMTPException) as e:
        problems.append(f"Sending: could not reach Gmail ({e})")
    try:
        imap = connect_imap(s.gmail_address, s.gmail_app_password)
        imap.logout()
    except imaplib.IMAP4.error:
        problems.append("Reading replies: Gmail rejected the login. Check the app password.")
    except (OSError, socket.timeout) as e:
        problems.append(f"Reading replies: could not reach Gmail ({e})")
    return problems

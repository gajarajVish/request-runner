"""Outbound email adapters. Provider specifics stay here.

`send` returns a SendResult. Outcomes:
- sent: the provider accepted the message.
- retry: definitely not accepted (connection refused, 429, 5xx before acceptance); safe to retry.
- failed: rejected permanently (bad address, 4xx validation).
- uncertain: the request may have reached the provider (timeout after sending). We never blindly
  resend these; the requester sees them and can resend manually.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import httpx

from ..config import get_settings
from .mime import build_mime


@dataclass
class OutgoingEmail:
    from_name: str
    from_address: str
    to: list[str]
    cc: list[str]
    reply_to: str | None
    subject: str
    text: str
    message_id: str
    in_reply_to: str | None
    references: str | None
    idempotency_key: str


@dataclass
class SendResult:
    outcome: str  # sent | retry | failed | uncertain
    provider_message_id: str | None = None
    error: str | None = None


class EmailSender(Protocol):
    name: str

    def send(self, email: OutgoingEmail) -> SendResult: ...


class FileSender:
    """Development sender: writes each message as an .eml under var/sent-mail."""

    name = "file"

    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)

    def send(self, email: OutgoingEmail) -> SendResult:
        msg = build_mime(
            from_name=email.from_name,
            from_address=email.from_address,
            to=email.to,
            cc=email.cc,
            reply_to=email.reply_to,
            subject=email.subject,
            text=email.text,
            message_id=email.message_id,
            in_reply_to=email.in_reply_to,
            references=email.references,
        )
        safe = email.idempotency_key.replace("/", "_").replace(":", "_")
        (self.root / f"{safe}.eml").write_bytes(msg.as_bytes())
        return SendResult("sent", provider_message_id=email.message_id)


class MemorySender:
    """Test sender. Can be scripted to return particular outcomes."""

    name = "memory"

    def __init__(self):
        self.sent: list[OutgoingEmail] = []
        self.script: list[SendResult] = []

    def send(self, email: OutgoingEmail) -> SendResult:
        result = self.script.pop(0) if self.script else SendResult("sent", provider_message_id=email.message_id)
        if result.outcome == "sent":
            self.sent.append(email)
        return result


def _classify_http(exc: Exception | None, resp: httpx.Response | None) -> SendResult | None:
    if exc is not None:
        if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout)):
            return SendResult("retry", error=f"connect: {exc}")
        return SendResult("uncertain", error=f"{type(exc).__name__}: {exc}")
    assert resp is not None
    if resp.status_code == 429 or resp.status_code >= 500:
        return SendResult("retry", error=f"HTTP {resp.status_code}: {resp.text[:300]}")
    if resp.status_code >= 400:
        return SendResult("failed", error=f"HTTP {resp.status_code}: {resp.text[:300]}")
    return None


class PostmarkSender:
    name = "postmark"

    def __init__(self, token: str, stream: str):
        self.token = token
        self.stream = stream

    def send(self, email: OutgoingEmail) -> SendResult:
        headers = [{"Name": "Message-ID", "Value": email.message_id}]
        if email.in_reply_to:
            headers.append({"Name": "In-Reply-To", "Value": email.in_reply_to})
        if email.references:
            headers.append({"Name": "References", "Value": email.references})
        body = {
            "From": f'"{email.from_name}" <{email.from_address}>',
            "To": ", ".join(email.to),
            "Cc": ", ".join(email.cc) or None,
            "ReplyTo": email.reply_to,
            "Subject": email.subject,
            "TextBody": email.text,
            "Headers": headers,
            "MessageStream": self.stream,
            "Metadata": {"idempotency_key": email.idempotency_key[:80]},
        }
        resp = exc = None
        try:
            resp = httpx.post(
                "https://api.postmarkapp.com/email",
                json={k: v for k, v in body.items() if v is not None},
                headers={"X-Postmark-Server-Token": self.token, "Accept": "application/json"},
                timeout=30,
            )
        except httpx.HTTPError as e:
            exc = e
        bad = _classify_http(exc, resp)
        if bad:
            return bad
        assert resp is not None
        data = resp.json()
        if data.get("ErrorCode", 0) != 0:
            return SendResult("failed", error=f"Postmark {data.get('ErrorCode')}: {data.get('Message')}")
        return SendResult("sent", provider_message_id=data.get("MessageID"))


class SendGridSender:
    name = "sendgrid"

    def __init__(self, api_key: str):
        self.api_key = api_key

    def send(self, email: OutgoingEmail) -> SendResult:
        personalization: dict = {"to": [{"email": a} for a in email.to]}
        if email.cc:
            personalization["cc"] = [{"email": a} for a in email.cc]
        hdrs = {"Message-ID": email.message_id}
        if email.in_reply_to:
            hdrs["In-Reply-To"] = email.in_reply_to
        if email.references:
            hdrs["References"] = email.references
        body = {
            "personalizations": [personalization],
            "from": {"email": email.from_address, "name": email.from_name},
            "subject": email.subject,
            "content": [{"type": "text/plain", "value": email.text}],
            "headers": hdrs,
        }
        if email.reply_to:
            body["reply_to"] = {"email": email.reply_to}
        resp = exc = None
        try:
            resp = httpx.post(
                "https://api.sendgrid.com/v3/mail/send",
                json=body,
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=30,
            )
        except httpx.HTTPError as e:
            exc = e
        bad = _classify_http(exc, resp)
        if bad:
            return bad
        assert resp is not None
        return SendResult("sent", provider_message_id=resp.headers.get("X-Message-Id"))


_sender: EmailSender | None = None


def get_sender() -> EmailSender:
    global _sender
    if _sender is None:
        s = get_settings()
        if s.email_provider == "postmark":
            _sender = PostmarkSender(s.postmark_server_token, s.postmark_message_stream)
        elif s.email_provider == "sendgrid":
            _sender = SendGridSender(s.sendgrid_api_key)
        elif s.email_provider == "gmail":
            from .gmail import GmailSender

            _sender = GmailSender(s.gmail_address, s.gmail_app_password)
        else:
            _sender = FileSender(s.outbox_dir)
    return _sender


def set_sender(sender: EmailSender | None) -> None:
    global _sender
    _sender = sender

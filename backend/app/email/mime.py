"""Parse inbound mail into a provider-neutral `InboundEmail`, and build outbound MIME."""

from __future__ import annotations

import base64
import html
import re
from dataclasses import dataclass, field
from email import policy
from email.message import EmailMessage, Message
from email.parser import BytesParser
from email.utils import format_datetime, getaddresses, parseaddr
from datetime import UTC, datetime


@dataclass
class Attachment:
    filename: str
    content_type: str
    data: bytes


@dataclass
class InboundEmail:
    from_address: str
    from_name: str
    to: list[str]
    cc: list[str]
    subject: str
    message_id: str | None
    in_reply_to: str | None
    references: str | None
    text: str
    headers: dict[str, str]  # lower-cased names, first value
    attachments: list[Attachment] = field(default_factory=list)
    extra_recipients: list[str] = field(default_factory=list)  # Delivered-To, X-Original-To, envelope
    mailbox_hash: str | None = None  # provider-parsed plus-address part (Postmark)

    @property
    def all_recipients(self) -> list[str]:
        return [*self.to, *self.cc, *self.extra_recipients]


_TAG_RE = re.compile(r"<[^>]+>")


def html_to_text(s: str) -> str:
    s = re.sub(r"(?is)<(script|style).*?</\1>", "", s)
    s = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</li>", "\n", s)
    return html.unescape(_TAG_RE.sub("", s))


def _addresses(msg: Message, name: str) -> list[str]:
    vals = msg.get_all(name, [])
    # keep case: the local part carries the case-sensitive reply token
    return [a for _, a in getaddresses([str(v) for v in vals]) if a]


def _attachments(msg: EmailMessage) -> list[Attachment]:
    out: list[Attachment] = []
    for part in msg.iter_attachments():
        ctype = part.get_content_type()
        filename = part.get_filename() or ("attached-message.eml" if ctype == "message/rfc822" else "attachment")
        if ctype == "message/rfc822":
            inner = part.get_payload(0) if part.is_multipart() else part.get_payload()
            data = inner.as_bytes() if isinstance(inner, Message) else bytes(part.get_payload(decode=True) or b"")
        else:
            data = part.get_payload(decode=True) or b""
        out.append(Attachment(filename=filename, content_type=ctype, data=data))
    return out


def parse_raw(raw: bytes) -> InboundEmail:
    msg: EmailMessage = BytesParser(policy=policy.default).parsebytes(raw)  # type: ignore[assignment]
    from_name, from_addr = parseaddr(str(msg.get("From", "")))
    body = msg.get_body(preferencelist=("plain", "html"))
    text = ""
    if body is not None:
        try:
            text = body.get_content()
        except Exception:  # noqa: BLE001 - malformed charset etc.
            text = (body.get_payload(decode=True) or b"").decode("utf-8", "replace")
        if body.get_content_type() == "text/html":
            text = html_to_text(text)
    headers: dict[str, str] = {}
    for k, v in msg.items():
        headers.setdefault(k.lower(), str(v))
    return InboundEmail(
        from_address=from_addr.lower(),
        from_name=from_name,
        to=_addresses(msg, "To"),
        cc=_addresses(msg, "Cc"),
        subject=str(msg.get("Subject", "")),
        message_id=_clean_id(msg.get("Message-ID")),
        in_reply_to=_clean_id(msg.get("In-Reply-To")),
        references=str(msg.get("References")) if msg.get("References") else None,
        text=text or "",
        headers=headers,
        attachments=_attachments(msg),
        extra_recipients=[*_addresses(msg, "Delivered-To"), *_addresses(msg, "X-Original-To")],
    )


def parse_postmark(payload: dict) -> InboundEmail:
    """Postmark inbound webhook JSON. Prefers RawEmail when the server includes it."""
    if payload.get("RawEmail"):
        em = parse_raw(payload["RawEmail"].encode("utf-8", "surrogateescape"))
        em.mailbox_hash = payload.get("MailboxHash") or None
        return em
    headers = {h["Name"].lower(): h["Value"] for h in payload.get("Headers", []) if "Name" in h}
    full = payload.get("FromFull") or {}
    text = payload.get("TextBody") or html_to_text(payload.get("HtmlBody") or "")
    return InboundEmail(
        from_address=(full.get("Email") or payload.get("From") or "").lower(),
        from_name=full.get("Name") or payload.get("FromName") or "",
        to=[t["Email"] for t in payload.get("ToFull", []) if t.get("Email")],
        cc=[t["Email"] for t in payload.get("CcFull", []) if t.get("Email")],
        subject=payload.get("Subject") or "",
        message_id=_clean_id(headers.get("message-id")),
        in_reply_to=_clean_id(headers.get("in-reply-to")),
        references=headers.get("references"),
        text=text,
        headers=headers,
        attachments=[
            Attachment(
                filename=a.get("Name") or "attachment",
                content_type=a.get("ContentType") or "application/octet-stream",
                data=base64.b64decode(a.get("Content") or ""),
            )
            for a in payload.get("Attachments", [])
        ],
        extra_recipients=[payload["OriginalRecipient"]] if payload.get("OriginalRecipient") else [],
        mailbox_hash=payload.get("MailboxHash") or None,
    )


def _clean_id(v) -> str | None:
    if not v:
        return None
    s = str(v).strip()
    m = re.search(r"<[^>]+>", s)
    return m.group(0) if m else f"<{s.strip('<>')}>"


def reference_ids(em: InboundEmail) -> list[str]:
    ids = re.findall(r"<[^>]+>", em.references or "")
    if em.in_reply_to:
        ids.append(em.in_reply_to)
    return list(dict.fromkeys(ids))


# --------------------------------------------------------------------- reply text

_QUOTE_HEADER = re.compile(
    r"^(On .{0,200}wrote:|-{2,}\s*Original Message\s*-{2,}|From: .+|_{10,})\s*$", re.IGNORECASE
)


def strip_quoted(text: str) -> str:
    """Keep only the new part of a reply: drop '>' lines and everything after 'On ... wrote:'."""
    lines = text.replace("\r\n", "\n").split("\n")
    out: list[str] = []
    for i, line in enumerate(lines):
        if _QUOTE_HEADER.match(line.strip()) and i > 0:
            break
        if line.lstrip().startswith(">"):
            continue
        out.append(line)
    return "\n".join(out).strip()


# --------------------------------------------------------------------- auto replies

_AUTO_SUBJECT = re.compile(
    r"^(automatic reply|auto[- ]?reply|out of (the )?office|ooo\b|auto:|undeliverable|delivery status notification|mail delivery failed|returned mail)",
    re.IGNORECASE,
)


def auto_reply_reason(em: InboundEmail) -> str | None:
    h = em.headers
    auto = h.get("auto-submitted", "").lower()
    if auto and auto != "no":
        return f"Auto-Submitted: {auto}"
    if "x-autoreply" in h or "x-autorespond" in h or "x-auto-response-suppress" in h and _AUTO_SUBJECT.match(em.subject):
        return "auto-responder header"
    if h.get("precedence", "").lower() in {"auto_reply", "bulk", "junk"}:
        return f"Precedence: {h['precedence']}"
    if "multipart/report" in h.get("content-type", "").lower():
        return "delivery status report (bounce)"
    local = em.from_address.split("@")[0]
    if local in {"mailer-daemon", "postmaster"}:
        return "bounce sender"
    if _AUTO_SUBJECT.match(em.subject.strip()):
        return "auto-reply subject"
    return None


# --------------------------------------------------------------------- outbound


def build_mime(
    *,
    from_name: str,
    from_address: str,
    to: list[str],
    cc: list[str],
    reply_to: str | None,
    subject: str,
    text: str,
    message_id: str,
    in_reply_to: str | None,
    references: str | None,
    date: datetime | None = None,
) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = f'"{from_name}" <{from_address}>'
    msg["To"] = ", ".join(to)
    if cc:
        msg["Cc"] = ", ".join(cc)
    if reply_to:
        msg["Reply-To"] = reply_to
    msg["Subject"] = subject
    msg["Message-ID"] = message_id
    msg["Date"] = format_datetime((date or datetime.now(UTC)).replace(tzinfo=UTC))
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
    if references:
        msg["References"] = references
    msg.set_content(text)
    return msg

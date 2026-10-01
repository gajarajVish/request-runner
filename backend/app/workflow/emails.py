"""Email wording. Deterministic templates over the confirmed checklist: the model never writes
free text that goes to a provider without the requester seeing the checklist it came from."""

from __future__ import annotations

from datetime import date
from typing import Any

from ..config import get_settings
from ..models import ChecklistItem, Request, User


def _d(d: date | None) -> str:
    return d.strftime("%b %-d, %Y") if d else ""


def first_name(name: str | None, email: str) -> str:
    if name:
        return name.split()[0]
    return email.split("@")[0].split(".")[0].capitalize()


def item_lines(items: list[ChecklistItem], indent: str = "  ", start: int = 1) -> list[str]:
    lines = []
    for n, it in enumerate(items, start=start):
        lines.append(f"{indent}{n}. {it.description}")
        c = it.criteria or {}
        details = []
        if c.get("format"):
            details.append(f"Format: {c['format']}")
        if (c.get("signature") or {}).get("required"):
            sig = c["signature"]
            who = ", ".join(sig.get("parties") or []) if sig.get("mode") == "named_parties" else ""
            details.append(f"Signed{' by ' + who if who else ''}")
        for sp in it.subpoints or []:
            cond = f" ({sp['condition']})" if sp.get("condition") else ""
            details.append(f"{sp['text']}{cond}")
        for d in details:
            lines.append(f"{indent}   - {d}")
    return lines


def footer(requester: User) -> str:
    app = get_settings().app_name
    return (
        "--\n"
        f"{app} is collecting this for {requester.name}. Your replies and files are shared with "
        f"{requester.name}. To reach {requester.name} directly, email {requester.email}."
    )


def how_to_reply(hub_link: str) -> str:
    return (
        f"Reply to this email with the files attached, or upload them here: {hub_link}\n"
        "If something is unclear, just reply with your question. If you can't provide some of it, "
        "tell us - reply \"that's everything I have\" and we'll let "
        "the requester know."
    )


def from_name(requester: User) -> str:
    return f"{requester.name} via {get_settings().app_name}"


# --------------------------------------------------------------------------- initial


def initial_subject(req: Request, requester: User, org: str | None) -> str:
    who = f" for {org}" if org else ""
    return f"{req.title}{who}: request from {requester.name}"


def initial_single(req: Request, items: list[ChecklistItem], requester: User, provider_name: str | None, provider_email: str, hub_link: str) -> str:
    due = f" by {_d(req.due_date)}" if req.due_date else ""
    return "\n".join(
        [
            f"Hi {first_name(provider_name, provider_email)},",
            "",
            f"{requester.name} asked {get_settings().app_name} to collect the following from you{due}:",
            "",
            *item_lines(items),
            "",
            how_to_reply(hub_link),
            "",
            footer(requester),
        ]
    )


def batch_subject(requester: User, n: int) -> str:
    return f"{n} item{'s' if n != 1 else ''} requested by {requester.name}"


def request_block(req: Request, items: list[ChecklistItem], extra: str | None = None) -> list[str]:
    head = f"[{req.external_id}] {req.title}" if req.external_id else req.title
    due = f" - due {_d(req.due_date)}" if req.due_date else ""
    lines = [f"{head}{due}"]
    if extra:
        lines.append(f"   ({extra})")
    lines += item_lines(items, indent="   ")
    return lines


def initial_batch(blocks: list[list[str]], requester: User, provider_name: str | None, provider_email: str, hub_link: str) -> str:
    body: list[str] = [
        f"Hi {first_name(provider_name, provider_email)},",
        "",
        f"{requester.name} asked {get_settings().app_name} to collect the following {len(blocks)} item"
        f"{'s' if len(blocks) != 1 else ''} from you. They are all on one page, where you can upload a file "
        "or type an answer against each item:",
        f"  {hub_link}",
        "",
    ]
    for b in blocks:
        body += b + [""]
    body += [
        "You can also reply to this email with files attached or answers typed in - mention the item "
        "number (e.g. R-01) so we file it correctly. Questions are welcome. If you can't provide something, "
        "say so and we'll let the requester know.",
        "",
        footer(requester),
    ]
    return "\n".join(body)


# --------------------------------------------------------------------------- follow-ups


def outstanding_lines(entries: list[dict[str, Any]]) -> list[str]:
    """entries: [{label, missing: [str], due}] -> bullet lines."""
    lines = []
    for e in entries:
        due = f" (due {_d(e['due'])})" if e.get("due") else ""
        lines.append(f"  * {e['label']}{due}")
        for m in e.get("missing") or []:
            lines.append(f"      - {m}")
    return lines


def provider_update(
    *,
    requester: User,
    provider_name: str | None,
    provider_email: str,
    hub_link: str,
    answers: list[dict[str, str]] | None = None,
    outstanding: list[dict[str, Any]] | None = None,
    overdue: list[dict[str, Any]] | None = None,
    due_soon: list[dict[str, Any]] | None = None,
    changes: list[str] | None = None,
    received_summary: str | None = None,
) -> str:
    """One message per provider per cycle. Each request appears in at most one section."""
    parts: list[str] = [f"Hi {first_name(provider_name, provider_email)},", ""]
    if answers:
        parts.append("Answers to your questions:")
        for a in answers:
            parts += [f"  Q: {a['question']}", f"  A: {a['answer']}", ""]
    if changes:
        parts.append(f"{requester.name} has updated what's being requested:")
        parts += [f"  * {c}" for c in changes]
        parts += ["Nothing else has changed.", ""]
    if outstanding:
        if received_summary:
            parts += [f"Thanks - we received {received_summary}.", ""]
        parts.append(f"Here is what {requester.name} still needs, and why:")
        parts += outstanding_lines(outstanding)
        parts.append("")
    if overdue:
        parts.append(f"These items for {requester.name} are now past their due date:")
        parts += outstanding_lines(overdue)
        parts.append("")
    if due_soon:
        parts.append(f"A reminder that these items for {requester.name} are due soon:")
        parts += outstanding_lines(due_soon)
        parts.append("")
    if outstanding or overdue or due_soon:
        parts += [how_to_reply(hub_link), ""]
    parts.append(footer(requester))
    return "\n".join(parts)


def closed_notice(requester: User, provider_name: str | None, provider_email: str, labels: list[str], reason: str) -> str:
    return "\n".join(
        [
            f"Hi {first_name(provider_name, provider_email)},",
            "",
            f"{requester.name} no longer needs the following, so you can stop working on it ({reason}):",
            *[f"  * {lbl}" for lbl in labels],
            "",
            "Thank you for your help.",
            "",
            footer(requester),
        ]
    )


def escalation(*, requester: User, backup_email: str, provider_name: str | None, provider_email: str, entries: list[dict[str, Any]]) -> str:
    who = provider_name or provider_email
    return "\n".join(
        [
            f"Hi {first_name(None, backup_email)},",
            "",
            f"You're listed as the backup contact for these items {requester.name} requested from {who} "
            f"({provider_email}). They are overdue and we haven't received what's needed:",
            "",
            *outstanding_lines(entries),
            "",
            f"Could you help get them to {requester.name}, or let us know who can? Reply to this email "
            "with the files or answers.",
            "",
            footer(requester),
        ]
    )


def requester_notice(requester: User, title: str, lines: list[str], link: str) -> str:
    return "\n".join([f"Hi {first_name(requester.name, requester.email)},", "", *lines, "", f"Open the request: {link}"])

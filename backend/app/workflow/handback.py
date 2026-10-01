"""The handback: what the requester gets when a request completes, closes, or hits a limit."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit, clock
from ..config import get_settings
from ..models import Check, EvidenceAssignment, EvidenceFile, Request
from . import emails, outbox, states
from .common import add_comment, current_version, effective_verdicts, latest_check, requester

REASONS = {
    "complete": "Every checklist item is met.",
    "closed_by_provider": "The provider said they have nothing more to send.",
    "follow_up_limit": "The provider still hasn't sent everything after the maximum number of automatic follow-ups.",
    "accepted": "You accepted what was received.",
    "cancelled": "You cancelled the request.",
}


def summary(s: Session, req: Request) -> dict[str, Any]:
    v = current_version(s, req)
    verdicts = effective_verdicts(s, req)
    items = []
    for it in v.items if v else []:
        ev = verdicts.get(it.key, {})
        cites = [
            {"filename": c.get("filename"), "file_id": c.get("file_id"), "location": c.get("location"), "quote": c.get("quote"), "visual": c.get("visual"), "verified": c.get("verified")}
            for c in ev.get("citations", []) + [c for sp in ev.get("subpoints", []) for c in sp.get("citations", [])]
            if c.get("verified") or (c.get("visual") and not c.get("problem"))
        ]
        items.append(
            {
                "key": it.key,
                "description": it.description,
                "verdict": ev.get("verdict", "pending"),
                "source": ev.get("source"),
                "rationale": ev.get("rationale"),
                "missing": ev.get("missing", []),
                "evidence": cites,
                "review_flags": ev.get("review_flags", []),
            }
        )
    fids = s.scalars(select(EvidenceAssignment.file_id).where(EvidenceAssignment.request_id == req.id)).all()
    files = [s.get(EvidenceFile, i) for i in sorted(set(fids))]
    chk = latest_check(s, req)
    return {
        "items": items,
        "met": sum(1 for i in items if i["verdict"] == "met"),
        "total": len(items),
        "gaps": [i for i in items if i["verdict"] != "met"],
        "files": [
            {"id": f.id, "filename": f.filename, "kind": f.kind, "status": f.extraction_status, "reason": f.unreadable_reason, "source": f.source}
            for f in files
            if f is not None
        ],
        "suspicious": (chk.suspicious if chk else []),
        "flags": req.flags or [],
    }


def hand_back(s: Session, req: Request, *, reason: str) -> None:
    now = clock.now(s)
    req.handed_back_at = now
    req.handback_reason = reason
    data = summary(s, req)
    data["reason"] = reason
    data["reason_text"] = REASONS.get(reason, reason)
    add_comment(s, req, author="agent", kind="handback", body=REASONS.get(reason, reason), payload=data)
    audit.log(s, actor="agent", action="handed_back", workspace_id=req.workspace_id, request_id=req.id, reason=reason, met=data["met"], total=data["total"])
    user = requester(s, req)
    lines = [f"“{req.title}” - {REASONS.get(reason, reason)}", ""]
    for it in data["items"]:
        mark = {"met": "MET", "partly_met": "PARTLY MET", "not_met": "MISSING", "unreadable": "UNREADABLE"}.get(it["verdict"], it["verdict"].upper())
        where = "; ".join(f"{e['filename']} {e['location']}".strip() for e in it["evidence"][:3])
        lines.append(f"  [{mark}] {it['description']}" + (f" - {where}" if where else ""))
        for m in it["missing"][:3]:
            lines.append(f"        - {m}")
    lines += ["", f"{len(data['files'])} file(s) and the full conversation are on the request page."]
    link = f"{get_settings().app_base_url.rstrip('/')}/requests/{req.id}"
    outbox.queue_message(
        s,
        workspace_id=req.workspace_id,
        kind="requester_notice",
        idempotency_key=f"handback:{req.id}:{reason}:{req.current_version_id}",
        to=[user.email],
        subject=f"[{get_settings().app_name}] {req.title}: {states.LABELS.get(req.state, req.state).lower()}",
        text=emails.requester_notice(user, req.title, lines, link),
        from_name=get_settings().app_name,
        request_id=req.id,
    )


def latest_checks(s: Session, req: Request) -> list[Check]:
    return list(s.scalars(select(Check).where(Check.request_id == req.id).order_by(Check.id.desc())).all())

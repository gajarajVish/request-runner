"""Small shared helpers: comments, current checklist, latest verdicts, providers."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit, clock
from ..models import (
    Check,
    ChecklistItem,
    ChecklistVersion,
    Comment,
    Provider,
    Request,
    RequestDependency,
    User,
    VerdictOverride,
)


def add_comment(
    session: Session,
    req: Request,
    *,
    author: str,
    body: str,
    kind: str = "message",
    payload: dict[str, Any] | None = None,
    user_id: int | None = None,
) -> Comment:
    c = Comment(
        request_id=req.id,
        author=author,
        author_user_id=user_id,
        kind=kind,
        body=body,
        payload=payload or {},
        created_at=clock.now(session),
    )
    session.add(c)
    session.flush()
    audit.emit(session, req.workspace_id, "comment", req.id, {"comment_id": c.id})
    return c


def current_version(session: Session, req: Request) -> ChecklistVersion | None:
    return session.get(ChecklistVersion, req.current_version_id) if req.current_version_id else None


def latest_proposed(session: Session, req: Request) -> ChecklistVersion | None:
    return session.scalars(
        select(ChecklistVersion)
        .where(ChecklistVersion.request_id == req.id, ChecklistVersion.status == "proposed")
        .order_by(ChecklistVersion.number.desc())
    ).first()


def next_version_number(session: Session, req: Request) -> int:
    nums = session.scalars(select(ChecklistVersion.number).where(ChecklistVersion.request_id == req.id)).all()
    return (max(nums) if nums else 0) + 1


def latest_check(session: Session, req: Request) -> Check | None:
    if not req.current_version_id:
        return None
    return session.scalars(
        select(Check)
        .where(Check.request_id == req.id, Check.version_id == req.current_version_id, Check.status == "checked")
        .order_by(Check.id.desc())
    ).first()


def effective_verdicts(session: Session, req: Request) -> dict[str, dict[str, Any]]:
    """Per item key: the latest checked verdict, with any requester override applied."""
    version = current_version(session, req)
    if version is None:
        return {}
    out: dict[str, dict[str, Any]] = {
        i.key: {"verdict": "pending", "source": "none", "rationale": "", "missing": [], "citations": [], "subpoints": [], "review_flags": []}
        for i in version.items
    }
    chk = latest_check(session, req)
    if chk:
        for v in chk.verdicts:
            if v.item_key in out:
                out[v.item_key] = {
                    "verdict": v.verdict,
                    "source": "agent",
                    "check_id": chk.id,
                    "rationale": v.rationale,
                    "missing": v.missing,
                    "citations": v.citations,
                    "subpoints": v.subpoints,
                    "review_flags": v.review_flags,
                    "model_verdict": v.model_verdict,
                }
    overrides = session.scalars(
        select(VerdictOverride)
        .where(VerdictOverride.request_id == req.id, VerdictOverride.version_id == version.id)
        .order_by(VerdictOverride.id)
    ).all()
    for o in overrides:
        if o.item_key in out:
            out[o.item_key] = {**out[o.item_key], "verdict": o.verdict, "source": "requester_override", "override_reason": o.reason}
    return out


def all_items_met(session: Session, req: Request) -> bool:
    v = effective_verdicts(session, req)
    return bool(v) and all(x["verdict"] == "met" for x in v.values())


def dependencies(session: Session, req: Request) -> list[Request]:
    ids = session.scalars(select(RequestDependency.depends_on_id).where(RequestDependency.request_id == req.id)).all()
    return [session.get(Request, i) for i in ids]  # type: ignore[misc]


def dependents(session: Session, req: Request) -> list[Request]:
    ids = session.scalars(select(RequestDependency.request_id).where(RequestDependency.depends_on_id == req.id)).all()
    return [session.get(Request, i) for i in ids]  # type: ignore[misc]


def get_or_create_provider(session: Session, workspace_id: int, email: str, name: str | None = None, org: str | None = None) -> Provider:
    email = email.strip().lower()
    p = session.scalars(select(Provider).where(Provider.workspace_id == workspace_id, Provider.email == email)).first()
    if p is None:
        p = Provider(workspace_id=workspace_id, email=email, name=name, organization=org)
        session.add(p)
        session.flush()
    else:
        if name and not p.name:
            p.name = name
        if org and not p.organization:
            p.organization = org
    return p


def requester(session: Session, req: Request) -> User:
    u = session.get(User, req.requester_id)
    assert u is not None
    return u


def item_label(item: ChecklistItem) -> str:
    return item.description


def add_flag(req: Request, code: str, message: str) -> None:
    flags = [f for f in (req.flags or []) if f.get("code") != code]
    flags.append({"code": code, "message": message})
    req.flags = flags


def clear_flag(req: Request, code: str) -> None:
    req.flags = [f for f in (req.flags or []) if f.get("code") != code]


def request_label(req: Request) -> str:
    return f"{req.external_id} {req.title}" if req.external_id else req.title

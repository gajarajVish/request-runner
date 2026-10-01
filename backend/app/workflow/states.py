"""Request state machine. Code owns every transition; model output never sets state directly."""

from __future__ import annotations

from sqlalchemy.orm import Session

from .. import audit, clock
from ..models import Request

SCOPING = "scoping"
WAITING_REQUESTER = "waiting_requester"
READY_TO_SEND = "ready_to_send"
WAITING_PROVIDER = "waiting_provider"
CHECKING = "checking"
NEEDS_MORE = "needs_more"
HANDED_BACK = "handed_back"  # follow-up limit reached; requester decides
COMPLETE = "complete"
CLOSED_BY_PROVIDER = "closed_by_provider"
ACCEPTED = "accepted"  # requester accepted what's there
CANCELLED = "cancelled"

TERMINAL = {COMPLETE, CLOSED_BY_PROVIDER, ACCEPTED, CANCELLED}
OPEN_WITH_PROVIDER = {WAITING_PROVIDER, CHECKING, NEEDS_MORE, HANDED_BACK}

_ACTIVE = {WAITING_PROVIDER, CHECKING, NEEDS_MORE, HANDED_BACK}
ALLOWED: dict[str, set[str]] = {
    SCOPING: {WAITING_REQUESTER, READY_TO_SEND, CANCELLED},
    WAITING_REQUESTER: {SCOPING, READY_TO_SEND, CANCELLED},
    READY_TO_SEND: {SCOPING, WAITING_REQUESTER, WAITING_PROVIDER, CANCELLED},
    WAITING_PROVIDER: {CHECKING, NEEDS_MORE, HANDED_BACK, COMPLETE, ACCEPTED, CANCELLED, CLOSED_BY_PROVIDER},
    CHECKING: {WAITING_PROVIDER, NEEDS_MORE, HANDED_BACK, COMPLETE, CLOSED_BY_PROVIDER, ACCEPTED, CANCELLED},
    NEEDS_MORE: {CHECKING, HANDED_BACK, COMPLETE, CLOSED_BY_PROVIDER, ACCEPTED, CANCELLED, WAITING_PROVIDER},
    HANDED_BACK: {CHECKING, NEEDS_MORE, COMPLETE, CLOSED_BY_PROVIDER, ACCEPTED, CANCELLED, WAITING_PROVIDER},
    COMPLETE: set(),
    CLOSED_BY_PROVIDER: set(),
    ACCEPTED: set(),
    CANCELLED: set(),
}

LABELS = {
    SCOPING: "Scoping",
    WAITING_REQUESTER: "Waiting for requester",
    READY_TO_SEND: "Ready to send",
    WAITING_PROVIDER: "Waiting for provider",
    CHECKING: "Checking",
    NEEDS_MORE: "Needs more",
    HANDED_BACK: "Handed back",
    COMPLETE: "Complete",
    CLOSED_BY_PROVIDER: "Closed by provider",
    ACCEPTED: "Accepted by requester",
    CANCELLED: "Cancelled",
}


class InvalidTransition(Exception):
    pass


def transition(session: Session, req: Request, new: str, *, actor: str, reason: str = "", actor_detail: str | None = None) -> None:
    old = req.state
    if old == new:
        return
    if new not in ALLOWED.get(old, set()):
        raise InvalidTransition(f"{old} -> {new}")
    req.state = new
    now = clock.now(session)
    req.updated_at = now
    if new in TERMINAL:
        req.closed_at = now
        req.followup_due_at = None
    audit.log(
        session,
        actor=actor,
        actor_detail=actor_detail,
        action="state_changed",
        workspace_id=req.workspace_id,
        request_id=req.id,
        old=old,
        new=new,
        reason=reason,
    )
    audit.emit(session, req.workspace_id, "request", req.id, {"state": new})

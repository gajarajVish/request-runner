"""Audit log + change feed. Every email, file, check and decision goes through `log`."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from . import clock
from .models import AuditLog, Event


def log(
    session: Session,
    *,
    actor: str,
    action: str,
    workspace_id: int | None,
    request_id: int | None = None,
    actor_detail: str | None = None,
    **detail: Any,
) -> AuditLog:
    entry = AuditLog(
        workspace_id=workspace_id,
        request_id=request_id,
        actor=actor,
        actor_detail=actor_detail,
        action=action,
        detail=detail,
        at=clock.now(session),
    )
    session.add(entry)
    if workspace_id is not None:
        emit(session, workspace_id, "audit", request_id, {"action": action})
    return entry


def emit(
    session: Session, workspace_id: int, topic: str, request_id: int | None = None, data: dict | None = None
) -> None:
    session.add(
        Event(workspace_id=workspace_id, topic=topic, request_id=request_id, data=data or {}, at=clock.now(session))
    )

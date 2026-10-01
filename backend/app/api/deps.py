"""Request-scoped dependencies: DB session, the signed-in requester, workspace scoping."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..db import new_session
from ..models import User
from ..models import Request as RequestModel


def db() -> Iterator[Session]:
    s = new_session()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def current_user(request: Request, s: Session = Depends(db)) -> User:
    uid = request.session.get("user_id")
    user = s.get(User, uid) if uid else None
    if user is None:
        raise HTTPException(401, "sign in required")
    return user


def owned_request(rid: int, user: User, s: Session) -> RequestModel:
    """Workspace authorization: a request from another workspace is indistinguishable from a missing one."""
    req = s.get(RequestModel, rid)
    if req is None or req.workspace_id != user.workspace_id:
        raise HTTPException(404, "not found")
    return req

"""Upload hub access tokens.

One hub per provider (per workspace). Each email that carries a link gets a fresh random
256-bit token; only its sha256 is stored. A token opens the hub while at least one of the
provider's items is still eligible: open, not closed by this provider, and within
max(due date + grace, token issuance + minimum lifetime). Tokens are revoked when nothing
eligible remains, and can be revoked or rotated manually.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit, clock
from ..config import get_settings
from ..models import Provider, Request, RequestOwner, UploadToken
from . import states


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def issue_token(session: Session, provider: Provider) -> str:
    token = secrets.token_urlsafe(32)  # 256 bits
    session.add(
        UploadToken(
            workspace_id=provider.workspace_id,
            provider_id=provider.id,
            token_hash=_hash(token),
            issued_at=clock.now(session),
        )
    )
    session.flush()
    return token


def hub_url(token: str) -> str:
    return f"{get_settings().app_base_url.rstrip('/')}/u/{token}"


def _item_deadline(req: Request, issued_at: datetime) -> datetime:
    s = get_settings()
    by_issue = issued_at + timedelta(days=s.upload_token_min_days)
    if req.due_date is None:
        return by_issue
    by_due = datetime(req.due_date.year, req.due_date.month, req.due_date.day) + timedelta(days=s.upload_token_grace_days + 1)
    return max(by_issue, by_due)


def eligible_requests(session: Session, provider: Provider, issued_at: datetime) -> list[Request]:
    now = clock.now(session)
    owners = session.scalars(select(RequestOwner).where(RequestOwner.provider_id == provider.id)).all()
    out = []
    for o in owners:
        req = o.request
        if req.workspace_id != provider.workspace_id:
            continue
        if req.state not in states.OPEN_WITH_PROVIDER or o.closed_at is not None:
            continue
        if now > _item_deadline(req, issued_at):
            continue
        out.append(req)
    return sorted(out, key=lambda r: (r.due_date or datetime.max.date(), r.id))


def resolve(session: Session, token: str) -> tuple[UploadToken, Provider, list[Request]] | None:
    if not token or len(token) > 100:
        return None
    row = session.scalars(select(UploadToken).where(UploadToken.token_hash == _hash(token))).first()
    if row is None or row.revoked_at is not None:
        return None
    provider = session.get(Provider, row.provider_id)
    assert provider is not None
    reqs = eligible_requests(session, provider, row.issued_at)
    if not reqs:
        row.revoked_at = clock.now(session)
        row.revoked_reason = "no eligible items"
        audit.log(session, actor="system", action="upload_token_revoked", workspace_id=row.workspace_id, reason="no eligible items", provider=provider.email)
        return None
    return row, provider, reqs


def revoke_all(session: Session, provider: Provider, reason: str) -> int:
    n = 0
    for row in session.scalars(select(UploadToken).where(UploadToken.provider_id == provider.id, UploadToken.revoked_at.is_(None))):
        row.revoked_at = clock.now(session)
        row.revoked_reason = reason
        n += 1
    audit.log(session, actor="requester", action="upload_tokens_revoked", workspace_id=provider.workspace_id, provider=provider.email, count=n, reason=reason)
    return n


def revoke_if_nothing_eligible(session: Session, provider: Provider) -> None:
    for row in session.scalars(select(UploadToken).where(UploadToken.provider_id == provider.id, UploadToken.revoked_at.is_(None))):
        if not eligible_requests(session, provider, row.issued_at):
            row.revoked_at = clock.now(session)
            row.revoked_reason = "no eligible items"

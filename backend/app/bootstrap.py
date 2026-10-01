"""Database migration + seed data."""

from __future__ import annotations

from pathlib import Path

import bcrypt
from alembic import command
from alembic.config import Config
from sqlalchemy import select

from .config import BACKEND_DIR, get_settings
from .db import get_engine, session_scope
from .models import Base, User, Workspace

SEED_USERS = [
    # (name, email, password) - replace emails with inboxes you control (see README)
    ("Sam Rivera", "sam@example.com", "requester"),
    ("Alex Chen", "alex@example.com", "requester"),
]


def migrate() -> None:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    cfg.set_main_option("sqlalchemy.url", get_settings().sqlalchemy_url)
    cfg.attributes["skip_logging"] = True
    with get_engine().begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "head")


def create_all() -> None:
    """Tests: build the schema straight from the models."""
    Base.metadata.create_all(get_engine())


def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()


def seed(users: list[tuple[str, str, str]] | None = None, workspace_name: str = "Alder & Finch Co.") -> None:
    import os

    env_users = os.environ.get("SEED_USERS")  # "Name|email|password;Name|email|password"
    if users is None and env_users:
        users = [tuple(u.split("|")) for u in env_users.split(";") if u.strip()]  # type: ignore[misc]
    users = users or SEED_USERS
    with session_scope() as s:
        ws = s.scalars(select(Workspace)).first()
        if ws is None:
            ws = Workspace(name=workspace_name, timezone=get_settings().workspace_timezone)
            s.add(ws)
            s.flush()
        for name, email, pw in users:
            if s.scalars(select(User).where(User.email == email.lower())).first() is None:
                s.add(User(workspace_id=ws.id, name=name, email=email.lower(), password_hash=hash_password(pw)))


def ensure_dirs() -> None:
    s = get_settings()
    for d in (s.data_dir, s.blob_dir, s.outbox_dir):
        Path(d).mkdir(parents=True, exist_ok=True)

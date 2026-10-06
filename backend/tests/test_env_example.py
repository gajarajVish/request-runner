"""`.env.example` is the first thing a new developer copies, so it must parse cleanly."""

from __future__ import annotations

from dotenv import dotenv_values

from app.config import REPO_DIR


def test_no_comment_is_read_as_a_value() -> None:
    values = dotenv_values(REPO_DIR / ".env.example")
    assert {k: v for k, v in values.items() if v and "#" in v} == {}


def test_blank_data_dir_and_secret_fall_back_to_defaults(monkeypatch) -> None:
    from app.config import Settings

    monkeypatch.setenv("DATA_DIR", "")
    monkeypatch.setenv("SESSION_SECRET", "")
    s = Settings(_env_file=None)
    assert s.data_dir == REPO_DIR / "var"
    assert s.session_secret == Settings.model_fields["session_secret"].default

"""Application settings, read from the environment (and `.env`)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_DIR / ".env", BACKEND_DIR / ".env"), extra="ignore"
    )

    # "development" enables the user switcher and the demo clock; "production" disables both.
    app_env: str = "development"
    app_name: str = "RequestRunner"
    app_base_url: str = "http://localhost:5173"
    session_secret: str = "dev-only-session-secret-change-me"

    data_dir: Path = REPO_DIR / "var"
    database_url: str = ""  # defaults to sqlite in data_dir

    # LLM
    llm_provider: str = "anthropic"  # anthropic | fake
    anthropic_api_key: str = ""
    llm_strong_model: str = "claude-opus-5"
    llm_fast_model: str = "claude-haiku-4-5"
    llm_strong_effort: str = "high"
    llm_max_retries: int = 2  # retries for schema-invalid output
    llm_server_fallbacks: bool = True  # server-side refusal fallback for Opus 5

    # Email
    email_provider: str = "file"  # file | postmark | sendgrid
    email_from_address: str = "requests@mail.example.com"
    email_inbound_domain: str = "in.example.com"
    email_inbound_prefix: str = "req"
    email_inbound_basic_auth: str = ""  # "user:password" expected on inbound webhooks
    postmark_server_token: str = ""
    postmark_message_stream: str = "outbound"
    sendgrid_api_key: str = ""

    # Uploads
    upload_max_file_bytes: int = 25 * 1024 * 1024
    upload_max_request_bytes: int = 100 * 1024 * 1024
    upload_token_min_days: int = 14
    upload_token_grace_days: int = 7

    # Workflow policy
    workspace_timezone: str = "America/New_York"
    max_auto_contacts: int = 3
    reminder_days_before_due: int = 2
    overdue_notice_days_after_due: int = 1
    escalation_business_days_after_overdue: int = 2
    followup_debounce_seconds: int = 120
    check_debounce_seconds: int = 3  # coalesce attachments/uploads arriving together
    provider_min_gap_seconds: int = 600
    worker_poll_seconds: float = 1.0
    run_worker: bool = True

    @property
    def is_dev(self) -> bool:
        return self.app_env != "production"

    @property
    def sqlalchemy_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{self.data_dir / 'app.db'}"

    @property
    def blob_dir(self) -> Path:
        return self.data_dir / "blobs"

    @property
    def outbox_dir(self) -> Path:
        return self.data_dir / "sent-mail"


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.data_dir.mkdir(parents=True, exist_ok=True)
    return s

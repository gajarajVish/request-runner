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
    session_secret: str = "dev-only-session-secret-change-me"  # see DEFAULT_SESSION_SECRET

    seed_users: str = ""  # "Name|email|password;Name|email|password"
    data_dir: Path = REPO_DIR / "var"
    database_url: str = ""  # defaults to sqlite in data_dir

    # LLM
    llm_provider: str = "anthropic"  # anthropic | openai | fake
    anthropic_api_key: str = ""
    llm_strong_model: str = "claude-opus-5"
    llm_fast_model: str = "claude-haiku-4-5"
    llm_strong_effort: str = "high"
    llm_max_retries: int = 2  # retries for schema-invalid output
    llm_server_fallbacks: bool = True  # server-side refusal fallback for Opus 5
    openai_api_key: str = ""
    openai_strong_model: str = "gpt-5.5"
    openai_fast_model: str = "gpt-5.4-mini"
    openai_reasoning_effort: str = "medium"

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


DEFAULT_SESSION_SECRET = "dev-only-session-secret-change-me"


def production_problems(s: Settings) -> list[str]:
    """Settings that are fine for local development but unsafe for a public deployment."""
    out = []
    if s.session_secret == DEFAULT_SESSION_SECRET or len(s.session_secret) < 32:
        out.append("SESSION_SECRET must be set to a random string of at least 32 characters")
    if not s.app_base_url.startswith("https://"):
        out.append("APP_BASE_URL must be the public https:// URL (upload links and session cookies depend on it)")
    if s.email_provider in ("postmark", "sendgrid") and ":" not in s.email_inbound_basic_auth:
        out.append("EMAIL_INBOUND_BASIC_AUTH must be 'user:password' so inbound webhooks are authenticated")
    if s.email_provider == "postmark" and not s.postmark_server_token:
        out.append("POSTMARK_SERVER_TOKEN is required with EMAIL_PROVIDER=postmark")
    if s.email_provider == "sendgrid" and not s.sendgrid_api_key:
        out.append("SENDGRID_API_KEY is required with EMAIL_PROVIDER=sendgrid")
    if s.llm_provider == "anthropic" and not s.anthropic_api_key:
        out.append("ANTHROPIC_API_KEY is required with LLM_PROVIDER=anthropic")
    if s.llm_provider == "openai" and not s.openai_api_key:
        out.append("OPENAI_API_KEY is required with LLM_PROVIDER=openai")
    return out


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.data_dir.mkdir(parents=True, exist_ok=True)
    return s

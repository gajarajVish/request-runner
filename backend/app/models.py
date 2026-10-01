"""Database schema.

Vocabulary used throughout the code:

- **Request**: one thing a requester wants from one or more providers. A comment in the app
  creates one; each (merged) CSV row creates one. The brief's Part 2 "item" is a Request.
- **ChecklistVersion / ChecklistItem**: the contract. Items are the individual requirements
  ("July statement", "Signed MSA"). Confirmed versions are immutable.
- **Provider**: a person we collect from, unique per (workspace, email). Their open
  Requests form their work queue; they get one upload hub.
- **Conversation**: one outreach email thread (an outreach batch) with its own reply token.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSON, list[Any]: JSON}


# --------------------------------------------------------------------------- tenancy


class Workspace(Base):
    __tablename__ = "workspaces"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    timezone: Mapped[str] = mapped_column(String(64), default="America/New_York")


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str | None] = mapped_column(String(200))


# --------------------------------------------------------------------------- requests


class Provider(Base):
    __tablename__ = "providers"
    __table_args__ = (UniqueConstraint("workspace_id", "email"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id"), index=True)
    email: Mapped[str] = mapped_column(String(320))
    name: Mapped[str | None] = mapped_column(String(200))
    organization: Mapped[str | None] = mapped_column(String(200))
    last_auto_contact_at: Mapped[datetime | None] = mapped_column(DateTime)


class Request(Base):
    __tablename__ = "requests"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id"), index=True)
    requester_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(String(300), default="New request")
    state: Mapped[str] = mapped_column(String(40), default="scoping", index=True)
    origin: Mapped[str] = mapped_column(String(20), default="comment")  # comment | import
    # import identity: source list + external ids (aliases include merged duplicates)
    import_list_id: Mapped[int | None] = mapped_column(ForeignKey("import_lists.id"))
    external_id: Mapped[str | None] = mapped_column(String(100))
    aliases: Mapped[list[Any]] = mapped_column(default=list)
    instructions: Mapped[str | None] = mapped_column(Text)

    due_date: Mapped[date | None] = mapped_column(Date)
    backup_email: Mapped[str | None] = mapped_column(String(320))
    ownership_mode: Mapped[str] = mapped_column(String(10), default="any")  # any | all
    cc_requester: Mapped[bool] = mapped_column(Boolean, default=False)
    current_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("checklist_versions.id", use_alter=True)
    )

    # follow-up accounting (see workflow.followups)
    auto_contact_count: Mapped[int] = mapped_column(Integer, default=0)
    followup_due_at: Mapped[datetime | None] = mapped_column(DateTime)
    reminder_sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    overdue_sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime)
    handed_back_at: Mapped[datetime | None] = mapped_column(DateTime)
    handback_reason: Mapped[str | None] = mapped_column(String(60))

    flags: Mapped[list[Any]] = mapped_column(default=list)  # [{code, message}]
    needs_recheck: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime)

    owners: Mapped[list[RequestOwner]] = relationship(
        back_populates="request", cascade="all, delete-orphan", order_by="RequestOwner.id"
    )
    versions: Mapped[list[ChecklistVersion]] = relationship(
        back_populates="request",
        foreign_keys="ChecklistVersion.request_id",
        order_by="ChecklistVersion.number",
    )


class RequestOwner(Base):
    __tablename__ = "request_owners"
    __table_args__ = (UniqueConstraint("request_id", "provider_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("requests.id"), index=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("providers.id"), index=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime)  # this owner said "that's all"
    request: Mapped[Request] = relationship(back_populates="owners")
    provider: Mapped[Provider] = relationship()


class RequestDependency(Base):
    __tablename__ = "request_dependencies"
    __table_args__ = (UniqueConstraint("request_id", "depends_on_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("requests.id"), index=True)
    depends_on_id: Mapped[int] = mapped_column(ForeignKey("requests.id"), index=True)


class ChecklistVersion(Base):
    __tablename__ = "checklist_versions"
    __table_args__ = (UniqueConstraint("request_id", "number"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("requests.id"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="proposed")  # proposed|confirmed|superseded|rejected
    provider_email: Mapped[str | None] = mapped_column(String(320))
    provider_name: Mapped[str | None] = mapped_column(String(200))
    due_date: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[list[Any]] = mapped_column(default=list)  # agent assumptions shown to the requester
    created_by: Mapped[str] = mapped_column(String(20))  # agent | requester | import
    created_at: Mapped[datetime] = mapped_column(DateTime)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime)
    confirmed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    request: Mapped[Request] = relationship(back_populates="versions", foreign_keys=[request_id])
    items: Mapped[list[ChecklistItem]] = relationship(
        back_populates="version", cascade="all, delete-orphan", order_by="ChecklistItem.position"
    )


class ChecklistItem(Base):
    __tablename__ = "checklist_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("checklist_versions.id"), index=True)
    key: Mapped[str] = mapped_column(String(40))  # stable across versions, e.g. "i1"
    position: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(20))  # document | answer
    description: Mapped[str] = mapped_column(Text)
    criteria: Mapped[dict[str, Any]] = mapped_column(default=dict)
    subpoints: Mapped[list[Any]] = mapped_column(default=list)  # [{key, text, condition}]
    version: Mapped[ChecklistVersion] = relationship(back_populates="items")


# --------------------------------------------------------------------------- thread


class Comment(Base):
    """The requester-side thread: requester messages, agent replies, cards."""

    __tablename__ = "comments"
    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("requests.id"), index=True)
    author: Mapped[str] = mapped_column(String(20))  # requester | agent | provider | system
    author_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    kind: Mapped[str] = mapped_column(String(40), default="message")
    body: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[dict[str, Any]] = mapped_column(default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime)


class ProviderQuestion(Base):
    __tablename__ = "provider_questions"
    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("requests.id"), index=True)
    inbound_id: Mapped[int | None] = mapped_column(ForeignKey("inbound_messages.id"))
    provider_id: Mapped[int | None] = mapped_column(ForeignKey("providers.id"))
    question: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30))  # answered_from_scope | waiting_requester | answered_by_requester
    answer: Mapped[str | None] = mapped_column(Text)
    basis: Mapped[list[Any]] = mapped_column(default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime)  # answer emailed to provider


# --------------------------------------------------------------------------- email


class Conversation(Base):
    """One outreach email thread. Replies to its token are attributed to its requests."""

    __tablename__ = "conversations"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id"), index=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("providers.id"), index=True)
    reply_token: Mapped[str] = mapped_column(String(64), unique=True)
    subject: Mapped[str] = mapped_column(String(400))
    created_at: Mapped[datetime] = mapped_column(DateTime)
    links: Mapped[list[ConversationRequest]] = relationship(cascade="all, delete-orphan")


class ConversationRequest(Base):
    __tablename__ = "conversation_requests"
    __table_args__ = (UniqueConstraint("conversation_id", "request_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"), index=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("requests.id"), index=True)
    version_id: Mapped[int | None] = mapped_column(ForeignKey("checklist_versions.id"))


class OutboundMessage(Base):
    """Durable outbox. Rows are written in the same transaction as the decision to send."""

    __tablename__ = "outbound_messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id"), index=True)
    conversation_id: Mapped[int | None] = mapped_column(ForeignKey("conversations.id"), index=True)
    request_id: Mapped[int | None] = mapped_column(ForeignKey("requests.id"), index=True)
    kind: Mapped[str] = mapped_column(String(30))
    # initial | followup | reminder | overdue | change_notice | answer | escalation |
    # requester_notice | closed_notice
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True)
    from_name: Mapped[str] = mapped_column(String(300))
    from_address: Mapped[str] = mapped_column(String(320))
    reply_to: Mapped[str | None] = mapped_column(String(320))
    to: Mapped[list[Any]] = mapped_column(default=list)
    cc: Mapped[list[Any]] = mapped_column(default=list)
    subject: Mapped[str] = mapped_column(String(400))
    text_body: Mapped[str] = mapped_column(Text)
    message_id: Mapped[str] = mapped_column(String(300), unique=True)
    in_reply_to: Mapped[str | None] = mapped_column(String(300))
    references: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    # draft | queued | sending | sent | failed | uncertain | cancelled
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    provider_message_id: Mapped[str | None] = mapped_column(String(300))
    last_error: Mapped[str | None] = mapped_column(Text)
    request_ids: Mapped[list[Any]] = mapped_column(default=list)  # requests this message names
    counted_request_ids: Mapped[list[Any]] = mapped_column(default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)


class InboundMessage(Base):
    __tablename__ = "inbound_messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    dedupe_key: Mapped[str] = mapped_column(String(300), unique=True)
    source: Mapped[str] = mapped_column(String(20))  # postmark | sendgrid | inject
    raw_blob: Mapped[str] = mapped_column(String(80))
    workspace_id: Mapped[int | None] = mapped_column(ForeignKey("workspaces.id"), index=True)
    conversation_id: Mapped[int | None] = mapped_column(ForeignKey("conversations.id"), index=True)
    provider_id: Mapped[int | None] = mapped_column(ForeignKey("providers.id"))
    from_address: Mapped[str | None] = mapped_column(String(320))
    from_name: Mapped[str | None] = mapped_column(String(300))
    to_addresses: Mapped[list[Any]] = mapped_column(default=list)
    subject: Mapped[str | None] = mapped_column(String(400))
    message_id: Mapped[str | None] = mapped_column(String(300), index=True)
    in_reply_to: Mapped[str | None] = mapped_column(String(300))
    references: Mapped[str | None] = mapped_column(Text)
    text_body: Mapped[str | None] = mapped_column(Text)
    new_text: Mapped[str | None] = mapped_column(Text)  # body with quoted history removed
    status: Mapped[str] = mapped_column(String(20), default="received")
    # received | processing | processed | unmatched | auto_reply | closed_target | error
    match_method: Mapped[str | None] = mapped_column(String(30))
    match_notes: Mapped[list[Any]] = mapped_column(default=list)
    suggested_conversation_ids: Mapped[list[Any]] = mapped_column(default=list)
    sender_is_owner: Mapped[bool | None] = mapped_column(Boolean)
    is_auto_reply: Mapped[bool] = mapped_column(Boolean, default=False)
    classification: Mapped[dict[str, Any]] = mapped_column(default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    received_at: Mapped[datetime] = mapped_column(DateTime)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime)


# --------------------------------------------------------------------------- evidence


class EvidenceFile(Base):
    """A file (attachment or upload) or a text answer (kind=text) submitted by a provider."""

    __tablename__ = "evidence_files"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id"), index=True)
    kind: Mapped[str] = mapped_column(String(10), default="file")  # file | text
    blob: Mapped[str | None] = mapped_column(String(80))
    filename: Mapped[str] = mapped_column(String(300))
    content_type: Mapped[str | None] = mapped_column(String(120))
    detected_type: Mapped[str | None] = mapped_column(String(20))
    size: Mapped[int] = mapped_column(Integer, default=0)
    source: Mapped[str] = mapped_column(String(20))  # email | upload
    inbound_id: Mapped[int | None] = mapped_column(ForeignKey("inbound_messages.id"), index=True)
    provider_id: Mapped[int | None] = mapped_column(ForeignKey("providers.id"))
    parent_file_id: Mapped[int | None] = mapped_column(ForeignKey("evidence_files.id"))
    accepted: Mapped[bool] = mapped_column(Boolean, default=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    extraction_status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|ok|unreadable|error
    unreadable_reason: Mapped[str | None] = mapped_column(Text)
    extraction: Mapped[dict[str, Any]] = mapped_column(default=dict)
    flags: Mapped[list[Any]] = mapped_column(default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime)


class EvidenceAssignment(Base):
    """Which request(s) a piece of evidence was submitted for."""

    __tablename__ = "evidence_assignments"
    __table_args__ = (UniqueConstraint("file_id", "request_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    file_id: Mapped[int] = mapped_column(ForeignKey("evidence_files.id"), index=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("requests.id"), index=True)
    method: Mapped[str] = mapped_column(String(20))  # single | classifier | upload | requester
    created_at: Mapped[datetime] = mapped_column(DateTime)


class Check(Base):
    __tablename__ = "checks"
    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("requests.id"), index=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("checklist_versions.id"))
    trigger: Mapped[str] = mapped_column(String(60))
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|checking|checked|error
    error: Mapped[str | None] = mapped_column(Text)
    suspicious: Mapped[list[Any]] = mapped_column(default=list)
    evidence_ids: Mapped[list[Any]] = mapped_column(default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    verdicts: Mapped[list[ItemVerdict]] = relationship(cascade="all, delete-orphan")


class ItemVerdict(Base):
    __tablename__ = "item_verdicts"
    id: Mapped[int] = mapped_column(primary_key=True)
    check_id: Mapped[int] = mapped_column(ForeignKey("checks.id"), index=True)
    item_key: Mapped[str] = mapped_column(String(40))
    verdict: Mapped[str] = mapped_column(String(20))  # met | partly_met | not_met | unreadable
    model_verdict: Mapped[str] = mapped_column(String(20))  # before code-side guards
    rationale: Mapped[str] = mapped_column(Text, default="")
    missing: Mapped[list[Any]] = mapped_column(default=list)
    citations: Mapped[list[Any]] = mapped_column(default=list)
    subpoints: Mapped[list[Any]] = mapped_column(default=list)
    review_flags: Mapped[list[Any]] = mapped_column(default=list)


class VerdictOverride(Base):
    __tablename__ = "verdict_overrides"
    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("requests.id"), index=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("checklist_versions.id"))
    item_key: Mapped[str] = mapped_column(String(40))
    verdict: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str] = mapped_column(Text)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime)


class UploadToken(Base):
    __tablename__ = "upload_tokens"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id"), index=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("providers.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)
    revoked_reason: Mapped[str | None] = mapped_column(String(100))


# --------------------------------------------------------------------------- imports


class ImportList(Base):
    """A named source list (e.g. 'Q3 audit PBC'). Re-imports update the same list."""

    __tablename__ = "import_lists"
    __table_args__ = (UniqueConstraint("workspace_id", "name"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id"), index=True)
    requester_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime)


class ImportBatch(Base):
    __tablename__ = "import_batches"
    id: Mapped[int] = mapped_column(primary_key=True)
    import_list_id: Mapped[int] = mapped_column(ForeignKey("import_lists.id"), index=True)
    filename: Mapped[str] = mapped_column(String(300))
    blob: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(20), default="analyzing")
    # analyzing | review | applied | error | discarded
    errors: Mapped[list[Any]] = mapped_column(default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime)
    rows: Mapped[list[ImportRow]] = relationship(cascade="all, delete-orphan", order_by="ImportRow.position")


class ImportRow(Base):
    __tablename__ = "import_rows"
    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("import_batches.id"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    external_id: Mapped[str] = mapped_column(String(100))
    raw: Mapped[dict[str, Any]] = mapped_column(default=dict)
    content_hash: Mapped[str] = mapped_column(String(64))
    # new | unchanged | changed | duplicate | flagged | error | removed
    action: Mapped[str] = mapped_column(String(20))
    merged_into: Mapped[str | None] = mapped_column(String(100))
    changes: Mapped[list[Any]] = mapped_column(default=list)  # [{field, old, new}]
    flags: Mapped[list[Any]] = mapped_column(default=list)
    scope: Mapped[dict[str, Any]] = mapped_column(default=dict)  # proposed checklist
    ownership_mode: Mapped[str] = mapped_column(String(10), default="any")
    request_id: Mapped[int | None] = mapped_column(ForeignKey("requests.id"))
    include: Mapped[bool] = mapped_column(Boolean, default=True)


class ScopeCache(Base):
    """Row-scoping results keyed by content hash, so unchanged rows never re-hit the model."""

    __tablename__ = "scope_cache"
    content_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    result: Mapped[dict[str, Any]] = mapped_column(default=dict)


# --------------------------------------------------------------------------- ops


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int | None] = mapped_column(ForeignKey("workspaces.id"), index=True)
    request_id: Mapped[int | None] = mapped_column(ForeignKey("requests.id"), index=True)
    actor: Mapped[str] = mapped_column(String(20))  # requester | provider | agent | system
    actor_detail: Mapped[str | None] = mapped_column(String(320))
    action: Mapped[str] = mapped_column(String(60))
    detail: Mapped[dict[str, Any]] = mapped_column(default=dict)
    at: Mapped[datetime] = mapped_column(DateTime, index=True)


class Job(Base):
    """Durable work queue. `key` makes enqueueing idempotent."""

    __tablename__ = "jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(200), unique=True)
    kind: Mapped[str] = mapped_column(String(40), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(default=dict)
    run_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)


class Event(Base):
    """Change feed for SSE. Cross-process: the worker and the inject CLI write here too."""

    __tablename__ = "events"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(Integer, index=True)
    topic: Mapped[str] = mapped_column(String(40))
    request_id: Mapped[int | None] = mapped_column(Integer)
    data: Mapped[dict[str, Any]] = mapped_column(default=dict)
    at: Mapped[datetime] = mapped_column(DateTime)


class ClockState(Base):
    """Demo clock: a persisted offset applied to real time. Single row."""

    __tablename__ = "clock_state"
    id: Mapped[int] = mapped_column(primary_key=True)
    offset_seconds: Mapped[int] = mapped_column(Integer, default=0)
    last_advance_key: Mapped[str | None] = mapped_column(String(100))

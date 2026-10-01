"""Structured outputs. Every model call returns one of these, validated by pydantic.

The model only *proposes*; workflow code decides what to do with a proposal.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Verdict = Literal["met", "partly_met", "not_met", "unreadable"]
SubVerdict = Literal["met", "partly_met", "not_met", "unreadable", "not_applicable"]


# --------------------------------------------------------------------------- scoping


class SignatureCriteria(BaseModel):
    required: bool
    mode: Literal["present", "named_parties"] = Field(
        description="'present': any clear signature suffices. 'named_parties': each listed party must have signed."
    )
    parties: list[str]
    date_required: bool


class Criteria(BaseModel):
    period: str | None = Field(description="Period the document must cover, e.g. 'July-September 2026'.")
    entity: str | None = Field(description="Entity / account / counterparty it must relate to.")
    format: str | None = Field(description="Required format, e.g. 'PDF downloaded from the bank'.")
    required_elements: list[str] = Field(description="Things that must be visible in the document.")
    signature: SignatureCriteria | None
    currency_rule: str | None = Field(description="E.g. 'policy period must include today's date'. Null if none.")


class Subpoint(BaseModel):
    key: str = Field(description="Short stable key, e.g. 'a', 'b'.")
    text: str = Field(description="One specific thing the answer must state or show.")
    condition: str | None = Field(description="If this sub-point only applies in some case, say when. Else null.")


class DraftItem(BaseModel):
    kind: Literal["document", "answer"]
    description: str = Field(description="Plain-language checklist line the provider will read.")
    criteria: Criteria
    subpoints: list[Subpoint] = Field(description="For answer items: every required sub-point. Empty for most documents.")


class ScopeProposal(BaseModel):
    message_to_requester: str = Field(description="Short reply posted in the requester's thread.")
    clarifying_questions: list[str] = Field(description="Questions that must be answered before the checklist can be final.")
    title: str
    provider_name: str | None
    provider_email: str | None
    provider_organization: str | None
    due_date: str | None = Field(description="YYYY-MM-DD, or null if not given.")
    items: list[DraftItem]
    assumptions: list[str] = Field(description="Interpretations the requester should know about before confirming.")
    ready_to_confirm: bool = Field(description="True only when no clarifying question is outstanding.")


class RowScope(BaseModel):
    title: str
    vague: bool = Field(description="True if the row cannot be turned into a clear checklist without guessing.")
    vague_reason: str | None
    items: list[DraftItem]
    assumptions: list[str]


# --------------------------------------------------------------------------- replies


class AttachmentAssignment(BaseModel):
    evidence_id: str
    request_refs: list[str] = Field(description="Refs (e.g. 'Q1') this attachment is for. Empty if unclear.")


class ProviderQuestionOut(BaseModel):
    request_ref: str | None
    question: str = Field(description="The provider's question, restated faithfully.")


class ReplyClassification(BaseModel):
    substantive: bool = Field(description="False for pure thanks/acknowledgements with nothing submitted or asked.")
    closes_request: bool = Field(
        description="True only if the provider says, in their own words, they have nothing more to send."
    )
    closing_quote: str | None = Field(description="Exact words from the provider's message that close the request.")
    closing_refs: list[str] = Field(description="Refs the closing applies to; empty means all.")
    questions: list[ProviderQuestionOut]
    attachment_assignments: list[AttachmentAssignment]
    answered_refs: list[str] = Field(description="Refs whose questions the message body tries to answer.")
    mentions_attachments: bool = Field(description="True if the text says files are attached/enclosed.")
    summary: str


# --------------------------------------------------------------------------- checking


class Citation(BaseModel):
    evidence_id: str
    page: int | None = Field(description="PDF page number (1-based), for PDFs.")
    sheet: str | None = Field(description="Sheet name, for spreadsheets.")
    cell_range: str | None = Field(description="Cell or range like 'B4' or 'A3:F9', for spreadsheets.")
    paragraph: int | None
    table: int | None
    row: int | None
    quote: str | None = Field(description="Verbatim text copied from that location. Null only for visual evidence.")
    visual: bool = Field(description="True if this citation rests on what an image shows rather than quoted text.")
    note: str | None


class SubpointCheck(BaseModel):
    key: str
    verdict: SubVerdict
    citations: list[Citation]
    note: str


class ItemCheck(BaseModel):
    item_key: str
    verdict: Verdict
    rationale: str = Field(description="One or two sentences, naming the file and page that decide it.")
    missing: list[str] = Field(description="Specific gaps, phrased for the provider. Empty if met.")
    citations: list[Citation]
    subpoints: list[SubpointCheck]
    needs_review: bool
    review_reason: str | None


class SuspiciousContent(BaseModel):
    evidence_id: str
    location: str
    quote: str
    reason: str


class UnreadableEvidence(BaseModel):
    evidence_id: str
    reason: str


class CheckOutput(BaseModel):
    items: list[ItemCheck]
    suspicious: list[SuspiciousContent]
    unreadable: list[UnreadableEvidence]


# --------------------------------------------------------------------------- questions & chat


class QuestionAnswer(BaseModel):
    in_scope: bool = Field(description="True only if the confirmed checklist clearly answers the question.")
    answer: str | None = Field(description="Answer for the provider, using only the confirmed checklist.")
    basis_item_keys: list[str]
    reason: str


class ChatReply(BaseModel):
    reply: str
    proposed_action: Literal["none", "change_due_date", "send_manual_followup", "cancel", "accept"]
    new_due_date: str | None

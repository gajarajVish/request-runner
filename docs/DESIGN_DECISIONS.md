# Design decisions to settle before building

19 high-level questions. Each has a short context, the options, and a **recommended**
default. Reply with the number and either "rec", a letter, or your own call (e.g.
`1: rec, 4: B, 15: split into two items`).

---

## A. Stack and infrastructure

### 1. Language and backend framework
The backend does a lot of document handling (PDF pages, spreadsheets, images, raw MIME
email) plus a scheduler and LLM calls.
- **A. Python + FastAPI** (pypdf/pdfplumber, openpyxl, Pillow, stdlib `email`, pytest).
- B. TypeScript + Node (Fastify/Hono), one language with the frontend.
- C. Next.js full-stack (fastest UI, awkward for background jobs and webhooks).

**Recommended: A.** The document and email libraries are better, and pytest with a stubbed model is simple.

### 2. Frontend and live updates
The requester app needs a comment thread, a checklist that updates live, a dashboard, and a public upload page.
- **A. React + Vite SPA, with Server-Sent Events for live updates.**
- B. Server-rendered pages (Jinja + HTMX) with SSE. Less code, but a plainer UI.

**Recommended: A** (with Tailwind and a small component kit). SSE is enough because updates only flow from server to client, so we don't need websockets.

### 3. Database and file storage
- **A. SQLite through an ORM (SQLAlchemy), files on local disk under `var/`, addressed by content hash.**
- B. Postgres in docker-compose, with S3/MinIO for files.

**Recommended: A.** It runs locally in a few commands, and moving to Postgres/S3 later only means swapping the ORM URL and the storage adapter.

### 4. Where it runs for the demo and the live call
Inbound email webhooks need a public URL.
- **A. Run locally with a stable tunnel (cloudflared or an ngrok static domain).**
- B. Deploy to Fly.io or Render.

**Recommended: A for development, B as an option for the call** so it doesn't depend on your laptop's network. Either way we add a local `inject-eml` CLI/endpoint that feeds the starter `.eml` files through the same inbound pipeline. Tests and quick iteration use that, and the real email loop is kept for the demo.

---

## B. Email

### 5. Email provider
We need authenticated outbound mail (SPF/DKIM), inbound mail with attachments posted to a webhook, and plus-addressed Reply-To support.
- **A. Postmark.** Its inbound webhook sends clean JSON with attachments, it parses `req+TOKEN@` into a `MailboxHash` field, and its deliverability is good. Caveat: new accounts send only to the sender's own domain until Postmark approves them, so we need to check this works with your test inboxes.
- B. Mailgun. Routes + sandbox; the free tier is limited to authorized recipients.
- C. SendGrid Inbound Parse. Works, but the setup is clunkier.
- D. Amazon SES + S3/SNS for inbound. Cheapest at scale, but has the most setup.

**Recommended: A, with C as the fallback** if Postmark approval gets in the way.

### 6. Domain, addresses and the "own mailbox" question
Do you own a domain we can put DNS records on? The plan is
`"<Requester> via RequestRunner" <requests@mail.<domain>>` for outbound (SPF/DKIM/DMARC
on `mail.`) and `req+<token>@in.<domain>` for inbound (MX to the provider). On sending from the requester's own mailbox (Gmail/M365 OAuth send-as):
- **A. Explain it in the README only, and don't build it.**
- B. Build Gmail OAuth sending as a stretch goal.

**Recommended: A.** Sending from their mailbox means replies land in their inbox, so we'd lose reliable inbound matching, and it also needs mailbox-wide OAuth scopes.

### 7. How replies are matched to requests
- **Recommended order:**
  1. Opaque Reply-To token (random, not guessable, never the DB id).
  2. `In-Reply-To`/`References` matched against Message-IDs we stored.
  3. Sender address plus that sender's open requests. This is never applied automatically: the reply goes into an "unmatched" queue for the requester to assign.

Edge policies:
- **Reply to a closed or completed request:** store it, notify the requester, and send no automatic reply.
- **Auto-replies (out-of-office, `Auto-Submitted`, bounces):** log them, but they don't count as a response or a follow-up.
- **Sender isn't the provider (e.g. a colleague):** accept the content, but flag it to the requester.

Do you agree, or would you want any of these to be stricter (e.g. reject unknown senders)?

---

## C. Agent and LLM

### 8. Model provider and model use
- **A. Claude via the Anthropic SDK, behind a small `LLM` interface (a fake implementation for tests).** Use a strong model for scoping and checking, and a cheaper one for classifying replies (question / partial / "that's all" / out-of-office).
- B. Something else or provider-agnostic (e.g. LiteLLM).

**Recommended: A.** Every call returns structured output (tool / JSON schema), never free text that we then parse.

### 9. Agent architecture: who controls state?
- **A. Deterministic state machine plus narrow LLM steps.** The code owns all state transitions. The LLM only produces structured proposals: a checklist draft, an email draft, a reply classification, per-item verdicts with evidence. Guard functions decide what to do with them.
- B. An autonomous tool-using agent loop that decides next actions itself.

**Recommended: A.** It's testable with the model stubbed (requirement 9), it keeps the 3-follow-up cap enforceable, and it's the core defence against prompt injection (Q13).

### 10. How documents are read and cited
- **A. Hybrid.** Extract per-page text ourselves (PDF pages, sheet name + cell range for spreadsheets). Send page images to the model's vision input when a page has little or no text (scans, screenshots, signatures). Verdicts must cite `file + page/sheet/range` and quote the evidence, and we check that the quote actually exists in that location.
- B. Pass whole files to the model natively and trust its citations.

**Recommended: A.** Citations can be verified, and "can't read this" (encrypted, corrupt, blank, too blurry) gets detected in code instead of guessed. Open question: is a visual check for signatures acceptable, or should "signed" also need text cues (a signature block with a name and date)?

### 11. The checklist as a contract
Each item gets an id, type (`document` | `answer`), plain-language description, and structured criteria (period, entity, format, required elements, e.g. "signed by both parties"). Once confirmed it is versioned and doesn't change.
- If a provider question is covered by the scope, the agent answers it.
- If not, the agent asks the requester. **Any change to scope creates a new checklist version that the requester has to confirm.**

Proposed verdict levels: `met` / `partly met` / `not met` / `unreadable`. Example of `partly met`: the right content in the wrong format, like the xlsx statement in the starter manifest.

Do you agree with versioning and these four levels?

### 12. Judging answers to questions (Part 2)
- **A. At scoping time, break each question into required sub-points** (e.g. R-14: "is there a schedule?" plus, depending on the answer, the latest review and sign-off, or an explicit "no"). The reply is judged one sub-point at a time, and each one needs a quoted sentence that answers it. Vague policy references ("in line with our policy") don't count. The requester sees the sub-points when confirming.
- B. One overall LLM judgment per question.

**Recommended: A.** The R-17 dodge is the test case.

### 13. Defences against untrusted provider content
Proposed layers:
1. Provider text and files only ever reach the model inside clearly delimited data blocks, with a system prompt that says they're evidence.
2. Prompts that read provider content can't call any tool that changes state. They only return verdicts.
3. The state machine never accepts a "complete" that the model asserts. Completion is computed from the item verdicts.
4. Any instruction-like text found in content is flagged to the requester in the handback.

Do you want point 4 (visible "suspicious content" flags), or only silent resistance?

---

## D. Part 2: request lists

### 14. Grouping items by provider
- **A. One provider thread per (requester workspace, provider email).** It has a single Reply-To token, one upload page and one email thread, and it holds every open item for that person across imports. Follow-ups and reminders are batched into one message per provider per cycle.
- B. One thread per (import, provider).

**Recommended: A.** It matches "the same person can owe a dozen items at once" and avoids sending them several parallel emails.

### 15. Rows with two owners (R-18)
- **A. One item, shared by both owners.** It appears in both providers' threads and on both upload pages, and either person can satisfy it. Each sees that the item is shared, and follow-ups go to both.
- B. Split it into two items, one per owner (both must respond).
- C. Flag it and ask the requester to choose.

**Recommended: A, plus a note shown at import review** so the requester can switch it to B or C.

### 16. Import identity, merging and re-import
- **Identity:** `request_id` is the stable key.
- **Duplicates:** rows with different ids but identical normalised content (R-07/R-08) are merged automatically. Near-duplicates are only *suggested* for merging, and the requester confirms.
- **Re-import:** compare field by field against the last import. Unchanged rows do nothing. A changed due date or instructions produces one "change notice" to that provider. Rows removed from the CSV are flagged, not cancelled automatically.
- **Vague rows (R-25):** flagged and not sent until the requester clarifies.
- **Dependent rows (R-06 → R-05, R-12 → R-11):** sent with their dependency noted, and checked against the dependency's evidence once it arrives.
- **Due dates already past on import (R-28):** flagged at review.

Agree, or do you want removed rows to auto-cancel?

### 17. Follow-ups, reminders and escalation policy
The brief caps automatic follow-ups at 3. Proposed policy:
- **Counting:** one counter per item. Any automatic message to the provider that names the item counts against that item's 3, whether it's a pre-due reminder, a "still missing" follow-up, or an overdue notice. When an item hits 3, it is handed back to the requester.
- **Cadence (configurable):** a reminder 2 days before the due date, a follow-up within minutes of a reply that checks short, an overdue notice the day after the due date, and escalation to the backup owner 2 business days after that, with a notice to the requester.
- **No backup (R-27):** notify the requester only.
- **Demo clock:** an app-level "now" that can be advanced from an admin panel, so overdue and escalation can be shown live.

Does the counting rule match how you read the brief? Are the cadences fine?

---

## E. Access, security and scope

### 18. Requester auth and upload links
- **Requesters:** seeded users with a simple login or user switcher. No real auth, and the README says so.
- **Upload links:** a random 256-bit token, stored hashed. It's tied to one request or provider thread and expires (proposed: the later of the latest due date + 7 days, or 14 days). It's revoked on complete, close or cancel, and access is rate-limited.
- **Attachments:**
  - Allowlist: PDF, XLSX/XLS/CSV, PNG/JPG/HEIC, DOCX, EML.
  - Size cap: 25 MB.
  - Stored outside the web root and served only to the requester with `Content-Disposition: attachment`.
  - Content checked by magic bytes, not by extension.
  - Macro-enabled Office files are rejected.

Do these choices work for you, or do you want a real login (magic link)?

### 19. Scope priorities and stretch goals
Proposed build order:
1. Part 1 loop end to end on the inject CLI.
2. Real email both ways.
3. Checking with citations.
4. Part 2 import, provider threads and the upload page.
5. Reminders, escalation and the dashboard.
6. Tests throughout.

Which optional items do you want? The candidates are:
- **(a)** "Requester chat about an open request". Cheap once the scoping chat exists.
- **(b)** Multi-provider single request. This mostly comes for free with Part 2 provider threads.
- **(c)** A quiet-provider nudge.

**Recommended:** (a) and (b), and skip (c) unless there's time left.

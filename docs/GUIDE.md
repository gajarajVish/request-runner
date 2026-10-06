# RequestRunner: full guide

The short version is in the [README](../README.md).

## Running locally

Requirements: Python 3.12 with [uv](https://docs.astral.sh/uv/), and Node 20.

```bash
cp .env.example .env            # set ANTHROPIC_API_KEY (or LLM_PROVIDER=openai + OPENAI_API_KEY), or LLM_PROVIDER=fake to work offline
cd backend
uv sync
uv run rr seed                  # migrate + create the workspace and two requester accounts
uv run uvicorn app.main:app --reload --port 8000

# second terminal
cd frontend
npm install
npm run dev                     # http://localhost:5173 (proxies /api to :8000)
```

Sign in as **Sam Rivera** (`sam@example.com` / `requester`) or **Alex Chen**. In development
the login page also has a one-click user switcher. Change the seed accounts with
`SEED_USERS="Name|email|password;..."`, using inboxes you control if you want the
requester notices to reach you.

With `EMAIL_PROVIDER=file` (the default), outgoing email is written to `var/sent-mail/*.eml`
instead of being sent, and every message also appears on the request's **Email** tab.

To serve the built UI from the backend (one process, as in production):
`cd frontend && npm run build`. The backend then serves `frontend/dist` at `/`.

### Tests

```bash
cd backend && uv run pytest -q          # 73 tests; stubbed model and email, no network
cd frontend && npx tsc -b --noEmit      # typecheck
cd frontend && npm run test:e2e         # Playwright; starts its own backend (fresh db, fake model, file email)
```

The backend tests cover state transitions, reply matching (token, headers, unmatched queue),
checking guards (quote verification, sub-points, injected instructions), the follow-up cap,
imports and re-import, LLM spend limits, and workspace access. The Playwright suite fails on
any uncaught page error or unexpected 5xx, and checks the app recovers from a server outage.

### LLM spend caps

`LLM_DAILY_TOKEN_BUDGET` (default 5M tokens per UTC day), `MAX_CHECKS_PER_REQUEST_PER_DAY`
(20), `MAX_IMPORT_ROWS` (300) and `CHAT_MESSAGES_PER_10_MIN` (20 per user) bound what one
provider, import or user can spend. Over a cap, the call fails visibly instead of running.
```

### Injecting replies without real email

`inject-eml` feeds a raw `.eml` through the same pipeline as a real inbound webhook:
persist → match → classify → extract → check.

```bash
# point a starter reply at request 1's thread (sets To and In-Reply-To), then process it
uv run rr inject-eml ../data/starter/part1/A_msa-and-insurance/reply-1_certificate-and-msa-question.eml --request 1 --process

uv run rr inject-eml FILE --request 1 --new-id    # inject the same file again as a new message
uv run rr inject-eml FILE --to 'req+TOKEN@in.example.com' --no-thread   # match by token only
uv run rr advance-clock --days 3                  # demo clock (development only)
uv run rr sweep                                   # queue a reminder/overdue/escalation pass
```

The server's own worker runs the jobs when it's running. `--process` is only for when it isn't.
The same injector is in the UI under **Inbox → Development: inject a raw .eml**.

---

## Demo script

For the recording, with real email and the expected result of every step, see
[`DEMO_SCRIPT.md`](DEMO_SCRIPT.md). The short version below uses the injector.

Start with `LLM_PROVIDER=anthropic` (or `openai`) for real checking. With `fake`, checklists come back empty
and verdicts stay "not met"; that mode is for UI work and tests.

**Part 1: MSA and insurance certificate**
1. On **Requests**, type: *"Get the signed 2025 Amended and Restated MSA and the current
   certificate of insurance from Jordan Lee (jordan@example.com) at Acme Logistics LLC by
   Oct 17."* The agent proposes a checklist: the certificate (current policy period) and the
   MSA (signed by both named parties). Edit it if needed, then **Confirm checklist**.
2. Review the drafted email: from "Sam Rivera via RequestRunner", Reply-To `req+<token>@…`,
   with an upload link. Then **Approve and send**.
3. Inject `part1/A_msa-and-insurance/reply-1_certificate-and-msa-question.eml` for that
   request. The certificate is **met**, with a verified quote and page. The provider's
   question about which MSA version is answered from the confirmed scope, and one follow-up
   goes out after the debounce window. The **Email** tab shows it threaded under the reply.
4. Reply with the unsigned MSA (`acme-msa-2025_unsigned.pdf`): **not met** (blank signature
   lines). Then reply with `acme-msa-2025_signed.pdf`: **met** with a *visual* citation. The
   request completes and the handback lists every item with its evidence.

**Part 1: bank statements, closed by the provider.** Ask for Acme's Q3 statements for
account ending 4410. Inject `part1/B_bank-statements/reply_partial-thats-all.eml`. July and
August are met, September is not, and the provider said "that's all I have", so the request
is handed back as *closed by provider* with the gap listed.

**Part 2: request list**
1. **Imports → Import a request list** with `data/starter/requests.csv`. Review shows:
   R-08 merged into R-07 (identical), R-25 held back as too vague, R-28 past due, R-27 no
   backup, R-18 shared by two owners, and R-06/R-12 depending on R-05/R-11.
2. Fix R-28's due date or leave it as is, then **Apply import**. You get one draft per
   person (8 emails for 29 items). **Send all**.
3. Open an email's upload link (`/u/<token>`, in the email text or in `var/sent-mail`) to see
   the provider's page. Upload `data/starter/part2/R-01/*.pdf` against R-01.
4. Inject `part2/combined/hannah_R-01_R-02_R-03.eml` into any of Hannah's requests. One
   reply is split across three items. Inject `part2/R-17/reply_dodge.eml` for R-17: the
   evasive answer is **not met**, sub-point by sub-point.
5. Use the demo clock (top right) to jump a few days: a pre-due reminder, then overdue
   notices, then escalation to the backup owner two business days later. R-27 has no backup,
   so only the requester is told. After three automatic contacts an item is handed back.
   The **Dashboard** shows who's behind and by how many days.
6. Re-import the same CSV: every row is *unchanged* and nothing is sent. Change a due date
   and some instructions, then re-import: the changed rows are listed, and one consolidated
   change notice goes to that provider. A row deleted from the CSV is flagged, not cancelled.

---

## Email setup

Outbound mail goes out as `"<Requester> via RequestRunner" <requests@mail.<domain>>`, with
`Reply-To: req+<opaque-token>@in.<domain>`. Replies come back through the provider's inbound
webhook.

**Gmail (free, no domain, works on a laptop)**
1. Turn on 2-step verification for the Google account, then create an app password:
   Google Account → Security → App passwords (myaccount.google.com/apppasswords).
2. In `.env`: `EMAIL_PROVIDER=gmail`, `GMAIL_ADDRESS=you@gmail.com`, `GMAIL_APP_PASSWORD=...`.
3. `uv run rr gmail-check` logs in to send and read without sending anything. Then restart the server.

Mail goes out from your Gmail as "<Requester> via RequestRunner", with
`Reply-To: you+req+<token>@gmail.com`. Gmail delivers those replies to your inbox; the
server checks it every minute (`GMAIL_POLL_SECONDS`) and only picks up messages sent to a
`+req+` address. The inbox is opened read-only: nothing is marked read, moved or deleted.
`uv run rr gmail-poll` checks right away. Limits: Gmail allows about 500 emails a day,
replies show up within a minute, and replies Gmail files as spam are not seen.

Upload links in the emails point at `APP_BASE_URL`. For providers on other computers, give
the app a public address, e.g. a free Cloudflare quick tunnel:
`cloudflared tunnel --url http://localhost:8000` (serve the built UI from the backend), then
set `APP_BASE_URL` to the `https://….trycloudflare.com` address it prints and restart.
Email replies with attachments work without this.

**Postmark (custom domain)**
1. Verify a sending domain `mail.<domain>` (DKIM, Return-Path CNAME) and add SPF and DMARC.
2. Add an MX record for `in.<domain>` pointing to `inbound.postmarkapp.com`, and set it as
   the server's inbound domain.
3. Inbound webhook URL: `https://user:password@<app>/webhooks/postmark/inbound` with
   "Include raw email content" on. Set `EMAIL_INBOUND_BASIC_AUTH=user:password`.
4. `EMAIL_PROVIDER=postmark`, `POSTMARK_SERVER_TOKEN`, `EMAIL_FROM_ADDRESS`, `EMAIL_INBOUND_DOMAIN`.

**SendGrid (fallback):** authenticate the domain, point the `in.<domain>` MX at
`mx.sendgrid.net`, and add an Inbound Parse host with **"POST the raw, full MIME message"**
to `https://user:password@<app>/webhooks/sendgrid/inbound`.
Then set `EMAIL_PROVIDER=sendgrid` and `SENDGRID_API_KEY`.

Before trusting the live loop, check four things: delivery to real inboxes, inbound
attachments, plus-address routing, and that a webhook without the password gets a 401.

**Not built: sending from the requester's own Gmail or Microsoft 365 mailbox (OAuth).**
"Via" sending from one verified domain needs no per-user OAuth consent, security review or
token storage. It keeps replies on infrastructure we control, and it makes reply matching
by token reliable. The cost is that mail comes from the app's address rather than the
requester's own.

---

## Deployment (Fly.io)

```bash
fly launch --no-deploy --copy-config        # uses fly.toml and the Dockerfile
fly volumes create rr_data --size 1         # SQLite + files live on /data
fly secrets set SESSION_SECRET=$(openssl rand -hex 32) APP_BASE_URL=https://<app>.fly.dev \
  ANTHROPIC_API_KEY=... GMAIL_ADDRESS=you@gmail.com GMAIL_APP_PASSWORD=... \
  SEED_USERS="Your Name|you@example.com|<password>"
fly deploy
```

With Postmark instead of Gmail, set `EMAIL_PROVIDER=postmark` and the secrets
`POSTMARK_SERVER_TOKEN`, `EMAIL_INBOUND_BASIC_AUTH=user:pass`, `EMAIL_FROM_ADDRESS` and
`EMAIL_INBOUND_DOMAIN` (see Email setup).

One machine, always on: SQLite plus the in-process job worker that sends reminders.
In production (`APP_ENV=production`) the app **refuses to start** in these cases:
- the session secret is the default or short;
- `APP_BASE_URL` isn't https;
- inbound webhooks have no password;
- the email provider or LLM credentials are missing.

The demo accounts are never seeded unless `SEED_USERS` is set. The user switcher, demo clock
and inject routes return 404, and session cookies are `Secure`.

---

## Architecture

```
backend/app
  api/          FastAPI routes (requester API, upload hub, webhooks), JSON shapes, SSE
  workflow/     the state machine and everything that moves a request
    scoping       comment → proposed checklist → confirm → draft → send
    inbound       persist → match → classify → assign evidence → questions → check
    checking      model verdicts → code guards → decide the next action
    evidence      file storage, rendering for the model, citation verification
    followups     per-provider cycles: follow-ups, reminders, overdue, change notices, escalation
    imports       Part 2 CSV review / apply / re-import
    outbox        durable outbound queue with idempotency keys and counter reservation
    jobs          durable job queue + in-process worker (restart-safe)
    hub           upload-link tokens
  extraction/   PDF text per page + page renders, sheets with cell refs, DOCX, images/HEIC,
                magic-byte checks, macro/zip-bomb rejection, injection heuristics
  email/        MIME/Postmark parsing, quoted-text stripping, auto-reply detection, senders
  llm/          provider-neutral interface, Anthropic implementation, deterministic fake
frontend/src    React + Vite + Tailwind; live updates over Server-Sent Events
```

**The model proposes; code decides.** The model returns validated structured output only:
checklist drafts, reply classifications, per-item and per-sub-point verdicts with
citations, and suggested answers to provider questions. It has no tools and cannot change
state. Code owns state transitions, confirmation and versioning, sending, counters,
scheduling, escalation and completion. Invalid model output is retried a bounded number of
times, then becomes a visible processing error.

**Request states:** scoping → waiting for requester → ready to send → waiting for provider ⇄
checking ⇄ needs more → *complete* | *closed by provider* | *accepted* | *cancelled*, plus
*handed back* (follow-up limit reached; the requester decides). Every transition is
audited.

**Durability:** inbound mail is stored before it's processed, and deduplicated by provider
message id or Message-ID. Outbound mail is written to an outbox in the same transaction as
the decision to send it, under an idempotency key. If a send result is unclear (timeout, or
a crash mid-send), the message is marked *uncertain* and never resent automatically; the
requester can resend it. Jobs live in the database and survive restarts.

### How replies are matched

1. The opaque token in the Reply-To address (`req+<token>@…`).
2. `In-Reply-To` / `References` against stored outbound Message-IDs.
3. The sender's address only ever **suggests** a match in the unmatched queue.

If the token and the headers point at different threads, or nothing matches, the message
waits in **Inbox** for the requester to assign. A reply to a closed request is stored and
the requester is told, but nothing is sent automatically. Auto-replies and bounces are
logged and ignored. Mail from someone who isn't a listed owner is accepted but flagged.

### How checking works

Each checklist item has a type (document or answer), a description, structured criteria
(period, entity, format, required elements, signature, currency), and, for answers, required
sub-points with explicit conditions. Confirmed versions are immutable; any change makes a
new version that the requester confirms.

The model sees files as extracted text with locations: PDF pages, sheet and cell ranges,
DOCX paragraphs and tables, email bodies. It also gets page images where a page has little
text or a signature matters. It must cite a location for every verdict other than not met.
Code then checks each citation:

- A **text quote** must appear at the cited location (whitespace-normalised). If the quote
  isn't there, the citation is unsupported and the verdict is downgraded.
- A **visual citation** is labelled visual and keeps the page image for the requester to
  inspect. It never passes as a verified quote, and a "met" resting only on an ambiguous
  visual becomes *partly met* with a review flag.
- An **answer** item is met only if every applicable sub-point has its own supporting quote.
  A generic "in line with our policy" doesn't count (the R-17 dodge).
- Code only **downgrades** verdicts. Completion is computed from the confirmed items, and a
  requester override needs a reason and is audited.

Verdicts: `met`, `partly_met`, `not_met`, `unreadable`. The check's own status (`pending`,
`checking`, `checked`, `error`) is tracked separately.

**Where it can fail:** handwriting and low-quality scans are judged visually, so they're
less reliable and are flagged for review. Signatures are checked for presence, never for
authenticity. A quote that appears verbatim but is taken out of context will verify.
Spreadsheet checks see cell values, not formatting.

### Part 2 specifics

- **One work queue per provider** (workspace + email): a single upload page and batched
  reminders across all their items. Each outreach batch is its own email conversation with
  its own reply token, so replies stay attributable.
- **Two owners (R-18):** one shared item that either owner can satisfy by default. At review
  it can be switched to "both must respond", which waits for each owner's own submission.
  Neither owner sees the other's files on their upload page.
- **Dependencies (R-06→R-05, R-12→R-11):** sent with the context, checked against the
  prerequisite's evidence, and completed only after the prerequisite is. They're rechecked
  when the prerequisite's evidence changes.
- **Identity and re-import:** `request_id` is scoped to the list. Exact duplicates (every
  meaningful field equal) merge, and the merged ids are kept as aliases. Near duplicates are
  only suggested. The same id with different content is a blocking error. On re-import,
  unchanged rows do nothing. Changed due dates or instructions update in place, and one
  consolidated change notice goes to each provider. Review edits survive a re-import of the
  original file.

### Follow-up limits (assumption)

- Each item has one automatic-contact counter, capped at 3.
- The initial email doesn't count.
- Reminders, deficiency follow-ups, overdue notices and change notices that name the item
  each count once per message. A batched message counts once for each item it names.
- Retries and duplicate processing never count twice: the counter is reserved in the same
  transaction as the outbox row.
- At 3, the item is handed back instead of contacting the provider again.
- **Escalation to the backup owner** is a separate message type, sent at most once per
  escalation cycle (a new due date starts a new cycle). It always goes to the backup, never
  the provider, so it can't be used to get round the limit.
- Default cadence: a reminder 2 days before the due date, a follow-up about 2 minutes after
  an incomplete reply (debounced), an overdue notice the day after the due date, and
  escalation 2 business days later. Times use the workspace timezone; business days are
  weekdays.

---

## Security

- **Provider content is evidence, never instructions.** It reaches the model only inside
  delimited data blocks. Calls that read it can't change anything. Instruction-like text is
  detected in code and shown to the requester. A quote of such an instruction never counts
  as evidence, but the rest of the file still does.
- **Upload links:** random 256-bit tokens, stored hashed, scoped to one provider in one
  workspace, and rate-limited. Each item stays open for the later of its due date + 7 days
  and issuance + 14 days. Links are revoked when nothing is left open, and can be revoked
  manually. Upload tokens and email reply tokens are separate credentials.
- **Files:** allowlist (PDF, XLSX/XLS/CSV, PNG/JPG/HEIC, DOCX, EML), checked by magic bytes
  rather than extension. Macro-enabled Office files are rejected, and archive expansion is
  bounded. The cap is 25 MB per file, enforced while streaming. Files are stored outside the
  web root, content-addressed but always accessed through workspace-scoped records.
  Downloads are `Content-Disposition: attachment`. Page previews are our own PNG renders.
- **Requesters:** bcrypt passwords and signed session cookies (`Secure` in production).
  Workspace authorization applies on every route, download and SSE stream. Another
  workspace's objects return 404.
- Provider email text is rendered as plain text, never as HTML.

## Limitations and before real customers

- SQLite and one process: fine for a demo, not for horizontal scale. Next steps would be
  Postgres, a separate worker, and S3 behind the existing storage interface.
- Requester auth is seeded accounts. Production would need SSO or magic links, password
  reset, and per-workspace admin.
- There's no provider identity beyond the email address and link. Anyone forwarded a link
  can upload to it until it expires.
- Check quality depends on the model. The tests pin the guard rails (quote verification,
  sub-points, injection), not the model's judgement. A labelled eval set built from
  `manifest.csv` is the next step.
- Reminders are plain-text templates in English, and there's no unsubscribe or opt-out
  handling for providers.
- The provider upload page refreshes by polling after a submission rather than over SSE,
  because the event stream requires a requester session.

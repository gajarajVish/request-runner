# RequestRunner

An agent that collects documents and answers from people for you. It agrees a checklist with
you, emails the provider, checks every reply and upload against that checklist with cited
evidence, follows up on what's missing, and hands the finished package back.

- **Single request:** describe what you need → confirm the checklist → approve the email →
  replies are checked → follow-up or handback.
- **Request lists:** import a CSV → review → one email per provider → reminders, overdue
  notices, escalation, and a "who's behind" dashboard.

## Quick start

**Hosted:** https://request-runner.fly.dev. Create an account with the invite code and it's ready
to use with the real model and real email.

Step-by-step setup and a guided first run are in [docs/SETUP.md](docs/SETUP.md).

Requires Python 3.12 + [uv](https://docs.astral.sh/uv/) and Node 20.

```bash
cp .env.example .env     # add ANTHROPIC_API_KEY, or set LLM_PROVIDER=fake to run offline
cd backend && uv sync && uv run rr seed && uv run uvicorn app.main:app --reload --port 8000
cd frontend && npm install && npm run dev     # second terminal → http://localhost:5173
```

Sign in as `sam@example.com` / `requester`. Outgoing email is written to `var/sent-mail/`
instead of being sent.

## Tests

```bash
cd backend && uv run pytest -q
cd frontend && npm run typecheck && npm run test:e2e
```

## Architecture and states

FastAPI + SQLite with a durable in-process job worker; React + Vite + Tailwind frontend; one
Fly.io machine. **The model proposes; code decides.** The model only returns validated
structured output (checklists, classifications, verdicts with citations). It has no tools.
Code owns every state change, send, counter and escalation.

```
scoping → waiting for requester → ready to send → waiting for provider ⇄ checking ⇄ needs more
  → complete | closed by provider | accepted | cancelled | handed back (follow-up cap hit)
```

Every transition is audited. Inbound mail is stored before it's processed and deduplicated.
Outbound mail goes through an idempotent outbox, and an unclear send is never retried
automatically.

## Matching replies to requests

1. The opaque token in the Reply-To address (`req+<token>@…`).
2. `In-Reply-To` / `References` against the Message-IDs we sent.
3. The sender address only *suggests* a match. Conflicts and unmatched mail wait in **Inbox**
   for the requester. Auto-replies and bounces are ignored.

## "On behalf of" choices

Mail is sent *via* the app (`"Sam Rivera via RequestRunner"`, Reply-To a per-request token
address), not from the requester's own Gmail or Microsoft 365 account. That means no per-user
OAuth or token storage, replies land on infrastructure we control, and matching is reliable.
The cost is that mail doesn't come from the requester's own address. Nothing goes out until
the requester confirms the checklist and approves the email. After that, follow-ups are
capped at 3 automatic contacts per item, then the item is handed back. Escalation goes only
to the backup owner.

## How checking works, and where it fails

Each item has structured criteria (period, entity, signature, required sub-points…). The
model sees extracted text with locations (PDF page, sheet cell, DOCX paragraph), plus page
images where needed, and must cite a location for every verdict. Code then **only
downgrades**:
- a text quote must actually appear at the cited location, otherwise the verdict drops;
- a visual citation (e.g. a signature) is labelled as visual and can't reach "met" on its own if it's ambiguous;
- an answer is met only if every required sub-point has its own quote.

**Fails on:** handwriting and poor scans (flagged for review), signature *authenticity*
(only presence is checked), quotes that are verbatim but taken out of context, and
spreadsheet formatting (only cell values are seen).

## Security

- **Provider content is data, never instructions:** it reaches the model only inside delimited data blocks, through
  calls that can't change state. Injection-like text is flagged to the requester and never
  counts as evidence.
- **Upload links:** random 256-bit tokens stored hashed, scoped to one provider, rate
  limited, auto-expiring and revocable. They are separate from reply tokens.
- **Attachments:** allowlist checked by magic bytes, macro files rejected, archive
  expansion bounded, 25 MB cap. Files are stored outside the web root and served as
  downloads only.
- Workspace authorization applies on every route. Production refuses to start with weak
  secrets, non-https URLs or an unauthenticated webhook.

## Before real customers

- Postgres, a separate worker, and S3 instead of SQLite on one machine.
- SSO or magic links, password reset and workspace admin instead of seeded accounts.
- Stronger provider identity: today anyone who's forwarded a link can upload.
- A labelled eval set for check quality (the tests pin the guard rails, not the model's
  judgement).
- Unsubscribe/opt-out handling and localized reminder templates.

## More

- [Setup and first run](docs/SETUP.md): install, seed, and try both parts without real email
- [Full guide](docs/GUIDE.md): demo script, email setup, deployment, and the long form of
  every section above
- [Design decisions](docs/DESIGN_DECISIONS.md)
- [Architecture overview (PDF)](docs/ARCHITECTURE.pdf): diagrams of the system and the request states
- [Demo script](docs/DEMO_SCRIPT.md): the recording walkthrough with real email, rehearsed on the real model
- [Evaluating the agent](docs/EVALS.md): how we'd measure that the model's judgements are good

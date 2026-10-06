# Build status (2026-10-07)

All milestones from the decisions plan are built. Setup for a new machine is in
[SETUP.md](SETUP.md); the README covers architecture, assumptions and limitations.

| Milestone | State |
|---|---|
| Foundation, Part 1 loop, evidence handling | done (backend/app) |
| Part 2 imports, provider batches, re-import, dashboard | done (`workflow/imports.py`, `/api/imports`, `/api/dashboard`) |
| Tests | 73 backend tests passing (2026-10-07): `cd backend && uv run pytest -q`; 18 Playwright e2e tests passing in `frontend/e2e` |
| Frontend | done (`frontend/`); axe-core WCAG 2.1 AA scan clean on all pages |
| Deployment | `Dockerfile` + `fly.toml`; image builds and enforces production checks |
| Real model + real email | rehearsed end to end on 2026-10-06 with Gmail and OpenAI (see [DEMO_SCRIPT.md](DEMO_SCRIPT.md)) |

## Fixed 2026-10-07

- `.env.example` had comments after empty values (`SEED_USERS=   # ...`), which the `.env`
  parser reads as the value. A fresh copy seeded an unusable account and wrote data to a
  directory named after the comment. Comments now sit on their own line, and a blank
  `DATA_DIR` or `SESSION_SECRET` falls back to the default.
- The first email's subject no longer repeats the organisation when the title already names it.
- The change notice no longer prints a doubled bullet.
- A reply from `x@d` now counts as coming from a provider listed as `x+tag@d` (same mailbox), so
  one Gmail inbox can play every provider without each reply being flagged as an unknown sender.
  Checked live: a self-addressed Gmail reply was matched by token and processed.
- R-13 re-run on the real model with the clock moved forward 7 days: **met**.

## Not done / needs external input

- A custom sending domain (SPF/DKIM/DMARC, inbound MX) and a Postmark account. Gmail works
  without one; see [GUIDE.md](GUIDE.md#email-setup).
- The actual Fly deploy (needs flyctl and an account).
- Known gaps: the hub refreshes by polling, not SSE; with "both must respond" nothing is sent
  automatically to the silent owner beyond normal reminders; no eval harness yet
  ([EVALS.md](EVALS.md) is the plan).

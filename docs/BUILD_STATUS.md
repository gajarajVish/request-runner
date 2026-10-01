# Build status (2026-10-01)

All milestones from the decisions plan are built. The README covers setup, the demo script,
email setup, deployment, architecture, assumptions and limitations.

| Milestone | State |
|---|---|
| Foundation, Part 1 loop, evidence handling | done (backend/app) |
| Part 2 imports, provider batches, re-import, dashboard | done (`workflow/imports.py`, `/api/imports`, `/api/dashboard`) |
| Tests (§15 list) | 52 passing: `cd backend && uv run pytest -q` |
| Frontend | done (`frontend/`), verified in headless Chromium against a live server |
| Deployment | `Dockerfile` + `fly.toml`; image builds and enforces production checks |

## Not done / needs external input

- Real email: domain, DNS (SPF/DKIM/DMARC, inbound MX) and the Postmark account. Until then use
  `EMAIL_PROVIDER=file` + `rr inject-eml`.
- The actual Fly deploy (needs flyctl + account), and an end-to-end run with the real model
  (`LLM_PROVIDER=anthropic`) through the README demo script.
- Known gaps (see README "Limitations"): the hub refreshes by polling, not SSE; with "both
  must respond" nothing is sent automatically to the silent owner beyond normal reminders.

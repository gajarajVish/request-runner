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

## Paused 2026-10-01 (evening): next steps

- Local demo instance runs with `LLM_PROVIDER=openai` (key in the git-ignored `.env`), user
  "Vishva Gajaraj" (vgajaraj@engineering.upenn.edu / requester). Run the demo at the fixtures'
  date: advance the demo clock 11 days first (fixtures are dated Oct 12, 2026).
- Last full real-model run matched manifest.csv except R-06 (model strict on "before it is
  saved"; tuning question) and, once, the bank-statement "that's all I have for now" not
  closing; the classify prompt was clarified but not re-verified.
- Not yet done: a clean rerun + screenshot gallery of the MVP for the user to direct UI changes.
  Driver scripts lived in the session scratchpad (demo.py, shots.py); rebuild from the README
  demo script if needed.

# Build status (2026-10-01)

All milestones from the decisions plan are built. The README covers setup, the demo script,
email setup, deployment, architecture, assumptions and limitations.

| Milestone | State |
|---|---|
| Foundation, Part 1 loop, evidence handling | done (backend/app) |
| Part 2 imports, provider batches, re-import, dashboard | done (`workflow/imports.py`, `/api/imports`, `/api/dashboard`) |
| Tests (§15 list) | 58 passing: `cd backend && uv run pytest -q` |
| Frontend | done (`frontend/`); enterprise restyle 2026-10-02 (tokens in `src/index.css`, primitives in `src/components/ui.tsx`), axe-core WCAG 2.1 AA scan clean on all pages |
| Deployment | `Dockerfile` + `fly.toml`; image builds and enforces production checks |

## Not done / needs external input

- Real email: domain, DNS (SPF/DKIM/DMARC, inbound MX) and the Postmark account. Until then use
  `EMAIL_PROVIDER=file` + `rr inject-eml`.
- The actual Fly deploy (needs flyctl + account), and an end-to-end run with the real model
  (`LLM_PROVIDER=anthropic`) through the README demo script.
- Known gaps (see README "Limitations"): the hub refreshes by polling, not SSE; with "both
  must respond" nothing is sent automatically to the silent owner beyond normal reminders.

## Paused 2026-10-02: next steps

- Local demo instance uses `LLM_PROVIDER=openai` (key in the git-ignored `.env`), user
  "Vishva Gajaraj" (vgajaraj@engineering.upenn.edu / requester). Run the demo at the fixtures'
  date: advance the demo clock 11 days first (fixtures are dated Oct 12, 2026).
- 2026-10-02 clean rerun: all of Part 1 matched manifest.csv, including the bank-statement
  "that's all I have" close. Part 2 import review matched the README exactly. R-01 uploads met.
  The run stopped at Hannah's combined reply / R-17 when the OpenAI account ran out of credits.
- Fixed from that run: a multi-line quote that skips a line no longer fails verification (it
  wrongly downgraded R-01's statements); evidence ids (E17) in `missing` are replaced with the
  file name / "your message" before reaching the provider; a model filling `criteria.format`
  with "json_object" no longer reaches the request email as "Format: json_object".
- Still to do once there are credits (or an ANTHROPIC_API_KEY): finish Part 2 (combined reply,
  R-17 dodge follow-up text, clock-driven reminders/escalation), then a screenshot gallery of the
  MVP for UI direction. Scoping sometimes makes Part 1 B's three months one item (verdict
  "partly met") rather than three; consider nudging scoping toward one item per period.

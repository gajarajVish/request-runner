# Build status (paused 2026-09-30)

Work follows the decisions and milestone plan the user supplied in reply to
`docs/DESIGN_DECISIONS.md`. Those decisions are settled; treat them as the spec.

## Done (backend, `backend/`)

| Area | Files | Notes |
|---|---|---|
| Config, DB, clock, storage, audit | `app/config.py`, `db.py`, `clock.py`, `storage.py`, `audit.py` | SQLite (WAL) + SQLAlchemy; demo clock = persisted offset, idempotent per key, disabled in production; content-addressed blobs; `Event` table is the cross-process SSE feed |
| Schema | `app/models.py`, `migrations/versions/e8cbd521caa4_initial_schema.py` | **The migration is stale**: `ProviderQuestion.delivered_at` was added afterwards. Nothing is deployed yet, so delete the migration and regenerate it: `DATA_DIR=<tmp> uv run alembic revision --autogenerate -m "initial schema"` |
| Extraction | `app/extraction/validate.py`, `core.py` | Magic-byte detection, macro/zip-bomb rejection, PDF text per page (pypdfium2) + page renders for low-text and signature pages, sheets with cell coordinates, DOCX, images/HEIC, injection heuristics. Verified on all 55 starter files |
| Email | `app/email/mime.py`, `adapters.py` | Raw/Postmark parsing, quoted-text stripping, auto-reply detection; File/Memory/Postmark/SendGrid senders with sent/retry/failed/uncertain outcomes |
| LLM | `app/llm/schemas.py`, `prompts.py`, `base.py`, `anthropic_llm.py`, `fake.py` | `LLMCall` → validated pydantic output; Anthropic uses `messages.stream(output_format=...)`, adaptive thinking on the strong model, bounded retries, server-side fallbacks (auto-disabled if rejected). Defaults: `claude-opus-5` (strong), `claude-haiku-4-5` (fast) |
| Workflow | `app/workflow/*` | `states`, `jobs` (durable queue + worker), `outbox` (idempotency + counter reservation + uncertain handling), `hub` (hashed 256-bit upload tokens, per-item expiry), `emails` (templates), `scoping`, `evidence` (store/render/citation verification), `inbound` (persist → match token/headers → classify → assign → questions → check), `checking` (guards + `decide`), `followups` (per-provider cycles, reminders, overdue, change notices, escalation), `handback`, `actions`, `chat` |
| API | `app/api/deps.py`, `serialize.py`, `routes.py`, `public.py`, `app/main.py` | Auth (bcrypt + session cookie; dev user switcher), requests CRUD/actions, files, inbound queue, audit, SSE, dev clock/inject, upload hub, Postmark/SendGrid webhooks (basic auth) |
| CLI | `app/cli.py` (`uv run rr ...`) | migrate, seed, inject-eml (retargets starter .eml To/In-Reply-To), run-jobs, advance-clock, sweep |
| Tests | `tests/conftest.py`, `helpers.py`, `test_part1_loop.py` | 4 Part 1 loop tests passed before the last edits (see below) |

## State at pause

- The last test run failed only because `tests/helpers.py` imported `scoping.latest_proposed`
  after ruff removed that import. The helper now imports it from `app.workflow.common`.
  **Tests have not been re-run since.** Run first: `cd backend && uv run pytest -q`.
- The server hasn't been smoke-tested yet (`uv run uvicorn app.main:app`). macOS has no
  `timeout` command, so background the server and `pkill` it afterwards.
- Commits: `1336f52` (backend foundation) plus a WIP commit with everything up to this pause.

## Remaining (in milestone order)

1. Re-run the tests and smoke-test the API. Regenerate the initial migration.
2. **Part 2 imports**: `app/workflow/imports.py`, which `registry.py` already tries to import.
   It needs:
   - CSV parse and validation;
   - row content hash, exact-duplicate merge (aliases), near-duplicate suggestions, conflicting-ID errors;
   - `R-xx` dependency detection, two owners (`;`) → shared ownership (`any`), and flags for vague rows (R-25), past-due rows (R-28) and rows with no backup owner (R-27);
   - LLM row scoping cached through `ScopeCache`;
   - review → apply → per-provider draft batch emails (`emails.initial_batch`) → "send all";
   - re-import diff: unchanged does nothing; a due-date change updates the date, calls `actions.reset_due_tracking` and sends one consolidated change notice (`followups.queue_change_notices`); a scope change creates a new confirmed version and a recheck; removed rows get a flag.
   - API routes for upload, review, row edits, apply and send, plus a dashboard endpoint (providers behind, items, days overdue; filters for provider, status and overdue).
3. More tests, as listed in the decisions §15: matching conflicts and unmatched mail, duplicate webhooks, uncertain send, quote verification, prompt injection, vague answers (R-17 dodge), unreadable files, shared ownership and dependencies, import idempotency, follow-up limit, batching and debounce, escalation, token expiry and revocation, cross-workspace access, repeated clock advances.
4. **Frontend** (`frontend/`, React + Vite + Tailwind):
   - login and user switcher;
   - requests list and a new-request comment box;
   - request page: thread with checklist and draft cards, live checklist with citations and page images, files, emails with headers, audit log, actions;
   - imports review, dashboard, unmatched inbox, demo clock panel;
   - public upload hub at `/u/:token`, with live updates over SSE (`/api/events`).
5. Fly.io config (volume for `var/`), production auth checks, and the README (setup, env, email provider setup, architecture, assumptions, limitations, demo script).

## Key design notes to keep

- A Part 2 "item" = a `Request`. Owners, due date, backup, dependencies and the automatic-contact counter live on `Request`. `ChecklistItem`s are the requirements inside it.
- Every model-claimed `met` needs a verified quote or a labeled visual citation. Answer items need every applicable sub-point met. Code only ever downgrades verdicts, never upgrades them.
- Closing by email requires the closing quote to appear in the sender's own new text, and the sender must be a listed owner.
- Escalation emails reply into the provider's thread token. Replies from the backup are accepted but flagged as "unknown sender".
- Hidden-pack files from the take-home (`generate.py`, the internal README) were deliberately left out of the repo.

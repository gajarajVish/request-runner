# Setting up and using RequestRunner

## Use the hosted app (no setup)

The app is running at **https://request-runner.fly.dev**, on the real model and real email.

1. Click **Create an account** on the sign-in page. Use an email you can read: handbacks and
   overdue notices are sent there. You'll need the invite code you were given.
2. Your account gets its own private workspace. Nobody else sees your requests.
3. Start a request (**Requests → New request**). To play the provider yourself, name an
   address you can read as the provider. Replies with attachments are picked up within a
   minute, and the upload link in the email works from any device.

Mail goes out from the app's Gmail as "<your name> via RequestRunner". The demo clock isn't
available on the hosted app, because it runs on real time.

## Run it locally

Everything you need to get from a fresh clone to a working app, then try both halves of the
product: a single request, and a request list. Allow about 10 minutes.

## 1. Install

You need **Python 3.12** with [uv](https://docs.astral.sh/uv/getting-started/installation/)
and **Node 20**.

```bash
git clone https://github.com/gajarajVish/request-runner.git
cd request-runner
cp .env.example .env
```

## 2. Choose a mode in `.env`

Pick one. You can change it later and restart the server.

| Mode | Set in `.env` | What you get |
|---|---|---|
| **Offline** (quickest) | `LLM_PROVIDER=fake` | Every screen and the whole flow work, with no API key and no network. Checklists and verdicts come from a deterministic stub, so they're simple. |
| **Real model** (recommended) | `LLM_PROVIDER=anthropic` and `ANTHROPIC_API_KEY=...`, or `LLM_PROVIDER=openai` and `OPENAI_API_KEY=...` | The real scoping questions, cited verdicts and follow-up text. |

Email stays in **file mode** by default (`EMAIL_PROVIDER=file`). Nothing is sent: every
outgoing message is written to `var/sent-mail/` and shown on the request's **Email** tab,
and you play the provider by injecting replies (step 5). To use real email instead, see
[Email setup in the guide](GUIDE.md#email-setup). Gmail works with only an app password.

## 3. Seed and run

```bash
# terminal 1: API + background worker
cd backend
uv sync
uv run rr seed                     # creates the database, the workspace and two accounts
uv run uvicorn app.main:app --reload --port 8000

# terminal 2: web app
cd frontend
npm install
npm run dev                        # http://localhost:5173
```

Open **http://localhost:5173** and sign in as **`sam@example.com` / `requester`**. There's
also `alex@example.com` / `requester`, a second requester in the same workspace.

To use your own accounts, so that requester emails reach an inbox you can read, set
`SEED_USERS="Your Name|you@example.com|a-password"` before running `rr seed`.

**Start over at any time:** stop the server, delete the `var/` folder, and run
`uv run rr seed` again.

## 4. Try a single request (Part 1)

1. **Requests → New request**, and type:
   > Get the signed MSA and the latest insurance certificate from our vendor Jordan Lee (jordan@example.com).
2. The agent drafts a checklist and asks about anything ambiguous (with a real model:
   which legal entity, what "latest" means, the due date). Answer in the same thread, e.g.
   > The vendor is Acme Logistics LLC. Latest means the certificate currently in force. The MSA is the 2025 Amended and Restated MSA, signed by both Acme Logistics LLC and us (Alder & Finch Co.). Due Oct 17.
3. **Confirm checklist**, review the email, then **Approve and send**. With file email it
   appears on the request's **Email** tab.
4. Play the provider by injecting the sample reply (certificate attached, plus a question
   about the MSA version):
   ```bash
   cd backend
   uv run rr inject-eml ../data/starter/part1/A_msa-and-insurance/reply-1_certificate-and-msa-question.eml --request 1
   ```
   `--request 1` threads the reply onto request 1. Use the id shown in the request's URL.
   You can also do this in the UI: **Inbox → Development: inject a raw .eml**.
5. Watch the request: the certificate is checked with page citations, the provider's
   question is answered from the confirmed checklist, and a follow-up for the MSA goes out
   about 2 minutes later.
6. Open the **upload link** from the sent email (Email tab) and upload
   `data/starter/part1/A_msa-and-insurance/acme-msa-2025_unsigned.pdf` against the MSA. It
   comes back **not met** (blank signature lines). Upload `acme-msa-2025_signed.pdf` and the
   request turns **Complete**, and the handback is written to `var/sent-mail/`.

The sample files are dated Oct 12, 2026. If today is before that, move the demo clock
forward first (step 6), or a date check can come back *partly met*. That's correct
behaviour, since evidence can't be dated in the future.

## 5. Try a request list (Part 2)

1. **Imports → Import a request list**, and choose `data/starter/requests.csv`.
2. The review flags the interesting rows before anything is sent: R-08 merged into R-07,
   R-25 held back as too vague, R-18 shared by two owners, R-06 and R-12 depending on other
   rows, R-27 with no backup owner, and R-28 already past due.
3. **Apply import**, then **Send all**. Each provider gets one email and one upload page for
   all their items.
4. Reply as a provider. The simplest way is that provider's upload page (the link is in
   their sent email, on the request's **Email** tab). To reply by email instead, inject a
   reply addressed to the Reply-To shown on that provider's email:
   ```bash
   uv run rr inject-eml ../data/starter/part2/R-14/reply.eml \
     --to 'req+<token>@in.example.com' --from mei@example.com --no-thread
   ```
   `data/starter/part2/R-xx/` has a sample file or reply for every row, and
   `data/starter/manifest.csv` lists the verdict each one should get.
5. **Dashboard** shows who's behind. Turn on **Overdue only** after the next step.

## 6. Move time forward (reminders, overdue, escalation)

Development mode has a demo clock. Use the clock control at the top right of the app, or:

```bash
uv run rr advance-clock --days 3
uv run rr sweep                    # run the reminder/overdue/escalation pass now
```

Reminders go out 2 days before the due date, overdue notices the day after, and escalation
to the backup owner 2 business days after that, with a notice to the requester. Each item
gets at most 3 automatic contacts, then it is handed back to the requester.

## 7. Run the tests

```bash
cd backend && uv run pytest -q             # 75 tests, model and email stubbed, no network
cd frontend && npm run typecheck
cd frontend && npm run test:e2e            # Playwright; starts its own server on other ports
```

The first e2e run may ask you to install browsers: `npx playwright install chromium`.

## Troubleshooting

| Problem | Fix |
|---|---|
| "wrong email or password" | Run `uv run rr seed`, and check `SEED_USERS` in `.env` is empty or in `Name|email|password` form. |
| A model call fails or "token budget" errors | Check the API key and `LLM_PROVIDER`. Re-run the check from the request's menu: **Re-check what was received**. |
| An injected reply shows up in **Inbox** instead of on the request | It couldn't be matched. Pass `--request <id>`, or assign it from the Inbox. |
| Upload links point to the wrong port | Set `APP_BASE_URL` to the address you open the app on, and restart. |
| Port 8000 already in use | Stop the other process, or run on another port and set `APP_BASE_URL` to match. |

More detail on every part is in the [full guide](GUIDE.md), and the design reasoning is in
[DESIGN_DECISIONS.md](DESIGN_DECISIONS.md).

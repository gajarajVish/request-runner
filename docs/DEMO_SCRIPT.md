# Demo script

A recording-ready walkthrough of the brief's demo script, playing both sides with real email.
Every step below was rehearsed end to end on 2026-10-06 against the real model (OpenAI,
`gpt-5.5` / `gpt-5.4-mini`), with the email layer writing files instead of sending. The
"you should see" lines are what that run produced.

You need three addresses you control:

| Role | Example | What it's for |
|---|---|---|
| App mailbox | `you@gmail.com` | Sends as "Sam Rivera via RequestRunner" and receives replies (`EMAIL_PROVIDER=gmail`) |
| Requester (Sam) | `sam.yourname@gmail.com` | Receives handbacks, overdue notices and the optional Cc |
| Provider | `provider@gmail.com` | Plays Jordan in Part 1, and every CSV owner in Part 2 (via plus addresses) |

---

## Before you record (about 10 minutes)

1. **Fresh data, real email, real model.** In `.env`:

   ```bash
   EMAIL_PROVIDER=gmail
   GMAIL_ADDRESS=you@gmail.com
   GMAIL_APP_PASSWORD=...            # Google Account → Security → App passwords
   LLM_PROVIDER=openai               # or anthropic
   SEED_USERS="Sam Rivera|sam.yourname@gmail.com|<password>"
   DATA_DIR=./var/demo               # a clean database just for the recording
   ```

   Then `cd backend && uv run rr gmail-check && uv run rr seed`.

2. **Run the built UI from one process**, so upload links work:
   `cd frontend && npm run build`, then `cd backend && uv run uvicorn app.main:app --port 8000`.
   If the provider inbox is on another machine, run `cloudflared tunnel --url http://localhost:8000`
   and set `APP_BASE_URL` to the address it prints.

3. **Move the demo clock forward 7 days** (clock control, top right, or
   `uv run rr advance-clock --days 7`). The sample files are dated Oct 12, 2026. Without this,
   the R-13 screenshot's "pulled on 10/12/2026" is in the future and the item comes back
   *partly met*, which is correct but not the beat you want.

4. **Make a Part 2 CSV with addresses you control.** Gmail delivers `provider+hannah@gmail.com`
   to `provider@gmail.com`, so one inbox can play all eight owners:

   ```bash
   sed -E 's/([a-z]+)@example\.com/provider+\1@gmail.com/g' data/starter/requests.csv > /tmp/requests-demo.csv
   ```

5. **Open four windows:** the app (signed in as Sam), the provider inbox, the app mailbox, and
   the requester inbox. Replies are picked up within a minute; `uv run rr gmail-poll` fetches now.

6. **Waiting time.** Scoping takes about 10–20 seconds and each check about 15–30 seconds. To
   fit five minutes, record in segments and cut the waits, or speed them up in the edit.

---

## Part 1: one request (about 2½ minutes)

### 1. The requester asks

Type in **Requests → New request**:

> Get the signed MSA and the latest insurance certificate from our vendor Jordan Lee (provider@gmail.com).

**You should see:** the agent drafts two items and asks which legal entity Jordan represents,
what "latest" means for the certificate, and the deadline. The checklist isn't ready yet.

### 2. Answer, confirm, send

Reply in the same thread:

> The vendor is Acme Logistics LLC. Latest means the certificate currently in force. The MSA is the 2025 Amended and Restated MSA, signed by both Acme Logistics LLC and us (Alder & Finch Co.). Due Oct 17.

**You should see:** a revised checklist. The MSA is signed by both named parties, and the
certificate's policy period must include today. Click **Confirm checklist**, review the
draft, then **Approve and send**.

**In the provider inbox,** open the email and use **Show original** to show:
- `From: "Sam Rivera via RequestRunner" <you@gmail.com>`, with SPF and DKIM **PASS** (Google signs
  Gmail-sent mail; the rehearsal used file email, so confirm this on your first live send)
- `Reply-To: you+req+<token>@gmail.com`, unique to this request
- the body says who asked, lists both items with the due date, and gives the upload link
- the footer: "RequestRunner is collecting this for Sam Rivera…"

> Rehearsal: the subject came out as "Acme Logistics LLC MSA and Insurance Certificate Request
> for Acme Logistics LLC: request from Sam Rivera". The vendor name appears twice, which is cosmetic.

### 3. Provider: the certificate plus a question

From the provider inbox, **reply** to the email (so it threads). Attach
`data/starter/part1/A_msa-and-insurance/acme-logistics-llc_certificate-of-insurance_2026-2027.pdf` and write:

> The current insurance certificate is attached. On the MSA: which version do you need? We have the 2023 original and the 2025 amended and restated agreement.

**You should see:**
- the certificate is **met**, citing `p.1` with verified quotes ("Insured Acme Logistics LLC",
  "Policy period 03/01/2026 to 03/01/2027")
- the question is answered **from the confirmed scope**: "Please provide the 2025 Amended and
  Restated Master Services Agreement, signed by both…"
- a follow-up still listing the MSA. The answer and the follow-up arrive as two emails in the same thread.

To show the other branch, leave the version out of step 2. The agent then asks Sam
instead of answering Jordan.

### 4. Provider: the unsigned MSA

Open the **upload link** from the email and upload `acme-msa-2025_unsigned.pdf` against the MSA
item, or reply with it attached.

**You should see:** the MSA is **not met**: "page 1 shows blank signature lines for both
parties". Within about 2 minutes a follow-up arrives in the same thread:

> Signed MSA: acme-msa-2025_unsigned.pdf has blank signature lines for both Alder & Finch Co. and Acme Logistics LLC; please provide the 2025 Amended and Restated Master Services Agreement signed by both parties.

### 5. Provider: the signed copy

Upload `acme-msa-2025_signed.pdf` on the upload page.

**You should see:** the MSA is **met**, with a verified text quote and a labelled
*visual* citation for the signatures. The request turns **Complete**, and the requester inbox
gets the handback: each item `[MET]` with the file and page, and a link to the full conversation.

### 6. A second request, closed by the provider

New request:

> @agent can you get the Q3 bank statements for the operating account (ending 4410) from Jordan Lee at Acme Logistics LLC (provider@gmail.com)? PDFs from the bank, by Oct 17.

**You should see:** three items, one per month, ready to confirm. Confirm and send.

As the provider, reply with `acme-operating-4410_2026-07.pdf` and `…-08.pdf` attached:

> July and August are attached. September hasn't been released by the bank yet, so that's all I have for now.

**You should see:** July and August **met**, September **not met**, and the state is **Closed by
provider**. The handback lists `[MISSING] … September 2026` with the reason quoted from the email.

---

## Part 2: a request list (about 2½ minutes)

### 1. Import

**Imports → Import a request list**, then choose `/tmp/requests-demo.csv`.

**You should see** the review (about a minute to analyse 30 rows):

| Row | Shown as |
|---|---|
| R-08 | Duplicate: "Identical to R-07; merged into it" |
| R-25 | Held back: too vague ("Send the usual stuff for Q3") |
| R-18 | Shared by Carlos Ruiz and Priya Shah; either can satisfy it |
| R-06, R-12 | Refer to R-05 and R-11; complete only after them |
| R-27 | No backup owner |
| R-28 | Due date already passed |

### 2. One email and one page per provider

**Apply import**: 8 drafts for 29 items ("Q3 audit: 4 items requested by Sam Rivera", …).
**Send all.** Open Mei's email (`provider+mei@gmail.com`) and its upload link: one page
listing her 4 items, each with upload and "type an answer".

### 3. One reply: a good answer, a dodge, and a file

Reply to Mei's email with
`data/starter/part2/R-13/finance-system-admins.xlsx`, `R-13/admin-list-screenshot.png` and
`R-14/admin-access-review_q2-2026.pdf` attached:

> Admin access list (R-13): the export and a screenshot showing when it was pulled are attached.
>
> Admin access review (R-14): Yes, quarterly, within two weeks of quarter end. The most recent completed one is Q2, signed off by Leo Park on 7/8, attached. Q3's is scheduled for 10/14.
>
> Access removal for leavers (R-12): access is always removed promptly in line with our offboarding policy.

**You should see:**
- **R-14 met.** Each sub-point is cited; "if not reviewed, say so" is marked *not applicable*.
- **R-12 not met** on all three sub-points (who, removal dates, why over 3 days). The follow-up
  says "Your message states only that access is always removed promptly in line with policy.
  Please provide, for each person on the R-11 list…"
- **R-13:** the rehearsal ran without the clock step and got *partly met*, because the
  screenshot's "pulled 10/12/2026" was in the future. With the clock moved forward 7 days it
  should be **met**. This exact case wasn't rehearsed, so check it once before recording.

### 4. Overdue and escalation

Use the demo clock to jump forward a day at a time and watch the app mailbox's Sent folder.
In rehearsal:

| Jump | What went out |
|---|---|
| to about Oct 14 | Pre-due reminders to Leo, Aisha and Dan. R-28 escalated to the backup (Leo), with an overdue notice to Sam |
| +3 days | Overdue notices to Leo, Aisha and Dan; reminders to Mei and Hannah |
| +4 days | Overdue notices to 4 more providers; R-07, R-10, R-11 and R-24 escalated to their backups, each with a notice to Sam |

Show one escalation email (it goes to the backup owner, never to the provider) and the matching
"Overdue:" notice in the requester inbox.

### 5. Re-import: nothing twice, only what changed

Import `/tmp/requests-demo.csv` again: **29 unchanged, 1 duplicate**, and applying it sends nothing.

Change R-21's due date from `2026-11-06` to `2026-11-13` and import again: **1 changed**
(due date, old → new). Applying sends exactly one email, to Tom:

> Sam Rivera has updated what's being requested: R-21 Tax provision: New due date: Nov 13, 2026 (was Nov 6, 2026). Nothing else has changed.

### 6. Dashboard

**Dashboard** with **Overdue only**: 7 providers behind. Hannah is at the top with 3 overdue items,
the worst 20 days late (R-28). Filter by one provider, then by status.

---

## If something goes wrong on the day

- **A reply doesn't show up.** Run `uv run rr gmail-poll`. Check that the reply went to the
  `+req+` address (reply, don't forward) and that Gmail didn't file it as spam.
- **Live email isn't available.** Switch to `EMAIL_PROVIDER=file` and feed the provider's
  replies with **Inbox → Development: inject a raw .eml**. It runs the same pipeline.
- **A model call fails.** The check shows as an error on the request and **Re-check what was received** (in the request's menu) runs it again.
  The daily token budget is `LLM_DAILY_TOKEN_BUDGET`.

## Rehearsal notes (2026-10-06)

Two scoping misses from the first rehearsal were fixed in `backend/app/llm/prompts.py` and
re-tested on the real model:
- The agent didn't ask which vendor entity "Jordan Lee" meant. It now asks.
- It made Q3 bank statements a single item. It now makes one item per month.

Still open, both cosmetic: the vendor name repeats in the first subject line, and the change
notice prints a doubled bullet (`*    New due date`).

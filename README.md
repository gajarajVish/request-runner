# Request Runner

An agent that collects documents and answers from people on a requester's behalf: it
agrees a checklist with the requester, emails the provider "via" the app, checks every
reply and upload against the checklist, follows up on what's missing, and hands the
package back.

> **Status:** scaffolding only. Open design questions live in
> [`docs/DESIGN_DECISIONS.md`](docs/DESIGN_DECISIONS.md); implementation starts once
> those are settled.

## Repo layout

```
data/starter/        test data from the take-home packet
  requests.csv       Part 2 request list (same as the brief)
  manifest.csv       file -> request -> checklist item -> expected verdict
  part1/             demo-script files for single requests (A: MSA + insurance, B: bank statements)
  part2/R-xx/        a response for each CSV row; part2/combined/ has a multi-item reply
docs/
  DESIGN_DECISIONS.md  key architecture / product decisions (to be answered)
```

## Sections to be written

- Running locally
- Connecting an email provider
- Architecture and request states
- How replies are matched to requests
- Sending "on behalf of" the requester (and the own-mailbox option)
- How checking works and where it fails
- Part 2: grouping per provider, two-owner rows, judging answers to questions
- Security: untrusted provider content, upload links, attachments
- Before real customers

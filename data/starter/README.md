# Request Runner: starter test data

Made-up files for playing the provider in the demo script. Every name, company, amount
and address is fictional; all addresses are `@example.com`.

- `requests.csv`: the Part 2 request list (same as the brief).
- `part1/A_msa-and-insurance/`: the "signed MSA + latest insurance certificate" request
  (demo steps 1–5), including an unsigned MSA that should trigger a follow-up.
- `part1/B_bank-statements/`: Q3 statements for Acme's operating account (ending 4410),
  including a partial reply that closes the request (demo step 6).
- `part2/R-xx/`: a response for each CSV row. `part2/combined/` holds one reply covering
  three items.
- `manifest.csv`: every file with the checklist item it targets and the verdict we'd
  expect. Use it for your tests.

## Using the `.eml` files

Each `.eml` is a provider reply with its attachments. Send it from an address you control
to the request's Reply-To, either by importing it into a mail client or by posting it to
your inbound provider directly. The `To` header is a placeholder (`req+REPLACE@in.yourapp.com`)
and there is no `In-Reply-To`: set both for the request you're testing.

The files cover the demo script and the obvious cases. Expect to meet others.

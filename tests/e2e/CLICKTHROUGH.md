# Click-through verification scripts

Small Playwright scripts that drive the **running** application and report what is
actually on screen, rather than what the source suggests should be there.

They were written to check a reviewer-facing report and immediately found three
claims that were wrong — a date field described as missing that existed, an
import described as a tab on a list where it is a separate screen, and a photo
upload described as available at creation when it is only offered after saving.
Reading the code alone would not have caught any of them.

## Running

Point them at a running frontend and supply a login for a throwaway account:

```bash
CLICKTHROUGH_EMAIL=you@example.local \
CLICKTHROUGH_PASSWORD='...' \
BASE_URL=http://localhost:3000 \
SHOT_DIR=./shots \
node clickthrough-inventory.mjs
```

Never point these at production: several create records.

| Script | What it does |
|---|---|
| `clickthrough-inventory.mjs` | Walks the product list and New Product form, reporting pass/fail per check |
| `clickthrough-form.mjs` | Reads every field and dropdown option inside the New Product dialog |
| `taxcheck.mjs` | Ticks "Taxable" and reports which fields that reveals |
| `flowcheck.mjs` | Creates a product with opening stock, then looks for it in the list and history |

## Two traps worth knowing

- **The terms gate** covers the page and swallows clicks until accepted. Set the
  user's `terms_accepted_version` to `settings.LEGAL_TERMS_VERSION` first, or the
  scripts stall on an invisible overlay.
- **Login is rate limited** at 20 per minute per IP. A suite that signs in afresh
  in every test will start failing partway through with a timeout that looks like
  a broken page rather than a throttle.

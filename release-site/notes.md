What installed desktop apps show in the "update available" dialog.

Write it for the person using the app, in plain language: what changed for
them, not what changed in the code. Keep it to a few sentences — this text
appears in a small dialog box.

If this file is left unchanged from the last release, CI falls back to the
subject line of the commit being released, which reads like engineering notes.
Editing this file before a release is the difference between a user seeing
"Bills can now be paid in parts, and the dashboard loads faster" and
"fix(bills): partial payment allocation + N+1 on dashboard tiles".

---

Shop prices now show VAT clearly, and a new switch lets a business that does not charge VAT turn it off. Returns ask how to refund (cash, bank, or off what the customer owes). Payroll is recorded as owed until you pay it, and bills can only be paid once approved. Many fixes make sales, tills, reports and balances add up correctly.

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

Audity has a fresh look: new fonts and colours throughout, a reorganised menu and home pages, and a new combined "New sale & invoice" page where you add items once and then create an invoice or complete a sale. Totals, VAT, deposits and refunds are now recorded more accurately, a total adjustment box lets you add a discount or extra charge, and voiding or editing an invoice now keeps your books in step.

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

Importing from a spreadsheet is more reliable. The sample files on the Import page now fill in the right columns, and they download properly in the web version too. Importing the same supplier list twice no longer makes duplicates, and purchase orders create a missing warehouse for you. Budgets and orders that already exist are now shown as skipped instead of as errors.

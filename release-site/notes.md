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

Who can see what has been tightened. Reports now follow the same permissions as the screens they come from, so a team member sees only the reports their role allows, and stock pages and actions need the Inventory permission. Voiding an invoice now needs full edit access to Sales. Cashiers who can make sales can still load the product and warehouse lists at the till. Changes saved offline in a web browser now send when you are back online. Owners: please review your team's permissions in Settings, Team.

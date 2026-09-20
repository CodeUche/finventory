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

Bills can now be paid in parts, and the app is clearer about what is happening
when your connection drops: it shows saved data instead of blinking between
online and offline, and tells you plainly when something needs a live
connection.

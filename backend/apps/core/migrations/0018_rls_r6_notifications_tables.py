"""
R-6 — enable row-level security on the two Notifications tenant tables.

Same shape as R-5, and the same cause. The notifications app was built after
batches R-2 to R-4 were generated, so its two tenant tables appeared in no
batch and would have deployed with no database-level isolation.

The difference this time is that nothing had to be noticed by a person.
RlsCoverageTests derives what it expects from the Django models, so the merge
that brought notifications onto this branch turned the suite red immediately
and named both tables. That is the check R-5 added working as intended, one
release later.

Notification rows carry who did what to whose leave request, along with the
message body shown in the app. NotificationPreference holds per-person email
opt-ins. Neither is catastrophic on its own, but both are per-person records
about employees, and they are exactly the sort of table that ends up joined
into a report later.

Policy shape, the FORCE decision, savepoint handling and the deliberate
exclusions are documented in apps/core/rls_policy.py and migration 0013.
"""

from django.db import migrations

from apps.core.rls_policy import apply_rls, revert_rls

TABLES = [
    "notifications_notification",
    "notifications_notificationpreference",
]

LABEL = "core.0018 (R-6)"


class Migration(migrations.Migration):
    atomic = False

    # notifications must have created its tables first — see the note in 0016.
    dependencies = [
        ("core", "0017_new6_org_created_at_indexes"),
        ("notifications", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(apply_rls(TABLES, LABEL), revert_rls(TABLES, LABEL), atomic=False),
    ]

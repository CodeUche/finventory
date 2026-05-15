"""
Merge migration — resolves two divergent branches that both forked from 0009.

Branch A: 0010_hide_partner_enterprise_plans → 0011_make_free_plan_public
Branch B: 0010_plan_limits_and_enterprise → … → 0017_partner_trial_30_days

0015_canonical_plan_features already overwrites all plan feature/visibility
state with the single source of truth, so the order these two branches
run in is irrelevant to the final DB state.
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("subscriptions", "0011_make_free_plan_public"),
        ("subscriptions", "0017_partner_trial_30_days"),
    ]

    operations = []

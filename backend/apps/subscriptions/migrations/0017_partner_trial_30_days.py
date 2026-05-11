"""
Update partner-starter and partner-pro trial period from 14 days to 30 days
so the first full month is free, matching the product description.
partner-agency has no trial (trial_days=0) and is unchanged.
"""
from django.db import migrations


def apply(apps, schema_editor):
    Plan = apps.get_model("subscriptions", "Plan")
    Plan.objects.filter(slug__in=["partner-starter", "partner-pro"]).update(trial_days=30)


def reverse_migration(apps, schema_editor):
    Plan = apps.get_model("subscriptions", "Plan")
    Plan.objects.filter(slug__in=["partner-starter", "partner-pro"]).update(trial_days=14)


class Migration(migrations.Migration):
    dependencies = [
        ("subscriptions", "0016_make_partner_plans_public"),
    ]

    operations = [
        migrations.RunPython(apply, reverse_migration),
    ]

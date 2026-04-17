"""
Re-enable partner plans for public listing.
Sets is_public=True on all partner-* slugs so they appear
in the Billing page when FEATURES.PARTNER_CHANNEL is enabled.
"""
from django.db import migrations


def apply(apps, schema_editor):
    Plan = apps.get_model("subscriptions", "Plan")
    Plan.objects.filter(slug__in=[
        "partner-starter",
        "partner-pro",
        "partner-agency",
    ]).update(is_public=True, is_active=True)


def reverse_migration(apps, schema_editor):
    Plan = apps.get_model("subscriptions", "Plan")
    Plan.objects.filter(slug__in=[
        "partner-starter",
        "partner-pro",
        "partner-agency",
    ]).update(is_public=False)


class Migration(migrations.Migration):
    dependencies = [
        ("subscriptions", "0015_canonical_plan_features"),
    ]

    operations = [
        migrations.RunPython(apply, reverse_migration),
    ]

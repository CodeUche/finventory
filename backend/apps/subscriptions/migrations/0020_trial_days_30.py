"""Set trial_days=30 on all plans (was 14)."""

from django.db import migrations


def set_trial_days_30(apps, schema_editor):
    Plan = apps.get_model("subscriptions", "Plan")
    Plan.objects.all().update(trial_days=30)


def revert_trial_days(apps, schema_editor):
    Plan = apps.get_model("subscriptions", "Plan")
    Plan.objects.all().update(trial_days=14)


class Migration(migrations.Migration):

    dependencies = [
        ("subscriptions", "0019_update_pricing_and_professional_payroll"),
    ]

    operations = [
        migrations.RunPython(set_trial_days_30, revert_trial_days),
    ]

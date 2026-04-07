"""Make Free and Enterprise plans visible in the public plans listing."""
from django.db import migrations


def update_visibility(apps, schema_editor):
    Plan = apps.get_model("subscriptions", "Plan")
    Plan.objects.filter(slug__in=["free", "enterprise", "enterprise-annual"]).update(is_public=True)


def reverse_migration(apps, schema_editor):
    Plan = apps.get_model("subscriptions", "Plan")
    Plan.objects.filter(slug="free").update(is_public=False)
    Plan.objects.filter(slug__in=["enterprise", "enterprise-annual"]).update(is_public=False)


class Migration(migrations.Migration):
    dependencies = [
        ("subscriptions", "0010_hide_partner_enterprise_plans"),
    ]

    operations = [
        migrations.RunPython(update_visibility, reverse_migration),
    ]

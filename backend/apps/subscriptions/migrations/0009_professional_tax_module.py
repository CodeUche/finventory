"""
Data migration:
- Add 'tax' to Professional and Professional Annual plan modules.
  These plans already have tax_engine='advanced' but the 'tax' module key
  was missing from the modules list, so the Tax page was hidden in the sidebar.
"""
from django.db import migrations

PRO_SLUGS = ["professional", "professional-annual"]


def add_tax_to_professional(apps, schema_editor):
    Plan = apps.get_model("subscriptions", "Plan")
    for plan in Plan.objects.filter(slug__in=PRO_SLUGS):
        features = dict(plan.features)
        modules = list(features.get("modules", []))
        if "tax" not in modules:
            modules.append("tax")
            features["modules"] = modules
            Plan.objects.filter(pk=plan.pk).update(features=features)


def reverse_migration(apps, schema_editor):
    Plan = apps.get_model("subscriptions", "Plan")
    for plan in Plan.objects.filter(slug__in=PRO_SLUGS):
        features = dict(plan.features)
        features["modules"] = [m for m in features.get("modules", []) if m != "tax"]
        Plan.objects.filter(pk=plan.pk).update(features=features)


class Migration(migrations.Migration):
    dependencies = [
        ("subscriptions", "0008_free_vat_class_access"),
    ]

    operations = [
        migrations.RunPython(add_tax_to_professional, reverse_migration),
    ]

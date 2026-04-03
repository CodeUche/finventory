"""
Data migration:
- Add 'tax' to Free plan modules so VAT Classes appear in the sidebar
- Change tax_engine from 'basic' → 'vat_only' so advanced tax tabs remain locked
"""
from django.db import migrations


def enable_vat_class_for_free(apps, schema_editor):
    Plan = apps.get_model("subscriptions", "Plan")
    plan = Plan.objects.filter(slug="free").first()
    if not plan:
        return

    features = dict(plan.features)
    features["tax_engine"] = "vat_only"
    if "tax" not in features.get("modules", []):
        features["modules"] = list(features.get("modules", [])) + ["tax"]

    Plan.objects.filter(pk=plan.pk).update(features=features)


def reverse_migration(apps, schema_editor):
    Plan = apps.get_model("subscriptions", "Plan")
    plan = Plan.objects.filter(slug="free").first()
    if not plan:
        return

    features = dict(plan.features)
    features["tax_engine"] = "basic"
    features["modules"] = [m for m in features.get("modules", []) if m != "tax"]

    Plan.objects.filter(pk=plan.pk).update(features=features)


class Migration(migrations.Migration):
    dependencies = [
        ("subscriptions", "0007_free_tier_and_pricing"),
    ]

    operations = [
        migrations.RunPython(enable_vat_class_for_free, reverse_migration),
    ]

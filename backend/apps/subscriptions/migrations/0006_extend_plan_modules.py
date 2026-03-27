"""
Data migration: add audit_log, owner_analytics, and team module keys to
professional and business plans. Starter plan remains unchanged (no access
to these features).
"""

from django.db import migrations

EXTRA_MODULES = ["audit_log", "owner_analytics", "team"]


def add_modules(apps, schema_editor):
    Plan = apps.get_model("subscriptions", "Plan")
    for slug in ("professional", "business"):
        plan = Plan.objects.filter(slug=slug).first()
        if not plan:
            continue
        mods = plan.features.get("modules") or []
        for m in EXTRA_MODULES:
            if m not in mods:
                mods.append(m)
        plan.features = {**plan.features, "modules": mods}
        plan.save()


def remove_modules(apps, schema_editor):
    Plan = apps.get_model("subscriptions", "Plan")
    for slug in ("professional", "business"):
        plan = Plan.objects.filter(slug=slug).first()
        if not plan:
            continue
        mods = [m for m in (plan.features.get("modules") or []) if m not in EXTRA_MODULES]
        plan.features = {**plan.features, "modules": mods}
        plan.save()


class Migration(migrations.Migration):

    dependencies = [
        ("subscriptions", "0005_cleanup_plans"),
    ]

    operations = [
        migrations.RunPython(add_modules, reverse_code=remove_modules),
    ]

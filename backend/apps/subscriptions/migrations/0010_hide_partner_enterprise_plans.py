"""
Data migration: hide Partner and Enterprise plans from public listing.
Only Free, Professional, and Business (+ their annual variants) are shown
to users during onboarding.
"""
from django.db import migrations

HIDE_SLUGS = [
    "enterprise",
    "enterprise-annual",
    "partner-starter",
    "partner-pro",
    "partner-agency",
    "starter",          # legacy
    "starter (legacy)",
]


def hide_plans(apps, schema_editor):
    Plan = apps.get_model("subscriptions", "Plan")
    Plan.objects.filter(slug__in=HIDE_SLUGS).update(is_public=False)
    # Also catch any slug that starts with "partner-" or "enterprise"
    for plan in Plan.objects.filter(is_public=True):
        if plan.slug.startswith("partner-") or plan.slug.startswith("enterprise"):
            Plan.objects.filter(pk=plan.pk).update(is_public=False)


def reverse_migration(apps, schema_editor):
    pass  # Non-destructive reverse


class Migration(migrations.Migration):
    dependencies = [
        ("subscriptions", "0009_professional_tax_module"),
    ]

    operations = [
        migrations.RunPython(hide_plans, reverse_migration),
    ]

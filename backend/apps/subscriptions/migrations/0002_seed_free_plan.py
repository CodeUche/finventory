"""
Data migration: seed the Free plan.

The Free plan grants full access to all features with no artificial limits.
It is automatically assigned to every new organisation at creation time.
"""

from django.db import migrations

FREE_PLAN_FEATURES = {
    # Numeric limits — 999999 is effectively unlimited
    "max_products": 999999,
    "max_users": 999999,
    "max_warehouses": 999999,
    # Boolean feature gates — all enabled
    "multi_warehouse": True,
    "advanced_reports": True,
    "api_access": True,
    "credit_management": True,
    "export_reports": True,
    "tax_engine": "advanced",
    "purchase_orders": True,
    "supplier_management": True,
}


def seed_free_plan(apps, schema_editor):
    Plan = apps.get_model("subscriptions", "Plan")
    Plan.objects.get_or_create(
        slug="free",
        defaults={
            "name": "Free",
            "description": "Full-featured plan. All features included, no limits.",
            "price": 0,
            "interval": "monthly",
            "trial_days": 0,
            "is_active": True,
            "is_public": False,   # Not shown on pricing page (auto-assigned internally)
            "features": FREE_PLAN_FEATURES,
            "display_order": 0,
        },
    )


def reverse_free_plan(apps, schema_editor):
    Plan = apps.get_model("subscriptions", "Plan")
    Plan.objects.filter(slug="free").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("subscriptions", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_free_plan, reverse_code=reverse_free_plan),
    ]

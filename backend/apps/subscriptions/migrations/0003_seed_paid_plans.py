"""
Data migration: seed Starter, Professional and Business paid plans.

Prices are in NGN (stored as Decimal). Adjust in the Django admin
or via a follow-up migration before going live.

Feature limits mirror what is enforced by SubscriptionActive
permission and SubscriptionService.check_feature().
"""

from django.db import migrations

PLANS = [
    {
        "name": "Starter",
        "slug": "starter",
        "description": "Perfect for small businesses just getting started.",
        "price": "5000.00",
        "interval": "monthly",
        "trial_days": 14,
        "is_active": True,
        "is_public": True,
        "display_order": 1,
        "features": {
            "max_products": 100,
            "max_users": 3,
            "max_warehouses": 1,
            "multi_warehouse": False,
            "advanced_reports": False,
            "api_access": False,
            "credit_management": True,
            "export_reports": True,
            "tax_engine": "basic",
            "purchase_orders": True,
            "supplier_management": True,
        },
    },
    {
        "name": "Professional",
        "slug": "professional",
        "description": "For growing businesses that need more power.",
        "price": "15000.00",
        "interval": "monthly",
        "trial_days": 14,
        "is_active": True,
        "is_public": True,
        "display_order": 2,
        "features": {
            "max_products": 500,
            "max_users": 5,
            "max_warehouses": 3,
            "multi_warehouse": True,
            "advanced_reports": True,
            "api_access": False,
            "credit_management": True,
            "export_reports": True,
            "tax_engine": "advanced",
            "purchase_orders": True,
            "supplier_management": True,
        },
    },
    {
        "name": "Business",
        "slug": "business",
        "description": "Unlimited access for established businesses.",
        "price": "30000.00",
        "interval": "monthly",
        "trial_days": 14,
        "is_active": True,
        "is_public": True,
        "display_order": 3,
        "features": {
            "max_products": 999999,
            "max_users": 999999,
            "max_warehouses": 999999,
            "multi_warehouse": True,
            "advanced_reports": True,
            "api_access": True,
            "credit_management": True,
            "export_reports": True,
            "tax_engine": "advanced",
            "purchase_orders": True,
            "supplier_management": True,
        },
    },
]


def seed_paid_plans(apps, schema_editor):
    Plan = apps.get_model("subscriptions", "Plan")
    for data in PLANS:
        Plan.objects.get_or_create(slug=data["slug"], defaults=data)


def reverse_paid_plans(apps, schema_editor):
    Plan = apps.get_model("subscriptions", "Plan")
    Plan.objects.filter(slug__in=["starter", "professional", "business"]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("subscriptions", "0002_seed_free_plan"),
    ]

    operations = [
        migrations.RunPython(seed_paid_plans, reverse_code=reverse_paid_plans),
    ]

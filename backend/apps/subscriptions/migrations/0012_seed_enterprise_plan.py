"""
Seed / update Enterprise and Enterprise Annual plans with correct features.
Enterprise = Business features + API access + dedicated support + white-label.
"""
from django.db import migrations

ENTERPRISE_FEATURES = {
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
    "recurring_invoices": True,
    "quotes": True,
    "payroll": True,
    "white_label": True,
    "dedicated_support": True,
    "custom_integrations": True,
    "modules": [
        "invoicing", "sales", "customers", "expenses", "inventory",
        "suppliers", "purchases", "quotes", "recurring", "budget",
        "reports", "payroll", "accounting", "owner_analytics",
        "audit_log", "team", "api_access", "tax",
    ],
}


def seed_enterprise(apps, schema_editor):
    Plan = apps.get_model("subscriptions", "Plan")

    Plan.objects.update_or_create(
        slug="enterprise",
        defaults=dict(
            name="Enterprise",
            description="Custom scale — API access, white-label, dedicated support, and unlimited everything.",
            price=150000,
            interval="monthly",
            trial_days=14,
            is_active=True,
            is_public=True,
            display_order=5,
            features=ENTERPRISE_FEATURES,
        ),
    )

    Plan.objects.update_or_create(
        slug="enterprise-annual",
        defaults=dict(
            name="Enterprise Annual",
            description="All Enterprise features billed annually. Save one month.",
            price=1650000,
            interval="annual",
            trial_days=0,
            is_active=True,
            is_public=True,
            display_order=6,
            features=ENTERPRISE_FEATURES,
        ),
    )


def reverse_migration(apps, schema_editor):
    pass  # non-destructive


class Migration(migrations.Migration):
    dependencies = [
        ("subscriptions", "0011_make_free_plan_public"),
    ]

    operations = [
        migrations.RunPython(seed_enterprise, reverse_migration),
    ]

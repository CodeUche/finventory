"""Update Enterprise plan with the full correct feature set."""
from django.db import migrations

ENTERPRISE_FEATURES = {
    "max_products": 999999,
    "max_users": 999999,
    "max_warehouses": 999999,
    "multi_warehouse": True,
    "advanced_reports": True,
    "api_access": True,
    "api_write": True,
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
    "multi_entity": True,
    "sso": True,
    "custom_roles": True,
    "bulk_export": True,
    "modules": [
        "invoicing", "sales", "customers", "expenses", "inventory",
        "suppliers", "purchases", "quotes", "recurring", "budget",
        "reports", "payroll", "accounting", "owner_analytics",
        "audit_log", "team", "api_access", "tax",
    ],
}

def update_enterprise(apps, schema_editor):
    Plan = apps.get_model("subscriptions", "Plan")
    for slug in ["enterprise", "enterprise-annual"]:
        Plan.objects.filter(slug=slug).update(features=ENTERPRISE_FEATURES)

def reverse_migration(apps, schema_editor):
    pass

class Migration(migrations.Migration):
    dependencies = [
        ("subscriptions", "0012_seed_enterprise_plan"),
    ]
    operations = [
        migrations.RunPython(update_enterprise, reverse_migration),
    ]

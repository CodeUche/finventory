"""
Data migration: add `modules` array to each plan's features dict.

This drives sidebar/route gating in the frontend — only modules listed
here are visible to users on that plan.

Starter   → sales, expenses, basic inventory, quotes, recurring
Professional → + reports, CRM, procurement, accounting, tax, budgets
Business  → + payroll (audit log is ownerOnly and always shown to owners)
Free      → no restriction (null modules — used for superusers)
"""

from django.db import migrations

STARTER_MODULES = [
    "sales", "expenses", "inventory", "quotes", "recurring",
]

PROFESSIONAL_MODULES = STARTER_MODULES + [
    "reports", "customers", "purchases", "suppliers",
    "bills", "accounting", "tax", "budget",
]

BUSINESS_MODULES = PROFESSIONAL_MODULES + ["payroll"]


def update_modules(apps, schema_editor):
    Plan = apps.get_model("subscriptions", "Plan")

    updates = {
        "starter": {
            "modules": STARTER_MODULES,
            "max_products": 50,
            "max_warehouses": 1,
            "max_users": 1,
        },
        "professional": {
            "modules": PROFESSIONAL_MODULES,
            "max_products": 100,
            "max_warehouses": 3,
            "max_users": 3,
        },
        "business": {
            "modules": BUSINESS_MODULES,
            "max_products": 999999,
            "max_warehouses": 999999,
            "max_users": 6,
        },
        # Free plan: no modules restriction — all features open
        "free": {
            "modules": None,
        },
    }

    for slug, patch in updates.items():
        plan = Plan.objects.filter(slug=slug).first()
        if plan:
            plan.features = {**plan.features, **patch}
            plan.save()


def reverse_modules(apps, schema_editor):
    Plan = apps.get_model("subscriptions", "Plan")
    for plan in Plan.objects.filter(slug__in=["starter", "professional", "business", "free"]):
        features = {k: v for k, v in plan.features.items() if k != "modules"}
        plan.features = features
        plan.save()


class Migration(migrations.Migration):

    dependencies = [
        ("subscriptions", "0003_seed_paid_plans"),
    ]

    operations = [
        migrations.RunPython(update_modules, reverse_code=reverse_modules),
    ]

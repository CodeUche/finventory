"""
Data migration:
- Professional plan: max_users=3, max_warehouses=3
- Business plan: max_users=5, max_warehouses=5
- Add Enterprise plan: unlimited users + warehouses, all features, white-label, dedicated support
"""
from django.db import migrations


ENTERPRISE_FEATURES = {
    "max_products": 999999,
    "max_users": 999999,
    "max_warehouses": 999999,
    "max_invoices_per_month": 999999,
    "max_customers": 999999,
    "max_expenses_per_month": 999999,
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
    "custom_domain": True,
    "dedicated_support": True,
    "sla_support": True,
    "custom_integrations": True,
    "audit_log": True,
    "bulk_operations": True,
    "advanced_payroll": True,
    "multi_currency": True,
    "modules": [
        "invoicing", "sales", "customers", "expenses", "inventory",
        "suppliers", "purchases", "quotes", "recurring", "budget",
        "reports", "payroll", "accounting", "owner_analytics",
        "audit_log", "team", "api_access", "tax", "bills", "credits",
    ],
}


def apply(apps, schema_editor):
    Plan = apps.get_model("subscriptions", "Plan")

    # ── Professional: 3 members, 3 locations ──────────────────────────────────
    for slug in ("professional", "professional-annual"):
        plan = Plan.objects.filter(slug=slug).first()
        if plan:
            f = dict(plan.features)
            f["max_users"] = 3
            f["max_warehouses"] = 3
            Plan.objects.filter(pk=plan.pk).update(features=f)

    # ── Business: 5 members, 5 locations ─────────────────────────────────────
    for slug in ("business", "business-annual"):
        plan = Plan.objects.filter(slug=slug).first()
        if plan:
            f = dict(plan.features)
            f["max_users"] = 5
            f["max_warehouses"] = 5
            Plan.objects.filter(pk=plan.pk).update(features=f)

    # ── Enterprise plan ───────────────────────────────────────────────────────
    if not Plan.objects.filter(slug="enterprise").exists():
        Plan.objects.create(
            name="Enterprise",
            slug="enterprise",
            description=(
                "For large businesses and enterprises. Unlimited users, locations, and products. "
                "Includes white-label, dedicated support, custom integrations, and SLA."
            ),
            price=150000,
            interval="monthly",
            trial_days=0,
            is_active=True,
            is_public=True,
            display_order=5,
            features=ENTERPRISE_FEATURES,
        )
    else:
        Plan.objects.filter(slug="enterprise").update(
            description=(
                "For large businesses and enterprises. Unlimited users, locations, and products. "
                "Includes white-label, dedicated support, custom integrations, and SLA."
            ),
            price=150000,
            features=ENTERPRISE_FEATURES,
            display_order=5,
        )

    # Also create Enterprise Annual (2 months free = 10 × ₦150,000 = ₦1,500,000)
    if not Plan.objects.filter(slug="enterprise-annual").exists():
        Plan.objects.create(
            name="Enterprise Annual",
            slug="enterprise-annual",
            description="All Enterprise features, billed annually. Save two months.",
            price=1500000,
            interval="annual",
            trial_days=0,
            is_active=True,
            is_public=True,
            display_order=6,
            features={**ENTERPRISE_FEATURES},
        )
    else:
        Plan.objects.filter(slug="enterprise-annual").update(
            price=1500000,
            features={**ENTERPRISE_FEATURES},
            display_order=6,
        )


def reverse_migration(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("subscriptions", "0009_professional_tax_module"),
    ]

    operations = [
        migrations.RunPython(apply, reverse_migration),
    ]

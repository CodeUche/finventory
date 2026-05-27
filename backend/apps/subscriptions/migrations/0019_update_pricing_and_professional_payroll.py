"""
Pricing update + Professional payroll unlock.

Changes:
  Professional monthly  ₦19,500  →  ₦13,000
  Professional annual   ₦214,500 →  ₦130,000  (2 months free)
  Business monthly      ₦35,000  →  ₦30,000
  Business annual       ₦385,000 →  ₦300,000  (2 months free)

Feature change:
  Professional now includes payroll (capped at 5 employees via
  max_payroll_employees=5). This makes Professional a genuine
  value proposition for small businesses and moves the conversion
  barrier down from ₦30,000 to ₦13,000.
"""

from django.db import migrations


PROFESSIONAL_FEATURES = {
    "max_products": 999999,
    "max_users": 3,
    "max_warehouses": 3,
    "max_invoices_per_month": 999999,
    "max_customers": 999999,
    "max_expenses_per_month": 999999,
    "multi_warehouse": True,
    "advanced_reports": True,
    "api_access": False,
    "tax_engine": "advanced",
    "purchase_orders": True,
    "supplier_management": True,
    "recurring_invoices": True,
    "quotes": True,
    "payroll": True,
    "max_payroll_employees": 5,
    "modules": [
        "invoicing", "sales", "customers", "expenses", "inventory",
        "suppliers", "purchases", "quotes", "recurring", "budget",
        "reports", "audit_log", "team", "tax", "bills", "payroll",
    ],
}

UPDATES = [
    # (slug,              new_price,  new_features_or_None)
    ("professional",        13000,    PROFESSIONAL_FEATURES),
    ("professional-annual", 130000,   PROFESSIONAL_FEATURES),
    ("business",            30000,    None),
    ("business-annual",     300000,   None),
]


def apply(apps, schema_editor):
    Plan = apps.get_model("subscriptions", "Plan")
    for slug, price, features in UPDATES:
        kwargs = {"price": price}
        if features is not None:
            kwargs["features"] = features
        updated = Plan.objects.filter(slug=slug).update(**kwargs)
        if updated == 0:
            import logging
            logging.getLogger(__name__).warning(
                "0019: plan slug=%r not found — skipped", slug
            )


def reverse_migration(apps, schema_editor):
    Plan = apps.get_model("subscriptions", "Plan")
    Plan.objects.filter(slug="professional").update(price=19500)
    Plan.objects.filter(slug="professional-annual").update(price=214500)
    Plan.objects.filter(slug="business").update(price=35000)
    Plan.objects.filter(slug="business-annual").update(price=385000)


class Migration(migrations.Migration):

    dependencies = [
        ("subscriptions", "0018_merge_free_plan_branch"),
    ]

    operations = [
        migrations.RunPython(apply, reverse_migration),
    ]

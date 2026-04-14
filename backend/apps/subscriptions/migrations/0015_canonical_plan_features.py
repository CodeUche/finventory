"""
Canonical plan feature definitions — single source of truth.

This migration overwrites all plan features to exactly match the
MODULE_ROWS display on the BillingPage. After this migration the DB
is authoritative; no prior migration's partial updates matter.

Plan summary:
  Free        — core tools only, hard caps, VAT only
  Professional — core + procurement/quotes/bills/budget/audit/team, 3 users, 3 locations
  Business     — Professional + payroll/accounting/owner_analytics/read API, 5 users, 5 locations
  Enterprise   — everything, unlimited
"""
from django.db import migrations

# ── Feature definitions ────────────────────────────────────────────────────────

FREE_FEATURES = {
    # Hard limits
    "max_products": 20,
    "max_users": 1,
    "max_warehouses": 1,
    "max_invoices_per_month": 10,
    "max_customers": 20,
    "max_expenses_per_month": 10,
    # Feature flags
    "multi_warehouse": False,
    "advanced_reports": False,
    "api_access": False,
    "tax_engine": "vat_only",
    # Modules (gates sidebar nav + backend endpoints)
    "modules": [
        "invoicing", "sales", "customers", "expenses",
        "inventory", "reports", "tax",
    ],
}

PROFESSIONAL_FEATURES = {
    # Unlimited on paid plans (999999 sentinel = ∞)
    "max_products": 999999,
    "max_users": 3,
    "max_warehouses": 3,
    "max_invoices_per_month": 999999,
    "max_customers": 999999,
    "max_expenses_per_month": 999999,
    # Feature flags
    "multi_warehouse": True,
    "advanced_reports": True,
    "api_access": False,
    "tax_engine": "advanced",   # VAT + Income Tax
    "purchase_orders": True,
    "supplier_management": True,
    "recurring_invoices": True,
    "quotes": True,
    # Modules — no payroll, no accounting, no owner_analytics
    "modules": [
        "invoicing", "sales", "customers", "expenses", "inventory",
        "suppliers", "purchases", "quotes", "recurring", "budget",
        "reports", "audit_log", "team", "tax", "bills",
    ],
}

BUSINESS_FEATURES = {
    "max_products": 999999,
    "max_users": 5,
    "max_warehouses": 5,
    "max_invoices_per_month": 999999,
    "max_customers": 999999,
    "max_expenses_per_month": 999999,
    "multi_warehouse": True,
    "advanced_reports": True,
    "api_access": True,
    "api_write": False,         # read-only API
    "tax_engine": "advanced",
    "purchase_orders": True,
    "supplier_management": True,
    "recurring_invoices": True,
    "quotes": True,
    "payroll": True,
    # Modules — adds payroll, accounting, owner_analytics vs Professional
    "modules": [
        "invoicing", "sales", "customers", "expenses", "inventory",
        "suppliers", "purchases", "quotes", "recurring", "budget",
        "reports", "payroll", "accounting", "owner_analytics",
        "audit_log", "team", "tax", "bills",
    ],
}

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
    "api_write": True,          # full read/write REST API + webhooks
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
    "multi_entity": True,
    "sso": True,
    "custom_roles": True,
    "bulk_export": True,
    # Modules — adds api_access vs Business
    "modules": [
        "invoicing", "sales", "customers", "expenses", "inventory",
        "suppliers", "purchases", "quotes", "recurring", "budget",
        "reports", "payroll", "accounting", "owner_analytics",
        "audit_log", "team", "api_access", "tax", "bills",
    ],
}

# Map slug → features for every plan variant (monthly + annual share the same features)
PLAN_FEATURES = {
    "free":                  FREE_FEATURES,
    "professional":          PROFESSIONAL_FEATURES,
    "professional-annual":   PROFESSIONAL_FEATURES,
    "business":              BUSINESS_FEATURES,
    "business-annual":       BUSINESS_FEATURES,
    "enterprise":            ENTERPRISE_FEATURES,
    "enterprise-annual":     ENTERPRISE_FEATURES,
}


def apply(apps, schema_editor):
    Plan = apps.get_model("subscriptions", "Plan")
    for slug, features in PLAN_FEATURES.items():
        updated = Plan.objects.filter(slug=slug).update(features=features)
        if updated == 0:
            import logging
            logging.getLogger(__name__).warning(
                "canonical_plan_features: plan slug=%r not found — skipped", slug
            )


def reverse_migration(apps, schema_editor):
    pass   # irreversible — re-run forward migration to restore


class Migration(migrations.Migration):
    dependencies = [
        ("subscriptions", "0014_merge_0011_partner_plans_0013_enterprise_features_v2"),
    ]

    operations = [
        migrations.RunPython(apply, reverse_migration),
    ]

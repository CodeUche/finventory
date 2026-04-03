"""
Partner / Accountant Channel plans.

Three tiers aligned with the 5-layer revenue model:
    Layer 1: Partner licence fee   (the plan price itself)
    Layer 2: Per-client seat       (each SMB org keeps its own subscription)
    Layer 3: Volume tiers          (max_managed_clients cap per tier)
    Layer 4: Referral commission   (tracked on PartnerProfile.commission_rate)
    Layer 5: Premium tools upsell  (white_label_reports, consolidated_reporting)

Pricing (monthly, NGN):
    Partner Starter  — ₦30,000/mo  — up to 10 SMB clients
    Partner Pro      — ₦75,000/mo  — up to 30 SMB clients  + white-label reports
    Partner Agency   — ₦150,000/mo — unlimited clients + full white-label + consolidated reporting
"""
from django.db import migrations

PARTNER_BASE_FEATURES = {
    # Partners get all Business-tier modules for managing their OWN firm
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
    "audit_log": True,
    "bulk_operations": True,
    "multi_currency": True,
    "accounting": True,
    # Partner-specific gates
    "is_partner": True,
    "partner_dashboard": True,
    "modules": [
        "invoicing", "sales", "customers", "expenses", "inventory",
        "suppliers", "purchases", "quotes", "recurring", "budget",
        "reports", "payroll", "accounting", "owner_analytics",
        "audit_log", "team", "api_access", "tax", "bills", "credits",
    ],
}

PARTNER_STARTER = {
    **PARTNER_BASE_FEATURES,
    "max_managed_clients": 10,
    "white_label_reports": False,
    "consolidated_reporting": False,
    "volume_discount": False,
}

PARTNER_PRO = {
    **PARTNER_BASE_FEATURES,
    "max_managed_clients": 30,
    "white_label_reports": True,
    "consolidated_reporting": True,
    "volume_discount": True,
    "bulk_client_operations": True,
}

PARTNER_AGENCY = {
    **PARTNER_BASE_FEATURES,
    "max_managed_clients": 999999,
    "white_label_reports": True,
    "consolidated_reporting": True,
    "volume_discount": True,
    "bulk_client_operations": True,
    "custom_branding": True,
    "client_health_dashboard": True,
    "dedicated_support": True,
    "sla_support": True,
}


def apply(apps, schema_editor):
    Plan = apps.get_model("subscriptions", "Plan")

    plans = [
        {
            "name": "Partner Starter",
            "slug": "partner-starter",
            "description": (
                "For accountants and bookkeepers managing up to 10 SMB clients. "
                "Includes your own full Business-tier account plus a multi-client dashboard."
            ),
            "price": 30000,
            "interval": "monthly",
            "trial_days": 14,
            "display_order": 7,
            "features": PARTNER_STARTER,
        },
        {
            "name": "Partner Pro",
            "slug": "partner-pro",
            "description": (
                "Manage up to 30 clients with white-label reports and consolidated reporting. "
                "Volume pricing kicks in as your client base grows."
            ),
            "price": 75000,
            "interval": "monthly",
            "trial_days": 14,
            "display_order": 8,
            "features": PARTNER_PRO,
        },
        {
            "name": "Partner Agency",
            "slug": "partner-agency",
            "description": (
                "Unlimited clients, full white-label branding, dedicated support, and SLA. "
                "Your logo, your brand — powered by Audity."
            ),
            "price": 150000,
            "interval": "monthly",
            "trial_days": 0,
            "display_order": 9,
            "features": PARTNER_AGENCY,
        },
    ]

    for p in plans:
        if not Plan.objects.filter(slug=p["slug"]).exists():
            Plan.objects.create(
                is_active=True,
                is_public=True,
                **p,
            )
        else:
            Plan.objects.filter(slug=p["slug"]).update(
                description=p["description"],
                price=p["price"],
                features=p["features"],
                display_order=p["display_order"],
            )


def reverse_migration(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("subscriptions", "0010_plan_limits_and_enterprise"),
    ]

    operations = [
        migrations.RunPython(apply, reverse_migration),
    ]

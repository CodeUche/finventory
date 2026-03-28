"""
Data migration:
- Rename Starter plan → Free (price=0, tight limits, no expiry)
- Update Professional price → ₦19,500
- Update Business price → ₦35,000
- Create Professional Annual (11 months, 1 month free) → ₦214,500
- Create Business Annual (11 months, 1 month free) → ₦385,000
"""
from django.db import migrations


FREE_FEATURES = {
    "max_products": 20,
    "max_users": 1,
    "max_warehouses": 1,
    "max_invoices_per_month": 10,
    "max_customers": 20,
    "max_expenses_per_month": 10,
    "multi_warehouse": False,
    "advanced_reports": False,
    "api_access": False,
    "tax_engine": "basic",
    "quotes": False,
    "recurring_invoices": False,
    "purchase_orders": False,
    "payroll": False,
    "modules": ["invoicing", "sales", "customers", "expenses", "inventory"],
}

PROFESSIONAL_FEATURES = {
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
    "recurring_invoices": True,
    "quotes": True,
    "payroll": False,
    "modules": ["invoicing", "sales", "customers", "expenses", "inventory",
                "suppliers", "purchases", "quotes", "recurring", "budget",
                "reports", "audit_log", "team"],
}

BUSINESS_FEATURES = {
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
    "modules": ["invoicing", "sales", "customers", "expenses", "inventory",
                "suppliers", "purchases", "quotes", "recurring", "budget",
                "reports", "payroll", "accounting", "owner_analytics",
                "audit_log", "team", "api_access"],
}


def update_plans(apps, schema_editor):
    Plan = apps.get_model("subscriptions", "Plan")

    # ── Free plan ─────────────────────────────────────────────────────────────
    # Strategy: prefer updating the existing "free" slug plan; if not found,
    # update "starter" in-place. This avoids FK constraint errors on Subscription.
    free_plan = Plan.objects.filter(slug="free").first()
    starter_plan = Plan.objects.filter(slug="starter").first()

    if free_plan:
        # Update the existing free plan with new strict limits
        Plan.objects.filter(pk=free_plan.pk).update(
            name="Free",
            description="Get started at no cost. Perfect for freelancers and new businesses.",
            price=0,
            trial_days=0,
            display_order=0,
            features=FREE_FEATURES,
        )
        # If there's also a separate starter plan, rename it to avoid conflict
        if starter_plan:
            Plan.objects.filter(pk=starter_plan.pk).update(
                name="Starter (Legacy)",
                is_public=False,
                display_order=99,
            )
    elif starter_plan:
        # No "free" slug plan exists — safely rename starter → free
        Plan.objects.filter(pk=starter_plan.pk).update(
            name="Free",
            slug="free",
            description="Get started at no cost. Perfect for freelancers and new businesses.",
            price=0,
            trial_days=0,
            display_order=0,
            features=FREE_FEATURES,
        )
    else:
        # Neither exists — create from scratch
        Plan.objects.create(
            name="Free",
            slug="free",
            description="Get started at no cost. Perfect for freelancers and new businesses.",
            price=0,
            interval="monthly",
            trial_days=0,
            is_active=True,
            is_public=True,
            display_order=0,
            features=FREE_FEATURES,
        )

    # ── Professional monthly ─────────────────────────────────────────────────
    Plan.objects.filter(slug="professional").update(
        price=19500,
        description="For growing businesses that need advanced tools and team access.",
        features=PROFESSIONAL_FEATURES,
        display_order=1,
    )

    # ── Business monthly ─────────────────────────────────────────────────────
    Plan.objects.filter(slug="business").update(
        price=35000,
        description="For established businesses that need everything — payroll, accounting, and API.",
        features=BUSINESS_FEATURES,
        display_order=2,
    )

    # ── Professional Annual (1 month free = 11 × ₦19,500 = ₦214,500) ────────
    if not Plan.objects.filter(slug="professional-annual").exists():
        Plan.objects.create(
            name="Professional Annual",
            slug="professional-annual",
            description="All Professional features, billed annually. Save one month.",
            price=214500,
            interval="annual",
            trial_days=0,
            is_active=True,
            is_public=True,
            display_order=3,
            features={**PROFESSIONAL_FEATURES},
        )
    else:
        Plan.objects.filter(slug="professional-annual").update(
            price=214500,
            features={**PROFESSIONAL_FEATURES},
        )

    # ── Business Annual (1 month free = 11 × ₦35,000 = ₦385,000) ────────────
    if not Plan.objects.filter(slug="business-annual").exists():
        Plan.objects.create(
            name="Business Annual",
            slug="business-annual",
            description="All Business features, billed annually. Save one month.",
            price=385000,
            interval="annual",
            trial_days=0,
            is_active=True,
            is_public=True,
            display_order=4,
            features={**BUSINESS_FEATURES},
        )
    else:
        Plan.objects.filter(slug="business-annual").update(
            price=385000,
            features={**BUSINESS_FEATURES},
        )


def reverse_migration(apps, schema_editor):
    pass  # Non-destructive reverse: leave plans as-is


class Migration(migrations.Migration):
    dependencies = [
        ("subscriptions", "0006_extend_plan_modules"),
    ]

    operations = [
        migrations.RunPython(update_plans, reverse_migration),
    ]

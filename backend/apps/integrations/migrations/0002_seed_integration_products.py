"""
Data migration: seed the initial integrations-marketplace catalog.

IntegrationProduct itself lives in apps.subscriptions (migration 0023), not
here — this migration only inserts rows, matching the same
apps.get_model()-based, reversible pattern as
apps.subscriptions.migrations.0003_seed_paid_plans. It lives in
apps.integrations (not a follow-up subscriptions migration) because
subscriptions' schema is explicitly frozen per this task's constraints —
only data is added, and only from this app.

Prices are one-time fees in NGN (MoneyField / Decimal), matching the
convention `Plan.price` already uses.
"""

from django.db import migrations

PRODUCTS = [
    {
        "key": "webhooks",
        "name": "Custom Webhooks",
        "price": "15000.00",
        "description": (
            "Connect any external app or tool to Audity via outbound webhooks. "
            "Subscribe to business events (invoices, payments, HR) and receive "
            "signed HTTP callbacks in real time."
        ),
        "is_active": True,
    },
    {
        "key": "zapier",
        "name": "Zapier",
        "price": "20000.00",
        "description": (
            "Connect Audity to 5,000+ apps via Zapier. Includes a Zapier-compatible "
            "REST Hooks API and a scoped API key for polling triggers."
        ),
        "is_active": True,
    },
]


def seed_integration_products(apps, schema_editor):
    IntegrationProduct = apps.get_model("subscriptions", "IntegrationProduct")
    for data in PRODUCTS:
        IntegrationProduct.objects.get_or_create(key=data["key"], defaults=data)


def reverse_integration_products(apps, schema_editor):
    IntegrationProduct = apps.get_model("subscriptions", "IntegrationProduct")
    IntegrationProduct.objects.filter(key__in=["webhooks", "zapier"]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("integrations", "0001_initial"),
        ("subscriptions", "0023_integrationproduct_paymenthistory_expected_amount_and_more"),
    ]

    operations = [
        migrations.RunPython(seed_integration_products, reverse_code=reverse_integration_products),
    ]

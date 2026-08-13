"""
Add max_connectors to every plan's features JSON — the Connectors feature's
plan-quota gate (apps.connectors.services.ConnectorQuotaService).

Free = 0, Professional = 1, Business = 3, Enterprise = 5 (both monthly and
annual variants share the same features, matching 0015_canonical_plan_features's
convention). Partner-tier plans are left untouched (default via .get(...,0)
at read time — apps.connectors.services.ConnectorQuotaService.max_connectors
treats a missing key as 0, which is the correct fail-closed default for a
plan tier Connectors was never priced against).

Merges into the existing features dict rather than overwriting it — unlike
0015's "canonical" full-overwrite, this migration must not clobber whatever
else has been added to features since (advanced_reports, modules, etc.).
"""
from django.db import migrations

MAX_CONNECTORS_BY_SLUG = {
    "free": 0,
    "professional": 1,
    "professional-annual": 1,
    "business": 3,
    "business-annual": 3,
    "enterprise": 5,
    "enterprise-annual": 5,
}


def apply(apps, schema_editor):
    Plan = apps.get_model("subscriptions", "Plan")
    for slug, max_connectors in MAX_CONNECTORS_BY_SLUG.items():
        for plan in Plan.objects.filter(slug=slug):
            features = dict(plan.features or {})
            features["max_connectors"] = max_connectors
            plan.features = features
            plan.save(update_fields=["features"])


def reverse_migration(apps, schema_editor):
    Plan = apps.get_model("subscriptions", "Plan")
    for slug in MAX_CONNECTORS_BY_SLUG:
        for plan in Plan.objects.filter(slug=slug):
            features = dict(plan.features or {})
            features.pop("max_connectors", None)
            plan.features = features
            plan.save(update_fields=["features"])


class Migration(migrations.Migration):
    dependencies = [
        ("subscriptions", "0024_remove_paymenthistory_payment_history_exactly_one_target_when_settled_and_more"),
    ]

    operations = [
        migrations.RunPython(apply, reverse_migration),
    ]

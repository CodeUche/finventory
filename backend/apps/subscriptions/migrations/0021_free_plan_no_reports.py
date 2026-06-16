"""Remove 'reports' module from the free plan — Reports & Analytics is a paid feature."""
from django.db import migrations


def remove_reports_from_free(apps, schema_editor):
    Plan = apps.get_model("subscriptions", "Plan")
    for plan in Plan.objects.filter(slug="free"):
        features = dict(plan.features)
        modules = list(features.get("modules", []))
        if "reports" in modules:
            modules.remove("reports")
        features["modules"] = modules
        features["advanced_reports"] = False
        plan.features = features
        plan.save(update_fields=["features"])


class Migration(migrations.Migration):
    dependencies = [
        ("subscriptions", "0020_trial_days_30"),
    ]

    operations = [
        migrations.RunPython(remove_reports_from_free, migrations.RunPython.noop),
    ]

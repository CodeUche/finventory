"""
Data migration: delete garbage test plans and reassign their subscriptions to free.
"""
from django.db import migrations


def cleanup_plans(apps, schema_editor):
    Plan = apps.get_model("subscriptions", "Plan")
    Subscription = apps.get_model("subscriptions", "Subscription")

    free_plan = Plan.objects.filter(slug="free").first()
    if not free_plan:
        return

    # Reassign subscriptions on smoke-plan and empty-slug plan to free
    garbage_plans = Plan.objects.filter(slug__in=["smoke-plan", ""])
    if garbage_plans.exists():
        Subscription.objects.filter(plan__in=garbage_plans).update(plan=free_plan)
        garbage_plans.delete()


def reverse_cleanup(apps, schema_editor):
    pass  # irreversible


class Migration(migrations.Migration):
    dependencies = [
        ("subscriptions", "0004_update_plan_modules"),
    ]
    operations = [
        migrations.RunPython(cleanup_plans, reverse_code=reverse_cleanup),
    ]

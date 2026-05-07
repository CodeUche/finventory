"""
Data migration: mark onboarding_completed=True for all organisations that
already have at least one active membership.

Why: migration 0015 added onboarding_completed with default=False, which means
every organisation that existed before 2026-03-25 has onboarding_completed=False.
The OnboardingPage escape hatch (hadOrgAtMount ref) no longer depends on this
field, but setting it correctly prevents any future code from treating these
organisations as incomplete.
"""

from django.db import migrations


def mark_completed(apps, schema_editor):
    Organisation = apps.get_model("tenancy", "Organisation")
    Membership = apps.get_model("tenancy", "Membership")
    # Get org IDs that have at least one active membership
    org_ids_with_members = (
        Membership.objects.filter(is_active=True)
        .values_list("organisation_id", flat=True)
        .distinct()
    )
    updated = Organisation.objects.filter(
        id__in=org_ids_with_members,
        onboarding_completed=False,
    ).update(onboarding_completed=True)
    import logging
    logging.getLogger(__name__).info(
        "tenancy.0022: marked %d organisation(s) as onboarding_completed=True", updated
    )


def unmark(apps, schema_editor):
    pass  # irreversible data migration — not worth reverting


class Migration(migrations.Migration):

    dependencies = [
        ("tenancy", "0021_add_invitation_status"),
    ]

    operations = [
        migrations.RunPython(mark_completed, unmark),
    ]

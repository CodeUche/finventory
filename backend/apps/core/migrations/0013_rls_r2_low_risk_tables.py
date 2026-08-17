"""
R-2 — enable RLS on 11 low-traffic tenant tables.

First batch of the rollout that closes the gap found at runtime: only 60 of
128 tenant-bearing tables had row-level security, so the other 68 relied on
the application layer alone. That layer is sound, but C-1 proved a permission
gap can ship, and RLS is the net underneath it.

These 11 go first because a wrong policy here is visible and recoverable —
support tickets or webhook config appearing empty — rather than financially
damaging. Payroll, payments and tax wait for R-4.

Policy shape is copied verbatim from 0002_enable_rls so every protected table
behaves identically:

    USING       (organisation_id = current_setting('app.current_org_id', TRUE)::uuid)
    WITH CHECK  (same)

Deliberately NOT included:
  tenancy_membership / tenancy_organisation — migrations 0006-0008 disabled RLS
    on these on purpose. Org discovery must read membership BEFORE
    app.current_org_id can be known, so a policy there returned zero rows and
    sent every user to /onboarding. Re-enabling them would break login.
  core_auditlog — organisation_id is a nullable raw UUIDField, and the
    platform-admin view reads rows where it is NULL. The standard policy would
    hide those. Needs its own design (NEW-11).
  accounting_journalline — no organisation column at all; it is scoped through
    its journal entry, so it needs an EXISTS subquery policy (NEW-11).

FORCE ROW LEVEL SECURITY is deliberately not set: the app connects as
audity_app, which owns 7 of 163 tables (none of them RLS-enabled), so policies
already apply to it. Forcing would only break `manage.py migrate`, which runs
as the owner.

Reverting disables RLS and drops the policies. No data is touched either way.
"""

from django.db import migrations

from apps.core.rls_policy import apply_rls, revert_rls

TABLES = [
    "einvoicing_firsconfig",
    "einvoicing_firssubmission",
    "einvoicing_sandboxtestrun",
    "helpdesk_supportticket",
    "helpdesk_ticketcomment",
    "integrations_domainevent",
    "integrations_organisationapikey",
    "integrations_webhookdelivery",
    "integrations_webhooksubscription",
    "inventory_modifiergroup",
    "inventory_modifieroption",
]

LABEL = "core.0013 (R-2)"


class Migration(migrations.Migration):
    atomic = False


    # Every app whose tables this batch touches must have created them first.
    # Without these, Django is free to run this migration before those apps'
    # initial migrations: ALTER TABLE then fails on a table that does not exist
    # yet, the per-table handler logs a warning and continues, and the migration
    # is recorded as applied having protected nothing. That is exactly how
    # migrations 0006/0007 came to be silently no-ops. Verified: 8/68 tables
    # were enabled before these dependencies were added, 68/68 after.
    dependencies = [
        ("core", "0012_rls_r1_accountmapping_index"),
        ("einvoicing", "0003_sandbox_testing"),
        ("helpdesk", "0001_initial"),
        ("integrations", "0002_seed_integration_products"),
        ("inventory", "0011_modifiergroup_modifieroption"),
    ]

    operations = [
        migrations.RunPython(apply_rls(TABLES, LABEL), revert_rls(TABLES, LABEL), atomic=False),
    ]

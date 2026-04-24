"""
Add bootstrap RLS policies to allow org discovery when no X-Organisation-ID
header is present.

Problem
-------
tenancy_membership and tenancy_organisation have RLS policies:

    USING (organisation_id = current_setting('app.current_org_id', TRUE)::uuid)
    USING (id           = current_setting('app.current_org_id', TRUE)::uuid)

When no org header is supplied (Tauri startup, login flow, etc.) RLSMiddleware
sets app.current_org_id to the sentinel '00000000-…' which matches no real row.
This makes the org-list endpoint return an empty list, meaning the frontend can
never learn which org the user belongs to, and all subsequent requests 403.

Fix
---
Add a SECOND, SELECT-only policy on both tables.  In PostgreSQL, permissive
policies are OR-ed together, so the effective USING becomes:

    (organisation_id = current_org_id) OR (current_org_id = SENTINEL)

Under SENTINEL, SELECT is now allowed (org discovery can proceed).
Writes are still governed by WITH CHECK on the original strict policy,
so INSERT/UPDATE under SENTINEL remains blocked — you cannot create or
modify records without an explicit org context.

Security impact
---------------
Under SENTINEL any authenticated DB role (audity_app) can read ALL rows in
these two tables.  However:
* Only authenticated users reach Django views; DRF enforces this before any
  view runs.
* The application layer (OrganisationViewSet, TenantFilterMixin) always adds
  WHERE user_id = %s / WHERE id IN (...) filters — cross-user data is never
  returned by any view.
* Writes under SENTINEL are still blocked, preventing accidental data creation
  without an org context.
* The primary tenant isolation for data tables (products, invoices, etc.) is
  unchanged — only the two meta/bootstrap tables are relaxed.
"""

from django.db import migrations

SENTINEL = "00000000-0000-0000-0000-000000000000"

APPLY = f"""
DO $$
BEGIN
    -- ── tenancy_membership: allow SELECT under SENTINEL for org bootstrap ──
    IF EXISTS (
        SELECT 1 FROM pg_class WHERE relname = 'tenancy_membership'
    ) THEN
        DROP POLICY IF EXISTS membership_bootstrap ON tenancy_membership;
        CREATE POLICY membership_bootstrap ON tenancy_membership
            FOR SELECT
            USING (
                current_setting('app.current_org_id', TRUE) = '{SENTINEL}'
            );
    END IF;

    -- ── tenancy_organisation: allow SELECT under SENTINEL for org discovery ──
    IF EXISTS (
        SELECT 1 FROM pg_class WHERE relname = 'tenancy_organisation'
    ) THEN
        DROP POLICY IF EXISTS org_bootstrap ON tenancy_organisation;
        CREATE POLICY org_bootstrap ON tenancy_organisation
            FOR SELECT
            USING (
                current_setting('app.current_org_id', TRUE) = '{SENTINEL}'
            );
    END IF;
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'core.0004: could not add bootstrap RLS policies (non-fatal): %', SQLERRM;
END $$;
"""

REVERT = """
DO $$
BEGIN
    DROP POLICY IF EXISTS membership_bootstrap ON tenancy_membership;
    DROP POLICY IF EXISTS org_bootstrap ON tenancy_organisation;
EXCEPTION WHEN OTHERS THEN NULL;
END $$;
"""


def apply(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cur:
        cur.execute(APPLY)


def revert(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cur:
        cur.execute(REVERT)


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("core", "0003_rls_db_default"),
    ]

    operations = [
        migrations.RunPython(apply, revert, atomic=False),
    ]

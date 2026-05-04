"""
Completely disable Row Level Security on the two bootstrap tables.

Why this is needed
------------------
Migration 0006 was supposed to run `ALTER TABLE tenancy_membership NO FORCE ROW LEVEL
SECURITY` but it has a `try/except` that silently swallows any failure.  On Railway's
managed PostgreSQL the ALTER may have failed (e.g. the DB user is not the table owner,
or the statement was disallowed), and Django still marked 0006 as applied — so FORCE
RLS is still active on these tables in production.

The symptom is: every login returns "JWT has 0 org(s), API returned 0 org(s)" because
  1. FORCE RLS causes RLS policies to run even for the table owner.
  2. The membership_select policy depends on set_config('app.current_user_id', ...) being
     visible at query time.
  3. set_config() silently fails in some pgBouncer / managed-DB configurations.
  4. Result: 0 rows returned → user has no org → routed to onboarding every login.

Fix
---
This migration aggressively removes ALL RLS enforcement on the two meta/bootstrap tables:
  - NO FORCE ROW LEVEL SECURITY  (retry in case 0006 didn't take)
  - DISABLE ROW SECURITY          (belt-and-suspenders: completely turns off RLS)

Security is maintained by the application layer:
  - OrganisationViewSet.get_queryset() always filters by the requesting user's memberships
  - resolve_organisation() validates membership with an explicit WHERE clause
  - TenantFilterMixin raises 403 if the resolved org doesn't match the X-Organisation-ID header

All business-data tables (products, invoices, stock, payroll, etc.) are NOT touched —
they retain full FORCE ROW LEVEL SECURITY.
"""

from django.db import migrations


def disable_rls(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cur:
        cur.execute("ALTER TABLE tenancy_membership NO FORCE ROW LEVEL SECURITY")
        cur.execute("ALTER TABLE tenancy_membership DISABLE ROW SECURITY")
        cur.execute("ALTER TABLE tenancy_organisation NO FORCE ROW LEVEL SECURITY")
        cur.execute("ALTER TABLE tenancy_organisation DISABLE ROW SECURITY")


def enable_rls(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cur:
        cur.execute("ALTER TABLE tenancy_membership ENABLE ROW LEVEL SECURITY")
        cur.execute("ALTER TABLE tenancy_membership FORCE ROW LEVEL SECURITY")
        cur.execute("ALTER TABLE tenancy_organisation ENABLE ROW LEVEL SECURITY")
        cur.execute("ALTER TABLE tenancy_organisation FORCE ROW LEVEL SECURITY")


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("core", "0006_remove_force_rls_bootstrap_tables"),
    ]

    operations = [
        migrations.RunPython(disable_rls, enable_rls, atomic=False),
    ]

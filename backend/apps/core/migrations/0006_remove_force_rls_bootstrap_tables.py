"""
Remove FORCE ROW LEVEL SECURITY from tenancy_membership and tenancy_organisation.

Problem
-------
Migrations 0004 and 0005 added FORCE ROW LEVEL SECURITY to the two bootstrap
tables so that even the table owner (Railway's single DB role) is subject to
the membership_select / org_select policies.

Those policies use set_config('app.current_user_id', ...) to identify the
requesting user at the DB level during the SENTINEL bootstrap phase (before
any org ID is known).  However, set_config() with is_local=FALSE relies on
the value persisting across statement boundaries within the same PostgreSQL
session.  With connection pooling (including Django's CONN_MAX_AGE) or any
intermediary that rotates backend connections between statements (PgBouncer
transaction mode), this persistence is not guaranteed.  The result: the
second branch of membership_select never matches → empty org list → no
X-Organisation-ID header ever sent → every tenant endpoint returns 403.

Fix
---
Remove FORCE ROW LEVEL SECURITY from the two meta/bootstrap tables so that
the table owner (the Django DB user on Railway's single-role setup) bypasses
RLS on those tables.  The owner can read all memberships/orgs, and the Django
application layer (OrganisationViewSet, resolve_organisation, TenantFilterMixin)
enforces the correct per-user filtering before returning data.

Security impact
---------------
  - ALL business-data tables (products, invoices, payroll, stock, etc.) retain
    their strict FORCE ROW LEVEL SECURITY policies — cross-tenant leakage on
    business data is impossible at the DB level regardless of app bugs.
  - tenancy_membership and tenancy_organisation are meta/auth tables.  Their
    data is already correctly filtered by the application layer:
      * OrganisationViewSet.get_queryset() filters by request.user.memberships
      * resolve_organisation() validates membership with an explicit WHERE clause
      * TenantFilterMixin raises 403 if the resolved org doesn't match the header
  - ENABLE ROW LEVEL SECURITY remains on both tables, so the policies still
    apply to any non-owner DB role (useful for a future two-role deployment).
  - The existing per-operation policies (select/insert/update/delete) are kept
    intact for that two-role scenario.

Two-role production setup (future)
-----------------------------------
If APP_DATABASE_URL is configured to connect as a non-owner role ('audity_app'),
that role IS subject to the RLS policies on these tables.  The membership_select
SENTINEL branch (using app.current_user_id) still applies to it.  Only the
single-role Railway setup is affected by this migration.
"""

from django.db import migrations


def remove_force_rls(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cur:
        # Remove FORCE — table owner now bypasses RLS on bootstrap tables.
        # ENABLE ROW LEVEL SECURITY stays, so policies still protect non-owner roles.
        cur.execute("ALTER TABLE tenancy_membership NO FORCE ROW LEVEL SECURITY")
        cur.execute("ALTER TABLE tenancy_organisation NO FORCE ROW LEVEL SECURITY")


def restore_force_rls(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cur:
        cur.execute("ALTER TABLE tenancy_membership FORCE ROW LEVEL SECURITY")
        cur.execute("ALTER TABLE tenancy_organisation FORCE ROW LEVEL SECURITY")


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("core", "0005_fix_rls_policies"),
    ]

    operations = [
        migrations.RunPython(remove_force_rls, restore_force_rls, atomic=False),
    ]

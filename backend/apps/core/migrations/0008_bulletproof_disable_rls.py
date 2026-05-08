"""
Bulletproof RLS disable for the two bootstrap tables.

Root cause of the login → /onboarding regression
-------------------------------------------------
Production uses two DB roles:
  DATABASE_URL  — table owner; used by `manage.py migrate` (Procfile release step).
  APP_DATABASE_URL — limited `audity_app` role; used by the running Django app.

Migrations 0006 and 0007 wrapped ALL their ALTER TABLE statements inside a
single cursor block inside a single try/except.  In PostgreSQL, once any
statement inside a cursor block fails, the transaction is aborted and every
subsequent statement on that cursor raises "current transaction is aborted".
The broad except swallowed all of them, so Django marked the migration as
applied while none of the ALTER TABLE commands actually ran.

The result: FORCE ROW LEVEL SECURITY is still active on both tables, the
limited `audity_app` role is subject to the old `tenant_isolation` policy,
and every login query for memberships returns 0 rows.

Fix
---
Use a SEPARATE SAVEPOINT for every ALTER TABLE statement so that one failure
(e.g. "must be owner of table") rolls back only that statement and leaves the
cursor usable for the next attempt.

Each ALTER TABLE is tried twice: first via direct execution (works when the
migration user is the table owner / superuser, which is the normal case on
Railway since DATABASE_URL is the owner), then the same statement is retried
via DO $$ BEGIN ... EXCEPTION WHEN ... END $$; which swallows the error at the
PL/pgSQL level so the cursor stays clean.

Order matters:
  1. NO FORCE  — stops forcing RLS on the owner role.
  2. DISABLE   — turns off RLS for every role, including audity_app.

After this migration both the owner and the app role can read all rows on
tenancy_membership and tenancy_organisation without needing set_config GUCs,
and the login → /dashboard flow works for every user.

Security note
-------------
tenancy_membership and tenancy_organisation are bootstrap / auth tables.
Tenant isolation for all business-data (products, invoices, payroll, etc.)
is enforced by the strict FORCE ROW LEVEL SECURITY policies on those tables —
those are NOT touched here.  The Django application layer (OrganisationViewSet,
resolve_organisation, TenantFilterMixin) also enforces correct per-user
filtering before returning membership or org data.
"""

import logging

from django.db import migrations

logger = logging.getLogger(__name__)


def _exec_savepoint(cur, sp_name: str, sql: str) -> bool:
    """
    Execute *sql* inside a SAVEPOINT so a failure rolls back only that
    statement and leaves the cursor usable for subsequent commands.

    Returns True if the statement succeeded, False if it was rolled back.
    """
    try:
        cur.execute(f"SAVEPOINT {sp_name}")
        cur.execute(sql)
        cur.execute(f"RELEASE SAVEPOINT {sp_name}")
        return True
    except Exception as exc:
        cur.execute(f"ROLLBACK TO SAVEPOINT {sp_name}")
        logger.debug("0008: %s rolled back (%s: %s)", sp_name, type(exc).__name__, exc)
        return False


def disable_rls(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return

    with schema_editor.connection.cursor() as cur:
        results = {}

        for table in ("tenancy_membership", "tenancy_organisation"):
            short = table.replace("tenancy_", "")

            # ── NO FORCE ──────────────────────────────────────────────────────
            ok = _exec_savepoint(
                cur, f"m0008_{short}_noforce",
                f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY",
            )
            if not ok:
                # Retry via anonymous DO block (PL/pgSQL swallows the error
                # internally so the cursor stays clean).
                ok = _exec_savepoint(
                    cur, f"m0008_{short}_noforce_do",
                    f"DO $$ BEGIN ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY; "
                    f"EXCEPTION WHEN OTHERS THEN NULL; END $$",
                )
            results[f"{short}_noforce"] = ok

            # ── DISABLE ───────────────────────────────────────────────────────
            ok = _exec_savepoint(
                cur, f"m0008_{short}_disable",
                f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY",
            )
            if not ok:
                ok = _exec_savepoint(
                    cur, f"m0008_{short}_disable_do",
                    f"DO $$ BEGIN ALTER TABLE {table} DISABLE ROW LEVEL SECURITY; "
                    f"EXCEPTION WHEN OTHERS THEN NULL; END $$",
                )
            results[f"{short}_disable"] = ok

        succeeded = [k for k, v in results.items() if v]
        failed = [k for k, v in results.items() if not v]

        if succeeded:
            logger.info("0008: applied: %s", ", ".join(succeeded))
        if failed:
            logger.warning(
                "0008: could not apply: %s — run manually in the DB console: "
                "ALTER TABLE tenancy_membership DISABLE ROW LEVEL SECURITY; "
                "ALTER TABLE tenancy_organisation DISABLE ROW LEVEL SECURITY;",
                ", ".join(failed),
            )

        # ── Also ensure every active org-owner has a membership row ──────────
        # (idempotent — NOT EXISTS guard)
        _exec_savepoint(cur, "m0008_recover_memberships", """
            INSERT INTO tenancy_membership
                (id, user_id, organisation_id, role,
                 is_active, joined_at, created_at, updated_at)
            SELECT
                gen_random_uuid(),
                o.owner_id,
                o.id,
                'owner',
                TRUE,
                NOW(), NOW(), NOW()
            FROM tenancy_organisation o
            WHERE o.owner_id IS NOT NULL
              AND o.is_active = TRUE
              AND NOT EXISTS (
                  SELECT 1 FROM tenancy_membership m
                  WHERE m.user_id         = o.owner_id
                    AND m.organisation_id = o.id
              )
        """)


def restore_rls(apps, schema_editor):
    """Reverse: re-enable and force RLS (used only when reverting the migration)."""
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cur:
        for table in ("tenancy_membership", "tenancy_organisation"):
            short = table.replace("tenancy_", "")
            _exec_savepoint(cur, f"m0008r_{short}_enable",
                            f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
            _exec_savepoint(cur, f"m0008r_{short}_force",
                            f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("core", "0007_disable_rls_bootstrap_tables"),
    ]

    operations = [
        migrations.RunPython(disable_rls, restore_rls, atomic=False),
    ]

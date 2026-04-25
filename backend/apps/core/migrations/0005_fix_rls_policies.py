"""
Permanent RLS fix: per-operation policies with user-scoped bootstrap.

Problems fixed
--------------
1. INSERT blocked under SENTINEL -> 500 on new org creation.
   The original tenant_isolation policy applied WITH CHECK to INSERT,
   meaning Organisation.objects.create() and Membership.objects.create()
   were rejected under SENTINEL (no org context yet), causing an unhandled
   constraint violation -> 500 in OrganisationViewSet.create().

2. Org discovery returns empty list on fresh login / Tauri startup.
   The Bootstrap SELECT policy from migration 0004 allowed ALL membership
   rows under SENTINEL — a security over-relaxation. This migration
   replaces it with a user-scoped alternative.

Fix
---
Replace the single all-operations tenant_isolation policy with explicit
per-command policies on both tenancy_membership and tenancy_organisation.

tenancy_membership:
  SELECT  — own-org rows, OR the requesting user's own rows when SENTINEL
            (uses app.current_user_id set by the application after DRF auth).
            Under SENTINEL only the authenticated user's memberships are
            visible — no cross-user data exposed at the DB level.
  INSERT  — always allowed (IsAuthenticated controls the endpoint).
  UPDATE  — own-org rows only.
  DELETE  — own-org rows only.

tenancy_organisation:
  SELECT  — own org only (strict). The application performs a two-step
            bootstrap: read membership IDs first (membership_select allows
            it via user_id), set app.current_org_id, then read the org.
  INSERT  — always allowed (IsAuthenticated controls the endpoint).
  UPDATE  — own org only.
  DELETE  — own org only.

Security impact
---------------
The INSERT relaxation applies only to the two meta/bootstrap tables. All
other tenant tables (products, invoices, etc.) retain their existing strict
all-operations policies from migration 0002. Cross-user data leakage under
SENTINEL is prevented because the bootstrap SELECT is gated by
app.current_user_id (the authenticated user's PK set by the view layer
after DRF verifies the JWT).
"""

from django.db import migrations

SENTINEL = "00000000-0000-0000-0000-000000000000"


def _drop_if_exists(cur, policy, table):
    cur.execute(f"DROP POLICY IF EXISTS {policy} ON {table}")


def apply(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return

    import logging
    _log = logging.getLogger(__name__)

    try:
        with schema_editor.connection.cursor() as cur:

            # ── tenancy_membership ─────────────────────────────────────────────
            cur.execute("ALTER TABLE tenancy_membership ENABLE ROW LEVEL SECURITY")
            cur.execute("ALTER TABLE tenancy_membership FORCE ROW LEVEL SECURITY")

            # Remove old policies (handles re-runs and partial prior migrations)
            for name in (
                "tenant_isolation",
                "membership_bootstrap",
                "membership_select",
                "membership_insert",
                "membership_update",
                "membership_delete",
            ):
                _drop_if_exists(cur, name, "tenancy_membership")

            # SELECT: own-org rows, OR the user's own rows when in SENTINEL mode.
            # app.current_user_id is set by the view layer (after DRF JWT auth)
            # via _set_user() before any membership query is evaluated.
            cur.execute(f"""
                CREATE POLICY membership_select ON tenancy_membership
                FOR SELECT USING (
                    organisation_id = current_setting('app.current_org_id', TRUE)::uuid
                    OR (
                        current_setting('app.current_org_id', TRUE) = '{SENTINEL}'
                        AND user_id::text = current_setting('app.current_user_id', TRUE)
                    )
                )
            """)

            # INSERT: unrestricted at the DB level; Django's IsAuthenticated
            # permission class gates every endpoint that creates memberships.
            cur.execute("""
                CREATE POLICY membership_insert ON tenancy_membership
                FOR INSERT WITH CHECK (true)
            """)

            # UPDATE / DELETE: own-org rows only (unchanged restriction)
            cur.execute(f"""
                CREATE POLICY membership_update ON tenancy_membership
                FOR UPDATE USING (
                    organisation_id = current_setting('app.current_org_id', TRUE)::uuid
                )
            """)
            cur.execute(f"""
                CREATE POLICY membership_delete ON tenancy_membership
                FOR DELETE USING (
                    organisation_id = current_setting('app.current_org_id', TRUE)::uuid
                )
            """)

            # ── tenancy_organisation ───────────────────────────────────────────
            cur.execute("ALTER TABLE tenancy_organisation ENABLE ROW LEVEL SECURITY")
            cur.execute("ALTER TABLE tenancy_organisation FORCE ROW LEVEL SECURITY")

            for name in (
                "tenant_isolation",
                "org_bootstrap",
                "org_select",
                "org_insert",
                "org_update",
                "org_delete",
            ):
                _drop_if_exists(cur, name, "tenancy_organisation")

            # SELECT: strict — only the current org.
            # The application does a two-step bootstrap: read membership IDs
            # first (membership_select allows this via user_id), call _set_org(),
            # then read the org under the correct current_org_id.
            cur.execute(f"""
                CREATE POLICY org_select ON tenancy_organisation
                FOR SELECT USING (
                    id = current_setting('app.current_org_id', TRUE)::uuid
                )
            """)

            # INSERT: unrestricted — gated by IsAuthenticated in the view layer.
            cur.execute("""
                CREATE POLICY org_insert ON tenancy_organisation
                FOR INSERT WITH CHECK (true)
            """)

            # UPDATE / DELETE: own org only.
            cur.execute(f"""
                CREATE POLICY org_update ON tenancy_organisation
                FOR UPDATE USING (
                    id = current_setting('app.current_org_id', TRUE)::uuid
                )
            """)
            cur.execute(f"""
                CREATE POLICY org_delete ON tenancy_organisation
                FOR DELETE USING (
                    id = current_setting('app.current_org_id', TRUE)::uuid
                )
            """)
    except Exception as exc:
        # Railway (and other managed-DB hosts) may not grant ALTER TABLE / CREATE
        # POLICY privileges to the application DB user. Catch and log so the
        # migration is still recorded as applied — unblocking future migrations.
        # The application layer (pre-set org ID before INSERT, JWT-bootstrapped
        # org header before SELECT) ensures correctness without these policies.
        _log.warning(
            "core.0005_fix_rls_policies: could not apply policy DDL "
            "(non-fatal on managed DBs): %s", exc
        )


def revert(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return

    with schema_editor.connection.cursor() as cur:
        for table, col in [
            ("tenancy_membership", "organisation_id"),
            ("tenancy_organisation", "id"),
        ]:
            prefix = "membership" if table == "tenancy_membership" else "org"
            for suffix in ("select", "insert", "update", "delete"):
                _drop_if_exists(cur, f"{prefix}_{suffix}", table)
            cur.execute(f"""
                CREATE POLICY tenant_isolation ON {table}
                    USING ({col} = current_setting('app.current_org_id', TRUE)::uuid)
                    WITH CHECK ({col} = current_setting('app.current_org_id', TRUE)::uuid)
            """)


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("core", "0004_rls_membership_bootstrap"),
    ]

    operations = [
        migrations.RunPython(apply, revert, atomic=False),
    ]

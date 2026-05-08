"""
Data recovery migration: recreate missing OWNER membership rows.

Root cause of onboarding redirect regression:
    The tenancy_membership table on Railway has 0 rows — every existing
    user therefore looks like a new user and gets routed to /onboarding.

    Every Organisation has an `owner` FK that survived.  We recreate the
    missing Membership rows from that field.

RLS handling — Django migrations run inside a PostgreSQL transaction.
Each attempt uses a SAVEPOINT so a failed attempt rolls back without
aborting the outer transaction (which would make all subsequent
commands fail with "current transaction is aborted").

  Attempt 1: SET LOCAL row_security = OFF — SAVEPOINT protects the
             outer transaction when this raises ProgrammingError on
             managed PostgreSQL hosts (user is not table owner).
  Attempt 2: SENTINEL GUC — SAVEPOINT protects against any SQL error.
             Sets app.current_org_id = SENTINEL + app.current_user_id
             = SENTINEL so RLS policies that have a SENTINEL exception
             allow the SELECT.  Inserts 0 rows if the org_select policy
             has no SENTINEL exception (strict: id = current_org_id).
  Attempt 3: ORM get_or_create fallback — works on SQLite (tests) and
             when RLS has been disabled on the tables.

This migration is idempotent: the NOT EXISTS guard and get_or_create
semantics mean re-running it is safe.

NOTE: If all three attempts insert 0 rows (because RLS on
tenancy_organisation blocks the SELECT without knowing org UUIDs),
run the following in Railway's PostgreSQL dashboard as a privileged
user to complete the fix manually:

    ALTER TABLE tenancy_membership DISABLE ROW SECURITY;
    ALTER TABLE tenancy_organisation DISABLE ROW SECURITY;

    INSERT INTO tenancy_membership
        (id, user_id, organisation_id, role,
         is_active, joined_at, created_at, updated_at)
    SELECT gen_random_uuid(), o.owner_id, o.id, 'owner',
           TRUE, NOW(), NOW(), NOW()
    FROM   tenancy_organisation o
    WHERE  o.owner_id IS NOT NULL
      AND  o.is_active = TRUE
      AND  NOT EXISTS (
               SELECT 1 FROM tenancy_membership m
               WHERE  m.user_id = o.owner_id
                 AND  m.organisation_id = o.id
           );
"""

import logging

from django.db import migrations
from django.utils import timezone

logger = logging.getLogger(__name__)

_SENTINEL = "00000000-0000-0000-0000-000000000000"

_INSERT_SQL = """
    INSERT INTO tenancy_membership
        (id, user_id, organisation_id, role,
         is_active, joined_at, created_at, updated_at)
    SELECT
        gen_random_uuid(),
        o.owner_id,
        o.id,
        'owner',
        TRUE,
        %s, %s, %s
    FROM tenancy_organisation o
    WHERE
        o.owner_id IS NOT NULL
        AND o.is_active = TRUE
        AND NOT EXISTS (
            SELECT 1 FROM tenancy_membership m
            WHERE m.user_id         = o.owner_id
              AND m.organisation_id = o.id
        )
"""


def recover_memberships(apps, schema_editor):
    db = schema_editor.connection

    # Skip raw-SQL paths on SQLite (tests) — go straight to ORM.
    if db.vendor != "postgresql":
        _recover_orm(apps)
        return

    now = timezone.now().isoformat()

    # All three SQL attempts share ONE cursor so they share the migration's
    # outer transaction.  SAVEPOINTs let us recover from individual SQL errors
    # without aborting that transaction (a bare exception would leave the
    # transaction in "aborted" state, making every subsequent command fail).
    with db.cursor() as cur:

        # ── Attempt 1: bypass RLS entirely ────────────────────────────────
        # Requires BYPASSRLS or superuser; raises ProgrammingError on Railway.
        # SAVEPOINT ensures the outer transaction survives the failure.
        try:
            cur.execute("SAVEPOINT m0023_a1")
            cur.execute("SET LOCAL row_security = OFF")
            cur.execute(_INSERT_SQL, [now, now, now])
            inserted = cur.rowcount
            cur.execute("RELEASE SAVEPOINT m0023_a1")
            logger.info("0023 (rls_bypass): inserted %d membership(s)", inserted)
            return
        except Exception as exc:
            cur.execute("ROLLBACK TO SAVEPOINT m0023_a1")
            logger.debug(
                "0023: rls bypass unavailable (%s), trying SENTINEL GUC",
                type(exc).__name__,
            )

        # ── Attempt 2: SENTINEL GUC ────────────────────────────────────────
        # Sets both current_org_id = SENTINEL and current_user_id = SENTINEL
        # so RLS policies with a SENTINEL exception allow bootstrap reads.
        # Note: org_select has no SENTINEL exception (strict: id = org_id),
        # so the INSERT-SELECT will return 0 rows if that policy is active.
        # The SAVEPOINT still prevents any SQL error from aborting the txn.
        try:
            cur.execute("SAVEPOINT m0023_a2")
            cur.execute(
                "SELECT set_config('app.current_org_id', %s, TRUE)", [_SENTINEL]
            )
            cur.execute(
                "SELECT set_config('app.current_user_id', %s, TRUE)", [_SENTINEL]
            )
            cur.execute(_INSERT_SQL, [now, now, now])
            inserted = cur.rowcount
            cur.execute("RELEASE SAVEPOINT m0023_a2")
            logger.info("0023 (sentinel_guc): inserted %d membership(s)", inserted)
            return
        except Exception as exc:
            cur.execute("ROLLBACK TO SAVEPOINT m0023_a2")
            logger.warning(
                "0023: SENTINEL GUC failed (%s: %s), trying ORM fallback",
                type(exc).__name__, exc,
            )

    # ── Attempt 3: ORM fallback ────────────────────────────────────────────
    # Works on SQLite and when RLS has been disabled on the tables.
    # On Railway with active org_select RLS, Organisation.objects.filter()
    # returns 0 rows (filtered silently), so 0 memberships are inserted.
    _recover_orm(apps)


def _recover_orm(apps):
    """ORM fallback — works on SQLite and when RLS is disabled."""
    Organisation = apps.get_model("tenancy", "Organisation")
    Membership = apps.get_model("tenancy", "Membership")
    now = timezone.now()
    count = 0
    for org in Organisation.objects.filter(is_active=True):
        if not org.owner_id:
            continue
        _, created = Membership.objects.get_or_create(
            user_id=org.owner_id,
            organisation=org,
            defaults={
                "role": "owner",
                "is_active": True,
                "joined_at": now,
            },
        )
        if created:
            count += 1
    logger.info("0023 (orm_fallback): inserted %d membership(s)", count)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("tenancy", "0022_mark_onboarding_completed"),
    ]

    operations = [
        migrations.RunPython(recover_memberships, noop),
    ]

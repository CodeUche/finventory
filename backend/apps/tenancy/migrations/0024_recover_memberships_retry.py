"""
Second membership-recovery pass: runs after 0023 and after RLS is disabled.

Migration 0023 inserts 0 rows on Railway because the org_select RLS policy
(id = current_setting('app.current_org_id')::uuid) blocks the INSERT-SELECT
from tenancy_organisation — we cannot read any org row without already knowing
its UUID.

The permanent fix requires disabling RLS on the two bootstrap tables from
Railway's PostgreSQL dashboard (Data tab) as a privileged user:

    ALTER TABLE tenancy_membership  DISABLE ROW SECURITY;
    ALTER TABLE tenancy_organisation DISABLE ROW SECURITY;

Once that is done, deploy again.  This migration (0024) will then run and
use the ORM to iterate all orgs and create any missing owner memberships.

The migration is idempotent — get_or_create means re-running it is safe.
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


def recover_memberships_retry(apps, schema_editor):
    db = schema_editor.connection
    now = timezone.now().isoformat()

    if db.vendor == "postgresql":
        with db.cursor() as cur:
            # Attempt 1: RLS bypass
            try:
                cur.execute("SAVEPOINT m0024_a1")
                cur.execute("SET LOCAL row_security = OFF")
                cur.execute(_INSERT_SQL, [now, now, now])
                n = cur.rowcount
                cur.execute("RELEASE SAVEPOINT m0024_a1")
                logger.info("0024 (rls_bypass): inserted %d membership(s)", n)
                if n > 0:
                    return
            except Exception as exc:
                cur.execute("ROLLBACK TO SAVEPOINT m0024_a1")
                logger.debug("0024: rls bypass failed (%s)", type(exc).__name__)

            # Attempt 2: SENTINEL GUC
            try:
                cur.execute("SAVEPOINT m0024_a2")
                cur.execute(
                    "SELECT set_config('app.current_org_id', %s, TRUE)", [_SENTINEL]
                )
                cur.execute(
                    "SELECT set_config('app.current_user_id', %s, TRUE)", [_SENTINEL]
                )
                cur.execute(_INSERT_SQL, [now, now, now])
                n = cur.rowcount
                cur.execute("RELEASE SAVEPOINT m0024_a2")
                logger.info("0024 (sentinel_guc): inserted %d membership(s)", n)
                if n > 0:
                    return
            except Exception as exc:
                cur.execute("ROLLBACK TO SAVEPOINT m0024_a2")
                logger.warning("0024: SENTINEL GUC failed (%s)", type(exc).__name__)

    # ORM fallback — works when RLS is disabled or on SQLite
    Organisation = apps.get_model("tenancy", "Organisation")
    Membership = apps.get_model("tenancy", "Membership")
    now_dt = timezone.now()
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
                "joined_at": now_dt,
            },
        )
        if created:
            count += 1
    logger.info("0024 (orm_fallback): inserted %d membership(s)", count)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("tenancy", "0023_recover_owner_memberships"),
    ]

    operations = [
        migrations.RunPython(recover_memberships_retry, noop),
    ]

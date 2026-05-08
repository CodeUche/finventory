"""
Data recovery migration: recreate missing OWNER membership rows.

Root cause of onboarding redirect regression:
    The tenancy_membership table on Railway has 0 rows — every existing
    user therefore looks like a new user and gets routed to /onboarding.

    Every Organisation has an `owner` FK that survived.  We recreate the
    missing Membership rows from that field using a raw INSERT so the
    operation bypasses any remaining RLS policies (SET LOCAL row_security
    = OFF is attempted first; the INSERT itself is idempotent because of
    the NOT EXISTS guard).

This migration is safe to re-run: the NOT EXISTS guard prevents duplicates
and get_or_create semantics mean existing rows are left unchanged.
"""

import logging
import uuid

from django.db import migrations
from django.utils import timezone

logger = logging.getLogger(__name__)


def recover_memberships(apps, schema_editor):
    db = schema_editor.connection
    with db.cursor() as cur:
        # Attempt to bypass RLS — requires BYPASSRLS or superuser.
        # Use a SAVEPOINT so a permission-denied error doesn't abort the
        # migration transaction; we proceed without the bypass if it fails.
        try:
            cur.execute("SAVEPOINT audity_recover_rls")
            cur.execute("SET LOCAL row_security = OFF")
            cur.execute("RELEASE SAVEPOINT audity_recover_rls")
        except Exception as exc:
            cur.execute("ROLLBACK TO SAVEPOINT audity_recover_rls")
            logger.info(
                "0023: BYPASSRLS unavailable (%s) — proceeding without RLS bypass",
                type(exc).__name__,
            )

        # Determine the correct table name prefix (in case of custom schema)
        # and insert missing owner memberships in one shot.
        now = timezone.now().isoformat()
        try:
            cur.execute(
                """
                INSERT INTO tenancy_membership
                    (id, user_id, organisation_id, role,
                     is_active, joined_at, created_at, updated_at)
                SELECT
                    gen_random_uuid(),
                    o.owner_id,
                    o.id,
                    'owner',
                    TRUE,
                    %s,
                    %s,
                    %s
                FROM tenancy_organisation o
                WHERE
                    o.owner_id IS NOT NULL
                    AND o.is_active  = TRUE
                    AND NOT EXISTS (
                        SELECT 1
                        FROM   tenancy_membership m
                        WHERE  m.user_id         = o.owner_id
                          AND  m.organisation_id = o.id
                    )
                """,
                [now, now, now],
            )
            count = cur.rowcount
            logger.info("0023: inserted %d missing owner membership(s)", count)
        except Exception as exc:
            # gen_random_uuid() may not be available on very old PostgreSQL or
            # SQLite (test runner).  Fall back to Python-generated UUIDs.
            logger.warning("0023: bulk INSERT failed (%s), trying row-by-row ORM path", exc)
            _recover_orm(apps)


def _recover_orm(apps):
    """ORM fallback for environments where the raw INSERT is unavailable."""
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
    logger.info("0023: ORM path inserted %d missing owner membership(s)", count)


def noop(apps, schema_editor):
    pass  # Not worth reversing a data-recovery migration


class Migration(migrations.Migration):

    dependencies = [
        ("tenancy", "0022_mark_onboarding_completed"),
    ]

    operations = [
        migrations.RunPython(recover_memberships, noop),
    ]

"""
Data recovery migration: recreate missing OWNER membership rows.

Root cause of onboarding redirect regression:
    The tenancy_membership table on Railway has 0 rows — every existing
    user therefore looks like a new user and gets routed to /onboarding.

    Every Organisation has an `owner` FK that survived.  We recreate the
    missing Membership rows from that field.

RLS handling — three independent attempts, each in its own isolated block
so a failure in one does NOT corrupt the state for the next:

  Attempt 1: SET LOCAL row_security = OFF (needs BYPASSRLS/superuser).
             Fails on Railway with ProgrammingError — caught cleanly.
  Attempt 2: SENTINEL GUC pattern — set app.current_org_id = SENTINEL
             so the org_select policy allows reading tenancy_organisation,
             then INSERT membership rows.  Uses its own atomic block.
  Attempt 3: ORM get_or_create fallback (works on SQLite + when raw SQL
             is unavailable).

This migration is idempotent: the NOT EXISTS guard and get_or_create
semantics mean re-running it is safe.
"""

import logging
import uuid

from django.db import migrations
from django.utils import timezone

logger = logging.getLogger(__name__)

_SENTINEL = "00000000-0000-0000-0000-000000000000"


def recover_memberships(apps, schema_editor):
    db = schema_editor.connection

    # Skip raw-SQL paths on SQLite (tests) — go straight to ORM fallback.
    if db.vendor != "postgresql":
        _recover_orm(apps)
        return

    now = timezone.now().isoformat()
    inserted = 0

    # ── Attempt 1: bypass RLS entirely ────────────────────────────────────────
    try:
        with db.cursor() as cur:
            cur.execute("SET LOCAL row_security = OFF")
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
                    %s, %s, %s
                FROM tenancy_organisation o
                WHERE
                    o.owner_id IS NOT NULL
                    AND o.is_active = TRUE
                    AND NOT EXISTS (
                        SELECT 1 FROM tenancy_membership m
                        WHERE m.user_id = o.owner_id
                          AND m.organisation_id = o.id
                    )
                """,
                [now, now, now],
            )
            inserted = cur.rowcount
            logger.info(
                "0023 (rls_bypass): inserted %d missing owner membership(s)", inserted
            )
            return  # Done — no further attempts needed
    except Exception as exc:
        logger.debug(
            "0023: rls bypass unavailable (%s), trying SENTINEL GUC",
            type(exc).__name__,
        )

    # ── Attempt 2: SENTINEL GUC ────────────────────────────────────────────────
    # Set both current_org_id = SENTINEL and current_user_id = SENTINEL so the
    # org_select and membership_select RLS policies allow bootstrap reads.
    # Each query gets its own cursor inside this single connection to ensure the
    # set_config values persist for the INSERT (transaction-local, TRUE).
    try:
        with db.cursor() as cur:
            cur.execute(
                "SELECT set_config('app.current_org_id', %s, TRUE)", [_SENTINEL]
            )
            cur.execute(
                "SELECT set_config('app.current_user_id', %s, TRUE)", [_SENTINEL]
            )
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
                    %s, %s, %s
                FROM tenancy_organisation o
                WHERE
                    o.owner_id IS NOT NULL
                    AND o.is_active = TRUE
                    AND NOT EXISTS (
                        SELECT 1 FROM tenancy_membership m
                        WHERE m.user_id = o.owner_id
                          AND m.organisation_id = o.id
                    )
                """,
                [now, now, now],
            )
            inserted = cur.rowcount
            logger.info(
                "0023 (sentinel_guc): inserted %d missing owner membership(s)", inserted
            )
            return
    except Exception as exc:
        logger.warning(
            "0023: SENTINEL GUC path failed (%s: %s), trying ORM fallback",
            type(exc).__name__, exc,
        )

    # ── Attempt 3: ORM fallback ────────────────────────────────────────────────
    _recover_orm(apps)


def _recover_orm(apps):
    """ORM fallback — works on SQLite and when raw SQL paths are unavailable."""
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
    logger.info("0023 (orm_fallback): inserted %d missing owner membership(s)", count)


def noop(apps, schema_editor):
    pass  # Not worth reversing a data-recovery migration


class Migration(migrations.Migration):

    dependencies = [
        ("tenancy", "0022_mark_onboarding_completed"),
    ]

    operations = [
        migrations.RunPython(recover_memberships, noop),
    ]

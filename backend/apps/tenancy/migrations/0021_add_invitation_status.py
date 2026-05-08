"""
Add is_rejected and module_permissions columns to tenancy_invitation.

Uses SAVEPOINT-protected raw SQL so an InsufficientPrivilege error
(Railway's DB user may not be the table owner) does not abort the
migration transaction.  Each column gets its own SAVEPOINT so one
failure doesn't block the other.

Django's model state is updated unconditionally via SeparateDatabaseAndState
so the ORM always knows about the fields regardless of whether the ALTER
TABLE succeeded.

NOTE: plain ALTER TABLE ADD COLUMN (no IF NOT EXISTS) is used for
SQLite compatibility — IF NOT EXISTS in ADD COLUMN is PostgreSQL-only.
Duplicate-column errors are caught and treated as a no-op.

If the ALTER TABLE is skipped (privilege denied on Railway), add manually:
    ALTER TABLE tenancy_invitation
        ADD COLUMN is_rejected boolean NOT NULL DEFAULT false;
    ALTER TABLE tenancy_invitation
        ADD COLUMN module_permissions jsonb NOT NULL DEFAULT '{}';
"""

import logging

from django.db import migrations, models

logger = logging.getLogger(__name__)


def add_invitation_columns(apps, schema_editor):
    db = schema_editor.connection
    vendor = db.vendor  # 'postgresql', 'sqlite', etc.

    # jsonb is PostgreSQL-specific; SQLite uses TEXT (Django maps JSONField to TEXT on SQLite)
    if vendor == "postgresql":
        columns = [
            ("is_rejected",        "boolean NOT NULL DEFAULT false"),
            ("module_permissions", "jsonb NOT NULL DEFAULT '{}'"),
        ]
    else:
        columns = [
            ("is_rejected",        "boolean NOT NULL DEFAULT 0"),
            ("module_permissions", "text NOT NULL DEFAULT '{}'"),
        ]

    with db.cursor() as cur:
        for col, defn in columns:
            sp = f"m0021_{col}"
            try:
                cur.execute(f"SAVEPOINT {sp}")
                cur.execute(
                    f"ALTER TABLE tenancy_invitation ADD COLUMN {col} {defn}"
                )
                cur.execute(f"RELEASE SAVEPOINT {sp}")
                logger.info("0021: added column tenancy_invitation.%s", col)
            except Exception as exc:
                cur.execute(f"ROLLBACK TO SAVEPOINT {sp}")
                err = str(exc).lower()
                if "duplicate column" in err or "already exists" in err:
                    # Column was added by a previous (failed+retried) migration run
                    logger.info("0021: tenancy_invitation.%s already exists, skipping", col)
                else:
                    # InsufficientPrivilege on Railway or similar — log and continue.
                    # The column must be added manually if it is genuinely missing.
                    logger.warning(
                        "0021: skipped tenancy_invitation.%s (%s: %s) — "
                        "add manually if column is missing",
                        col, type(exc).__name__, exc,
                    )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('tenancy', '0020_alter_organisation_entity_group_name'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            # Django model-state update: always applied so ORM knows the fields.
            state_operations=[
                migrations.AddField(
                    model_name='invitation',
                    name='is_rejected',
                    field=models.BooleanField(default=False),
                ),
                migrations.AddField(
                    model_name='invitation',
                    name='module_permissions',
                    field=models.JSONField(
                        blank=True,
                        default=dict,
                        help_text=(
                            'Optional per-module access overrides: '
                            '{"sales": "edit", "reports": "view", ...}'
                        ),
                    ),
                ),
            ],
            # Actual DDL: privilege-safe via SAVEPOINT, SQLite-compatible.
            database_operations=[
                migrations.RunPython(add_invitation_columns, noop),
            ],
        ),
    ]

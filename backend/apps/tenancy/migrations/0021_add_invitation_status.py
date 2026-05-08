"""
Add is_rejected and module_permissions columns to tenancy_invitation.

Uses SAVEPOINT-protected raw SQL so an InsufficientPrivilege error
(Railway's DB user may not be the table owner) does not abort the
migration transaction.  Django's model state is updated unconditionally
via SeparateDatabaseAndState so the ORM always knows about the fields.

If the ALTER TABLE is skipped (privilege denied), the columns must be
added manually via the Railway Postgres console:
    ALTER TABLE tenancy_invitation
        ADD COLUMN IF NOT EXISTS is_rejected boolean NOT NULL DEFAULT false;
    ALTER TABLE tenancy_invitation
        ADD COLUMN IF NOT EXISTS module_permissions jsonb NOT NULL DEFAULT '{}';
"""

import logging

from django.db import migrations, models

logger = logging.getLogger(__name__)


def add_invitation_columns(apps, schema_editor):
    db = schema_editor.connection
    columns = [
        ("is_rejected",        "boolean NOT NULL DEFAULT false"),
        ("module_permissions", "jsonb NOT NULL DEFAULT '{}'"),
    ]
    with db.cursor() as cur:
        for col, defn in columns:
            sp = f"m0021_{col}"
            try:
                cur.execute(f"SAVEPOINT {sp}")
                cur.execute(
                    f"ALTER TABLE tenancy_invitation"
                    f" ADD COLUMN IF NOT EXISTS {col} {defn}"
                )
                cur.execute(f"RELEASE SAVEPOINT {sp}")
                logger.info("0021: added column tenancy_invitation.%s", col)
            except Exception as exc:
                cur.execute(f"ROLLBACK TO SAVEPOINT {sp}")
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
            # Actual DDL: privilege-safe via SAVEPOINT.
            database_operations=[
                migrations.RunPython(add_invitation_columns, noop),
            ],
        ),
    ]

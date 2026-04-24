"""
Security hardening: token_version + encrypted MFA fields.

SeparateDatabaseAndState keeps Django's migration state correct (so
dependent migrations compile) while the actual DDL is applied via a
PL/pgSQL block that:
  - skips token_version if the column already exists (manual add)
  - skips mfa_secret widening if the column is already TEXT
  - catches InsufficientPrivilege silently (managed DBs without ALTER)
"""

import apps.core.fields
from django.db import migrations, models


def _apply_schema_changes(apps, schema_editor):
    import logging
    log = logging.getLogger(__name__)

    if schema_editor.connection.vendor == "postgresql":
        try:
            with schema_editor.connection.cursor() as cursor:
                cursor.execute("""
                    DO $$
                    BEGIN
                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'authentication_user'
                              AND column_name = 'token_version'
                        ) THEN
                            ALTER TABLE authentication_user
                                ADD COLUMN token_version integer NOT NULL DEFAULT 0;
                        END IF;

                        IF (SELECT data_type FROM information_schema.columns
                            WHERE table_name = 'authentication_user'
                              AND column_name = 'mfa_secret') <> 'text' THEN
                            ALTER TABLE authentication_user
                                ALTER COLUMN mfa_secret TYPE text;
                        END IF;

                        IF (SELECT data_type FROM information_schema.columns
                            WHERE table_name = 'authentication_user'
                              AND column_name = 'mfa_secret_pending') <> 'text' THEN
                            ALTER TABLE authentication_user
                                ALTER COLUMN mfa_secret_pending TYPE text;
                        END IF;
                    EXCEPTION
                        WHEN insufficient_privilege THEN
                            RAISE NOTICE 'auth.0006: insufficient privilege — DDL skipped';
                        WHEN OTHERS THEN
                            RAISE NOTICE 'auth.0006: DDL skipped: %', SQLERRM;
                    END $$;
                """)
        except Exception as exc:
            log.warning("auth.0006: schema changes skipped: %s", exc)
    else:
        # SQLite / other backends (used in tests): add the column directly.
        # Ignore "duplicate column name" in case of re-runs.
        try:
            with schema_editor.connection.cursor() as cursor:
                cursor.execute(
                    "ALTER TABLE authentication_user"
                    " ADD COLUMN token_version integer NOT NULL DEFAULT 0"
                )
        except Exception:
            pass


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("authentication", "0005_user_must_change_password"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.AddField(
                    model_name="user",
                    name="token_version",
                    field=models.PositiveIntegerField(default=0),
                ),
                migrations.AlterField(
                    model_name="user",
                    name="mfa_secret",
                    field=apps.core.fields.EncryptedCharField(
                        blank=True, default="", max_length=500
                    ),
                ),
                migrations.AlterField(
                    model_name="user",
                    name="mfa_secret_pending",
                    field=apps.core.fields.EncryptedCharField(
                        blank=True, default="", max_length=500
                    ),
                ),
            ],
        ),
        migrations.RunPython(
            _apply_schema_changes,
            migrations.RunPython.noop,
            atomic=False,
        ),
    ]

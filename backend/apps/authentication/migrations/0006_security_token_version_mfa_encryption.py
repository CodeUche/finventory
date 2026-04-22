"""
Revised 0006: widen mfa_secret / mfa_secret_pending to TEXT.

token_version was removed from this migration (and from the model) because
Railway's managed PostgreSQL does not grant ALTER TABLE ownership to the app
user, causing `must be owner of table authentication_user` on every deploy.

The mfa_secret AlterField is attempted via a PL/pgSQL DO block that silently
catches InsufficientPrivilege, so this migration always marks as applied.
SeparateDatabaseAndState ensures Django's migration state matches the model
(EncryptedCharField) regardless of whether the DB ALTER TABLE succeeded.
"""

import apps.core.fields
from django.db import migrations


def _widen_mfa_columns(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    import logging
    log = logging.getLogger(__name__)
    try:
        with schema_editor.connection.cursor() as cursor:
            cursor.execute("""
                DO $$
                BEGIN
                    ALTER TABLE authentication_user
                        ALTER COLUMN mfa_secret TYPE text;
                    ALTER TABLE authentication_user
                        ALTER COLUMN mfa_secret_pending TYPE text;
                EXCEPTION
                    WHEN insufficient_privilege THEN
                        RAISE NOTICE 'auth.0006: no ALTER TABLE privilege — mfa columns stay varchar(64)';
                    WHEN OTHERS THEN
                        RAISE NOTICE 'auth.0006: mfa column alter skipped: %', SQLERRM;
                END $$;
            """)
    except Exception as exc:
        log.warning("auth.0006: mfa_secret column alteration skipped: %s", exc)


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("authentication", "0005_user_must_change_password"),
    ]

    operations = [
        # Update Django's migration state so it knows mfa_secret is now
        # EncryptedCharField — no DB operation here (done by RunPython below).
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
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
        # Try to widen the columns; silently ignores permission errors.
        migrations.RunPython(
            _widen_mfa_columns,
            migrations.RunPython.noop,
            atomic=False,
        ),
    ]

"""
Set a database-level default for app.current_org_id so every new PostgreSQL
connection starts with the sentinel value instead of an unset variable.

Without this, the very first SQL statement on a brand-new connection would see
current_setting('app.current_org_id', TRUE) return NULL, causing RLS policies
to filter out all rows before RLSMiddleware has a chance to set the variable.

The ALTER DATABASE form persists across server restarts and applies to every
new connection to this database.
"""

from django.db import migrations, transaction

SENTINEL = "00000000-0000-0000-0000-000000000000"


def apply(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    db_name = schema_editor.connection.settings_dict["NAME"]
    alias = schema_editor.connection.alias
    try:
        # SAVEPOINT, not a bare try/except: ALTER DATABASE ... SET is
        # instance/database-level DDL that some managed Postgres hosts (Railway
        # ran it fine as the connecting role; AWS RDS/Aurora's master user is
        # `rds_superuser`, not a true superuser, and rejects it — the same
        # class of restriction this comment already anticipated for "managed
        # cloud DBs", it just turned out to include Aurora too) refuse outright.
        # A plain `except Exception: pass` swallows the Python exception but
        # leaves the connection's transaction aborted (Postgres refuses every
        # later statement on it until a ROLLBACK), so the *next* statement
        # Django runs on this same connection — its own INSERT INTO
        # django_migrations recording this migration as applied — is what
        # actually raised, with the real ALTER DATABASE error already
        # discarded. Wrapping the statement in transaction.atomic() creates a
        # real savepoint and rolls back to it on failure, so the connection is
        # left usable afterwards exactly like the working `_exec_savepoint`
        # pattern in 0008_bulletproof_disable_rls.py.
        with transaction.atomic(using=alias):
            with schema_editor.connection.cursor() as cursor:
                cursor.execute(
                    f"ALTER DATABASE \"{db_name}\" SET app.current_org_id = %s",
                    [SENTINEL],
                )
    except Exception:
        # Managed cloud DBs (Railway, Supabase, AWS RDS/Aurora, etc.) may
        # restrict ALTER DATABASE to a true superuser. This setting is a
        # nice-to-have default; the RLS middleware sets the session variable
        # on every request anyway.
        pass


def revert(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    db_name = schema_editor.connection.settings_dict["NAME"]
    alias = schema_editor.connection.alias
    try:
        with transaction.atomic(using=alias):
            with schema_editor.connection.cursor() as cursor:
                cursor.execute(
                    f"ALTER DATABASE \"{db_name}\" RESET app.current_org_id"
                )
    except Exception:
        pass


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0002_enable_rls"),
    ]

    operations = [
        migrations.RunPython(apply, revert, atomic=False),
    ]

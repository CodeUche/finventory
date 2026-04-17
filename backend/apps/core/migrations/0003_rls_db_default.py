"""
Set a database-level default for app.current_org_id so every new PostgreSQL
connection starts with the sentinel value instead of an unset variable.

Without this, the very first SQL statement on a brand-new connection would see
current_setting('app.current_org_id', TRUE) return NULL, causing RLS policies
to filter out all rows before RLSMiddleware has a chance to set the variable.

The ALTER DATABASE form persists across server restarts and applies to every
new connection to this database.
"""

from django.db import migrations

SENTINEL = "00000000-0000-0000-0000-000000000000"


def apply(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    db_name = schema_editor.connection.settings_dict["NAME"]
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            f"ALTER DATABASE \"{db_name}\" SET app.current_org_id = %s",
            [SENTINEL],
        )


def revert(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    db_name = schema_editor.connection.settings_dict["NAME"]
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            f"ALTER DATABASE \"{db_name}\" RESET app.current_org_id"
        )


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0002_enable_rls"),
    ]

    operations = [
        migrations.RunPython(apply, revert, atomic=False),
    ]

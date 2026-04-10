"""Add missing deleted_at column to sales_location if it doesn't already exist."""

from django.db import migrations, models


def add_deleted_at_if_missing(apps, schema_editor):
    from django.db import connection
    db_vendor = connection.vendor  # 'postgresql', 'sqlite', etc.
    with connection.cursor() as cursor:
        if db_vendor == 'postgresql':
            cursor.execute("""
                SELECT column_name FROM information_schema.columns
                WHERE table_name='sales_location' AND column_name='deleted_at'
            """)
            exists = cursor.fetchone()
        else:
            # SQLite: use PRAGMA table_info
            cursor.execute("PRAGMA table_info(sales_location)")
            rows = cursor.fetchall()
            exists = any(row[1] == 'deleted_at' for row in rows)

        if not exists:
            if db_vendor == 'postgresql':
                cursor.execute(
                    "ALTER TABLE sales_location ADD COLUMN deleted_at timestamp with time zone NULL"
                )
            else:
                cursor.execute(
                    "ALTER TABLE sales_location ADD COLUMN deleted_at datetime NULL"
                )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("sales", "0010_location_invoice_location"),
    ]

    operations = [
        migrations.RunPython(add_deleted_at_if_missing, noop),
    ]

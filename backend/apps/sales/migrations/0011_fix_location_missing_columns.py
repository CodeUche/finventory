"""Add missing deleted_at column to sales_location if it doesn't already exist."""

from django.db import migrations, models


def add_deleted_at_if_missing(apps, schema_editor):
    from django.db import connection
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name='sales_location' AND column_name='deleted_at'
        """)
        if not cursor.fetchone():
            cursor.execute(
                "ALTER TABLE sales_location ADD COLUMN deleted_at timestamp with time zone NULL"
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

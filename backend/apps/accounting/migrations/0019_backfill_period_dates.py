"""Backfill start_date/end_date on existing FinancialPeriod rows from (year, month).

Additive + safe: only touches rows where start_date is NULL, never changes
year/month/is_locked, so existing period locks are preserved.
"""
import calendar
from datetime import date

from django.db import migrations


def backfill_dates(apps, schema_editor):
    FinancialPeriod = apps.get_model("accounting", "FinancialPeriod")
    for period in FinancialPeriod.objects.filter(start_date__isnull=True).iterator():
        try:
            last_dom = calendar.monthrange(period.year, period.month)[1]
            period.start_date = date(period.year, period.month, 1)
            period.end_date = date(period.year, period.month, last_dom)
            period.save(update_fields=["start_date", "end_date"])
        except Exception:
            # Defensive: never let a bad legacy row break the migration.
            continue


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("accounting", "0018_financialperiod_end_date_and_more"),
    ]

    operations = [
        migrations.RunPython(backfill_dates, noop),
    ]

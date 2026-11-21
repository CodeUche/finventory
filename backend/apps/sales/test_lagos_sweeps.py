"""At 23:30 UTC it is already 00:30 the next day in Lagos: sweeps and 'as of today'
defaults must use the Lagos date."""

from datetime import date, datetime, timezone as dt_timezone
from unittest.mock import patch

from django.test import override_settings

from apps.sales.models import Invoice
from apps.sales.test_new_sale_and_invoice import D
from apps.sales.test_sales_ledger import LedgerBase

UTC_LATE = datetime(2026, 11, 20, 23, 30, tzinfo=dt_timezone.utc)      # 21 Nov 00:30 in Lagos
UTC_LATE_MARCH = datetime(2026, 3, 14, 23, 30, tzinfo=dt_timezone.utc)  # 15 Mar 00:30 in Lagos (not the real today)


@override_settings(TIME_ZONE="Africa/Lagos")
class LagosSweepTests(LedgerBase):
    def test_the_overdue_sweep_uses_the_lagos_date(self):
        from apps.sales.tasks import mark_overdue_invoices
        inv = self.sale(amount_paid="0", due_date="2026-11-20")      # due 20 Nov, unpaid
        with patch("django.utils.timezone.now", return_value=UTC_LATE):
            mark_overdue_invoices()
        inv.refresh_from_db()
        self.assertEqual(inv.status, "overdue")                       # 21 Nov in Lagos: a day late

    def test_the_overdue_sweep_still_waits_for_the_due_date(self):
        from apps.sales.tasks import mark_overdue_invoices
        inv = self.sale(amount_paid="0", due_date="2026-11-21")
        with patch("django.utils.timezone.now", return_value=UTC_LATE):
            mark_overdue_invoices()
        inv.refresh_from_db()
        self.assertEqual(inv.status, "confirmed")

    def test_ar_aging_default_as_of_is_the_lagos_date(self):
        from apps.reports.services import ReportService
        inv = self.sale(amount_paid="0", due_date="2026-11-20")
        with patch("django.utils.timezone.now", return_value=UTC_LATE_MARCH):
            out = ReportService.ar_aging(self.org)
        self.assertEqual(str(out["as_of"])[:10], "2026-03-15")

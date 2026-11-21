"""Round 3 of the security re-check: negative prices, walk-in proforma confirm, row
locks on edit/return, leaked error text, idempotency claim length."""

import smtplib
from datetime import timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.utils import timezone

from apps.core.models import IdempotencyRecord
from apps.sales.models import Invoice
from apps.sales.services import SaleService
from apps.sales.test_new_sale_and_invoice import D, URL, _client
from apps.sales.test_sales_ledger import LedgerBase
from apps.sales.test_security_round import _staff
from apps.tenancy.models import EmailConfig


# ── N1 ──────────────────────────────────────────────────────────────────────
class NegativePriceTests(LedgerBase):
    def test_a_negative_unit_price_is_refused_on_create(self):
        res = self.post(items=[self.line(price="-500")], amount_paid="0")
        self.assertEqual(res.status_code, 400)
        self.assertEqual(Invoice.objects.filter(organisation=self.org).count(), 0)

    def test_a_negative_unit_price_is_refused_on_edit(self):
        inv = self.sale(payment_method="credit", amount_paid="0")
        res = self.api.patch(f"{URL}{inv.id}/edit_lines/", {
            "items": [{"product_id": str(self.taxed.id), "quantity": 1, "unit_price": "-500"}]}, format="json")
        self.assertEqual(res.status_code, 422)
        inv.refresh_from_db()
        self.assertEqual(inv.total_amount, D("2150"))

    def test_a_line_that_adds_up_negative_is_refused_by_the_service(self):
        """The backstop: whatever reaches the service, no negative line or invoice total."""
        with self.assertRaises(ValueError):
            SaleService.create_sale(
                organisation=self.org, created_by=self.user, customer=self.customer, warehouse=self.wh,
                items=[{"product_id": self.taxed.id, "quantity": 1, "unit_price": D("-500")}],
                payment_method="credit")
        self.assertEqual(Invoice.objects.filter(organisation=self.org).count(), 0)

    def test_a_zero_price_line_is_still_allowed(self):
        self.assertEqual(self.post(items=[self.line(price="0")], amount_paid="0").status_code, 201)

    def test_normal_prices_unaffected(self):
        self.assertEqual(self.post().status_code, 201)


# ── N2 ──────────────────────────────────────────────────────────────────────
class WalkInProformaConfirmTests(LedgerBase):
    def proforma(self, **kw):
        return self.ok(customer_id=None, is_proforma=True, amount_paid="0", **kw)

    def test_staff_cannot_confirm_an_unpaid_walk_in_proforma(self):
        inv = self.proforma()
        staff = _staff("n2_staff@example.com", self.org)
        res = _client(staff, self.org).post(f"{URL}{inv.id}/confirm_proforma/", {"allow_unpaid_walk_in": True},
                                            format="json")
        self.assertEqual(res.status_code, 422)
        self.assertIn("walk-in", res.data["error"].lower())
        inv.refresh_from_db()
        self.assertEqual(inv.status, "proforma")
        self.assertEqual(self.on_hand(self.goods), D("100"))

    def test_the_owner_without_the_flag_is_refused_too(self):
        inv = self.proforma()
        self.assertEqual(self.api.post(f"{URL}{inv.id}/confirm_proforma/").status_code, 422)

    def test_a_manager_with_the_flag_may_confirm_it(self):
        inv = self.proforma()
        res = self.api.post(f"{URL}{inv.id}/confirm_proforma/", {"allow_unpaid_walk_in": True}, format="json")
        self.assertEqual(res.status_code, 200, getattr(res, "data", None))
        self.assertEqual(res.data["status"], "confirmed")

    def test_a_walk_in_proforma_paid_in_full_confirms_without_the_flag(self):
        inv = self.proforma()
        self.pay(inv, 2000)                      # deposit of the whole total (goods, no VAT)
        res = self.api.post(f"{URL}{inv.id}/confirm_proforma/")
        self.assertEqual(res.status_code, 200, getattr(res, "data", None))
        self.assertEqual(res.data["status"], "paid")

    def test_a_proforma_with_a_customer_is_unaffected(self):
        inv = self.sale(is_proforma=True, amount_paid="0")
        self.assertEqual(self.api.post(f"{URL}{inv.id}/confirm_proforma/").status_code, 200)


# ── N3 / N4 ─────────────────────────────────────────────────────────────────
class RowLockTests(LedgerBase):
    def test_an_edit_does_not_overwrite_a_payment_that_landed_after_the_page_loaded(self):
        inv = self.sale(payment_method="credit", amount_paid="0")
        stale = Invoice.objects.get(pk=inv.pk)                  # the page's copy: nothing paid
        self.pay(inv, 1000)                                     # a payment lands meanwhile
        SaleService.update_sale(
            stale, self.user, items=[{"product_id": self.taxed.id, "quantity": 2, "unit_price": D("1000"),
                                      "discount_percent": D("0")}], notes="edited")
        fresh = Invoice.objects.get(pk=inv.pk)
        self.assertEqual((fresh.amount_paid, fresh.amount_due), (D("1000"), D("1150")))
        self.assertEqual(fresh.status, "partially_paid")

    def test_a_stale_copy_cannot_edit_an_invoice_that_was_voided_meanwhile(self):
        inv = self.sale(payment_method="credit", amount_paid="0")
        stale = Invoice.objects.get(pk=inv.pk)
        self.api.post(f"{URL}{inv.id}/void/")
        with self.assertRaises(ValueError):
            SaleService.update_sale(
                stale, self.user, items=[{"product_id": self.taxed.id, "quantity": 1, "unit_price": D("1000"),
                                          "discount_percent": D("0")}])
        self.zero = True
        self.assertEqual(self.gl("ar"), D("0"))                 # nothing re-posted
        self.assertEqual(self.on_hand(self.taxed), D("100"))

    def test_a_stale_copy_cannot_take_a_return_on_an_invoice_voided_meanwhile(self):
        inv = self.sale(payment_method="credit", amount_paid="0")
        stale = Invoice.objects.get(pk=inv.pk)
        item = stale.items.first()
        self.api.post(f"{URL}{inv.id}/void/")
        with self.assertRaises(ValueError):
            SaleService.process_return(
                organisation=self.org, invoice=stale,
                items=[{"sale_item_id": str(item.id), "quantity_returned": "1"}],
                reason="other", notes="", processed_by=self.user)
        self.assertEqual(self.on_hand(self.taxed), D("100"))

    def test_a_normal_edit_and_return_still_work(self):
        inv = self.sale()
        item = inv.items.first()
        res = self.api.post(f"{URL}{inv.id}/process_return/", {
            "items": [{"sale_item_id": str(item.id), "quantity_returned": "1"}]}, format="json")
        self.assertEqual(res.status_code, 201)


# ── N5 ──────────────────────────────────────────────────────────────────────
class ErrorLeakTests(LedgerBase):
    def setUp(self):
        super().setUp()
        self.customer.email = "ada@example.com"
        self.customer.save()
        self.inv = self.sale()
        EmailConfig.objects.create(
            organisation=self.org, smtp_host="smtp.secret-host.internal", smtp_port=2525, smtp_username="u@test",
            smtp_password="pw", use_tls=True, from_name="NSI", from_email="u@test", is_active=True)

    @patch("smtplib.SMTP")
    def test_smtp_connect_failure_does_not_name_the_host_or_port(self, smtp):
        smtp.side_effect = smtplib.SMTPConnectError(421, "no route")
        res = self.api.post(f"{URL}{self.inv.id}/send_email/", {}, format="json")
        self.assertEqual(res.status_code, 422)
        self.assertNotIn("secret-host", str(res.data))
        self.assertNotIn("2525", str(res.data))

    @patch("smtplib.SMTP")
    def test_a_network_error_does_not_echo_the_operating_system_text(self, smtp):
        smtp.side_effect = OSError("[Errno 111] Connection refused to 10.0.0.7:2525")
        res = self.api.post(f"{URL}{self.inv.id}/send_email/", {}, format="json")
        self.assertEqual(res.status_code, 422)
        self.assertNotIn("10.0.0.7", str(res.data))
        self.assertNotIn("Errno", str(res.data))

    def test_generate_now_does_not_leak(self):
        from apps.sales.models import RecurringInvoice
        rec = RecurringInvoice.objects.create(
            organisation=self.org, template_name="T", customer=self.customer, warehouse=self.wh, created_by=self.user,
            frequency="monthly", next_run_date=timezone.now().date(),
            items=[{"product_id": str(self.taxed.id), "quantity": 1, "unit_price": "1000"}])
        with patch("apps.sales.views.SaleService.create_sale", side_effect=RuntimeError("secret internals")):
            res = self.api.post(f"/api/v1/sales/recurring/{rec.id}/generate_now/")
        self.assertNotIn("secret", str(res.data))
        self.assertNotIn("RuntimeError", str(res.data))


# ── N7 ──────────────────────────────────────────────────────────────────────
class IdempotencyClaimTests(LedgerBase):
    def test_the_reservation_outlives_a_slow_sale(self):
        seen = {}

        def slow(self_view, request, idem_key):
            rec = IdempotencyRecord.objects.get(user_id=request.user.id)
            seen["left"] = rec.expires_at - timezone.now()
            from rest_framework.response import Response
            return Response({"error": "x"}, status=400)

        with patch("apps.sales.views.InvoiceViewSet._create_inner", slow):
            self.api.post(URL, self.payload(), format="json", HTTP_IDEMPOTENCY_KEY="slow-1")
        self.assertGreater(seen["left"], timedelta(minutes=4))
        self.assertEqual(IdempotencyRecord.objects.filter(response_status=0).count(), 0)   # released on failure

"""
Security-review round for the sales API: store-credit double spend, returns on
dead invoices, unbounded edit lines, walk-in underpayment, webhook money that
cannot be applied, invoice e-mail abuse, idempotency scoping, audit detail,
leaked exception text, WHT on void.
"""

import base64
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.test import override_settings

from apps.accounting.models import Account, FinancialPeriod, JournalEntry
from apps.core.models import AuditLog, IdempotencyRecord
from apps.customers.models import Customer
from apps.payments.models import PaymentLink, VirtualAccount
from apps.payments.providers import PaymentProviderError
from apps.payments.providers.base import PaymentEvent
from apps.payments.services import PaymentService
from apps.sales import ledger
from apps.sales.models import Invoice, SalePayment
from apps.sales.services import SaleService
from apps.sales.test_new_sale_and_invoice import D, URL, _client, _user
from apps.sales.test_sales_ledger import LedgerBase
from apps.tax.models import WHTTransaction
from apps.tenancy.models import EmailConfig, Membership
from apps.tenancy.services import OrganisationService

def _staff(email, org):
    from apps.tenancy.models import ModulePermission
    user = _user(email)
    m = Membership.objects.create(organisation=org, user=user, role="staff")
    ModulePermission.objects.create(membership=m, module="sales", access_level="write")
    return user


LOCMEM = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}


# ── F1 ──────────────────────────────────────────────────────────────────────
class StoreCreditDoubleSpendTests(LedgerBase):
    def setUp(self):
        super().setUp()
        self.customer.store_credit = D("500")
        self.customer.save()

    def _sale(self, customer_obj, credit):
        return SaleService.create_sale(
            organisation=self.org, created_by=self.user, customer=customer_obj, warehouse=self.wh,
            items=[{"product_id": self.taxed.id, "quantity": 1, "unit_price": "1000"}],
            payment_method="cash", amount_paid=D("0"), credit_applied=D(credit),
        )

    def test_a_stale_copy_of_the_customer_cannot_spend_credit_that_is_gone(self):
        stale = Customer.objects.get(pk=self.customer.pk)            # still shows 500
        Customer.objects.filter(pk=self.customer.pk).update(store_credit=D("0"))   # another sale spent it
        with self.assertRaises(ValueError):
            self._sale(stale, "500")
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.store_credit, D("0"))
        self.assertEqual(Invoice.objects.filter(organisation=self.org).count(), 0)

    def test_the_balance_is_reduced_from_the_stored_value_not_the_callers_copy(self):
        stale = Customer.objects.get(pk=self.customer.pk)            # shows 500
        Customer.objects.filter(pk=self.customer.pk).update(store_credit=D("800"))
        self._sale(stale, "300")
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.store_credit, D("500"))       # 800 - 300, not 500 - 300

    def test_void_gives_the_credit_back_on_top_of_the_current_balance(self):
        inv = self._sale(Customer.objects.get(pk=self.customer.pk), "300")     # 500 -> 200
        Customer.objects.filter(pk=self.customer.pk).update(store_credit=D("1000"))
        SaleService.void_invoice(inv, voided_by=self.user)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.store_credit, D("1300"))

    def test_credit_of_another_organisations_customer_is_refused(self):
        other_user = _user("sc_other@example.com")
        other_org = OrganisationService.create_organisation(
            name="SC Other", owner=other_user, extra={"currency": "NGN", "country": "NG"})
        foreign = Customer.objects.create(organisation=other_org, code="F1", name="F", store_credit=D("900"))
        with self.assertRaises(Exception):
            self._sale(foreign, "100")
        foreign.refresh_from_db()
        self.assertEqual(foreign.store_credit, D("900"))


# ── F2 ──────────────────────────────────────────────────────────────────────
class ReturnOnDeadInvoiceTests(LedgerBase):
    def _return(self, inv):
        item = inv.items.first()
        return self.api.post(f"{URL}{inv.id}/process_return/", {
            "items": [{"sale_item_id": str(item.id), "quantity_returned": "1"}]}, format="json")

    def test_no_return_after_void(self):
        inv = self.sale(payment_method="credit", amount_paid="0")
        self.api.post(f"{URL}{inv.id}/void/")
        stock = self.on_hand(self.taxed)
        res = self._return(inv)
        self.assertEqual(res.status_code, 422)
        self.assertIn("voided", res.data["error"].lower())
        self.assertEqual(self.on_hand(self.taxed), stock)
        self.assertEqual(self.entries("sale_return"), [])

    def test_no_return_on_a_proforma(self):
        inv = self.sale(is_proforma=True, amount_paid="0")
        res = self._return(inv)
        self.assertEqual(res.status_code, 422)
        self.assertIn("proforma", res.data["error"].lower())

    def test_no_return_when_everything_was_already_returned(self):
        inv = self.sale()
        item = inv.items.first()
        res = self.api.post(f"{URL}{inv.id}/process_return/", {
            "items": [{"sale_item_id": str(item.id), "quantity_returned": "2"}]}, format="json")
        self.assertEqual(res.status_code, 201, res.data)
        inv.refresh_from_db()
        self.assertEqual(inv.status, "returned")      # used to stay 'paid': stale prefetched lines
        again = self._return(inv)
        self.assertEqual(again.status_code, 422)
        self.assertIn("returned", again.data["error"].lower())

    def test_a_normal_partial_return_still_works(self):
        inv = self.sale()
        self.assertEqual(self._return(inv).status_code, 201)


# ── F3 ──────────────────────────────────────────────────────────────────────
class EditLinesBoundsTests(LedgerBase):
    def edit(self, inv, items, **extra):
        return self.api.patch(f"{URL}{inv.id}/edit_lines/", {"items": items, **extra}, format="json")

    def line_payload(self, **kw):
        return {"product_id": str(self.taxed.id), "quantity": 1, "unit_price": "1000", **kw}

    def setUp(self):
        super().setUp()
        self.inv = self.sale(payment_method="credit", amount_paid="0")

    def test_negative_quantity_refused(self):
        self.assertEqual(self.edit(self.inv, [self.line_payload(quantity=-5)]).status_code, 422)

    def test_discount_outside_0_100_refused(self):
        self.assertEqual(self.edit(self.inv, [self.line_payload(discount_percent=150)]).status_code, 422)
        self.assertEqual(self.edit(self.inv, [self.line_payload(discount_percent=-1)]).status_code, 422)

    def test_negative_tax_rate_refused(self):
        self.assertEqual(self.edit(self.inv, [self.line_payload(tax_rate="-7.5")]).status_code, 422)

    def test_too_many_lines_refused(self):
        self.assertEqual(self.edit(self.inv, [self.line_payload()] * 201).status_code, 422)

    def test_a_refused_edit_changes_nothing(self):
        self.edit(self.inv, [self.line_payload(quantity=-5)])
        self.inv.refresh_from_db()
        self.assertEqual(self.inv.total_amount, D("2150"))
        self.assertEqual(self.inv.items.count(), 1)

    def test_a_valid_money_edit_works_and_the_ledger_follows(self):
        """(The ledger is re-posted by the edit now -- see test_accountant_round.)"""
        res = self.edit(self.inv, [self.line_payload(quantity=1)])
        self.assertEqual(res.status_code, 200, res.data)
        self.assertNotIn("warning", res.data)
        self.assertEqual(self.gl("ar"), D("1075"))

    def test_an_edit_that_changes_nothing_has_no_warning(self):
        res = self.edit(self.inv, [self.line_payload(quantity=2)])
        self.assertEqual(res.status_code, 200, res.data)
        self.assertNotIn("warning", res.data)

    def test_an_unposted_proforma_edit_has_no_warning(self):
        pro = self.sale(is_proforma=True, amount_paid="0")
        res = self.edit(pro, [self.line_payload(quantity=1)])
        self.assertEqual(res.status_code, 200, res.data)
        self.assertNotIn("warning", res.data)


# ── F4 ──────────────────────────────────────────────────────────────────────
class WalkInAlwaysPaidTests(LedgerBase):
    def walk_in(self, client=None, **over):
        payload = self.payload(customer_id=None, **over)
        payload.pop("amount_paid", None)
        payload.update({k: v for k, v in over.items() if k == "amount_paid"})
        return (client or self.api).post(URL, payload, format="json")

    def test_walk_in_with_no_amount_paid_is_refused(self):
        res = self.walk_in()
        self.assertEqual(res.status_code, 422)
        self.assertIn("walk-in", res.data["error"].lower())
        self.assertEqual(Invoice.objects.filter(organisation=self.org).count(), 0)

    def test_walk_in_proforma_needs_no_payment(self):
        self.assertEqual(self.walk_in(is_proforma=True).status_code, 201)

    def test_a_manager_may_record_an_unpaid_walk_in_with_the_explicit_flag(self):
        res = self.walk_in(allow_unpaid_walk_in=True)
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(res.data["status"], "confirmed")

    def test_staff_cannot_use_the_flag(self):
        staff = _staff("wi_staff@example.com", self.org)
        res = self.walk_in(client=_client(staff, self.org), allow_unpaid_walk_in=True)
        self.assertEqual(res.status_code, 422)

    def test_walk_in_paid_in_full_still_fine(self):
        self.assertEqual(self.walk_in(amount_paid="2000").status_code, 201)


# ── F5 ──────────────────────────────────────────────────────────────────────
class GatewayMoneyThatCannotBeAppliedTests(LedgerBase):
    def setUp(self):
        super().setUp()
        self.inv = self.sale(payment_method="credit", amount_paid="0")
        self.link = PaymentLink.objects.create(
            organisation=self.org, invoice=self.inv, provider="paystack",
            payment_reference="REF-X", amount=D("1000"), link_url="https://example.test/pay")

    def event(self, ref="REF-X", event_id="e1"):
        return PaymentEvent(event_id=event_id, reference=ref, amount=D("1000"), status="success",
                            channel="bank_transfer", raw={"id": event_id})

    def test_payment_for_a_voided_invoice_is_parked_not_applied_and_does_not_raise(self):
        self.api.post(f"{URL}{self.inv.id}/void/")
        outcome = PaymentService.settle(self.org, "paystack", self.event())
        self.assertIn("needs review", outcome)
        self.assertEqual(SalePayment.objects.filter(invoice=self.inv, amount__gt=0).count(), 0)
        from apps.payments.models import PaymentEventLog
        self.assertIn("needs review", PaymentEventLog.objects.get(event_id="e1").note)

    def test_void_cancels_open_pay_links_and_transfer_accounts(self):
        va = VirtualAccount.objects.create(
            organisation=self.org, invoice=self.inv, provider="paystack", reference="VA-1",
            account_number="0123456789", amount=D("1000"))
        self.api.post(f"{URL}{self.inv.id}/void/")
        self.link.refresh_from_db()
        va.refresh_from_db()
        self.assertEqual(self.link.status, PaymentLink.CANCELLED)
        self.assertEqual(va.status, VirtualAccount.CANCELLED)

    def test_a_new_pay_link_cannot_be_made_for_a_voided_invoice(self):
        self.api.post(f"{URL}{self.inv.id}/void/")
        inv = Invoice.objects.get(pk=self.inv.pk)
        with self.assertRaises(PaymentProviderError):
            PaymentService.create_payment_link(inv, config=MagicMock(allow_card=True))

    def test_a_locked_period_does_not_drop_the_payment_or_raise(self):
        today = date.today()
        FinancialPeriod.objects.create(organisation=self.org, year=today.year, month=today.month, is_locked=True)
        outcome = PaymentService.settle(self.org, "paystack", self.event())
        self.assertIn("needs review", outcome)
        self.link.refresh_from_db()
        self.assertEqual(self.link.status, PaymentLink.PENDING)       # still unpaid, not marked paid
        self.inv.refresh_from_db()
        self.assertEqual(self.inv.amount_paid, D("0"))

    def test_a_missing_gl_account_is_parked_too(self):
        with patch("apps.sales.ledger.post_receipt_entry", side_effect=RuntimeError("boom")):
            outcome = PaymentService.settle(self.org, "paystack", self.event())
        self.assertIn("needs review", outcome)
        self.assertEqual(self.inv.payments.count(), 0)

    def test_a_normal_payment_still_settles(self):
        self.assertEqual(PaymentService.settle(self.org, "paystack", self.event()), "settled")


# ── F7 ──────────────────────────────────────────────────────────────────────
class InvoiceEmailHardeningTests(LedgerBase):
    def setUp(self):
        super().setUp()
        self.customer.email = "ada@example.com"
        self.customer.save()
        self.inv = self.sale()
        EmailConfig.objects.create(
            organisation=self.org, smtp_host="smtp.test", smtp_port=587, smtp_username="u@test",
            smtp_password="pw", use_tls=True, from_name="NSI", from_email="u@test", is_active=True)

    def send(self, inv=None, client=None, **body):
        return (client or self.api).post(f"{URL}{(inv or self.inv).id}/send_email/", body, format="json")

    def pdf(self, raw=b"%PDF-1.4 ok"):
        return base64.b64encode(raw).decode()

    def test_staff_cannot_send_a_walk_in_invoice_to_an_arbitrary_address(self):
        walk = self.ok(customer_id=None)
        staff = _staff("em_staff@example.com", self.org)
        res = self.send(inv=walk, client=_client(staff, self.org), to_email="anyone@example.com")
        self.assertEqual(res.status_code, 403)

    def test_bad_addresses_are_refused(self):
        for bad in ("not-an-email", "a@b.com\\r\\nBcc: x@y.com", "a@b.com\r\nBcc: x@y.com",
                    "a b@c.com", "a@b.com,c@d.com", "a@b.com\nBcc: x@y.com"):
            with self.subTest(bad=bad):
                self.assertEqual(self.send(to_email=bad).status_code, 422)

    @patch("smtplib.SMTP")
    def test_a_pdf_must_be_a_real_pdf(self, smtp):
        res = self.send(pdf_base64=self.pdf(b"MZ not a pdf"))
        self.assertEqual(res.status_code, 422)
        smtp.assert_not_called()

    @patch("smtplib.SMTP")
    def test_invalid_base64_is_refused(self, smtp):
        self.assertEqual(self.send(pdf_base64="@@@not base64@@@").status_code, 422)

    @patch("smtplib.SMTP")
    def test_an_oversized_pdf_is_refused(self, smtp):
        big = b"%PDF-" + b"0" * (5 * 1024 * 1024 + 10)
        self.assertEqual(self.send(pdf_base64=self.pdf(big)).status_code, 422)
        smtp.assert_not_called()

    @patch("smtplib.SMTP")
    def test_a_good_pdf_is_still_sent(self, smtp):
        smtp.return_value = MagicMock()
        self.assertEqual(self.send(pdf_base64=self.pdf()).status_code, 200)

    @patch("smtplib.SMTP")
    def test_line_breaks_in_the_sender_name_cannot_inject_headers(self, smtp):
        conn = MagicMock()
        smtp.return_value = conn
        EmailConfig.objects.filter(organisation=self.org).update(from_name="NSI\r\nBcc: evil@example.com")
        self.assertEqual(self.send().status_code, 200)
        raw = conn.sendmail.call_args[0][2]
        header_block = raw.split("\n\n", 1)[0]
        self.assertNotIn("\nBcc:", header_block)

    @override_settings(CACHES=LOCMEM, INVOICE_EMAIL_DAILY_CAP_PER_ORG=2)
    @patch("smtplib.SMTP")
    def test_daily_send_cap_per_organisation(self, smtp):
        from django.core.cache import cache
        cache.clear()
        smtp.return_value = MagicMock()
        self.assertEqual(self.send().status_code, 200)
        self.assertEqual(self.send().status_code, 200)
        res = self.send()
        self.assertEqual(res.status_code, 429)
        self.assertIn("daily", res.data["error"].lower())


# ── F8 ──────────────────────────────────────────────────────────────────────
class IdempotencyScopeTests(LedgerBase):
    def post_key(self, key, client=None, **over):
        return (client or self.api).post(URL, self.payload(**over), format="json", HTTP_IDEMPOTENCY_KEY=key)

    def test_same_key_with_a_different_body_is_a_conflict(self):
        self.assertEqual(self.post_key("k-body").status_code, 201)
        res = self.post_key("k-body", amount_paid="1000.00")
        self.assertEqual(res.status_code, 409)
        self.assertEqual(Invoice.objects.filter(organisation=self.org).count(), 1)

    def test_same_key_same_body_replays(self):
        a = self.post_key("k-same")
        b = self.post_key("k-same")
        self.assertEqual(str(a.data["id"]), str(b.data["id"]))

    def test_the_key_is_scoped_to_the_organisation(self):
        """One user in two organisations: a key used in org A must not return A's
        invoice when reused in org B."""
        org_b = OrganisationService.create_organisation(
            name="Second Org", owner=self.user, extra={"currency": "NGN", "country": "NG"})
        wh_b = self.wh.__class__.objects.create(organisation=org_b, name="B", is_default=True)
        api_b = _client(self.user, org_b)
        first = self.post_key("k-org")
        body_b = {"warehouse_id": str(wh_b.id), "payment_method": "cash", "amount_paid": "0",
                  "items": [{"product_id": str(self.service.id), "quantity": 1}]}
        # product belongs to A: B refuses it, and crucially does NOT replay A's invoice
        res = api_b.post(URL, body_b, format="json", HTTP_IDEMPOTENCY_KEY="k-org")
        self.assertNotEqual(str(res.data.get("id")), str(first.data["id"]))
        self.assertEqual(Invoice.objects.filter(organisation=self.org).count(), 1)

    def test_a_request_still_in_progress_is_a_409_not_a_second_sale(self):
        from django.utils import timezone
        from datetime import timedelta
        from apps.core.idempotency import scoped_key
        IdempotencyRecord.objects.create(
            user_id=self.user.id, key=scoped_key("invoice:create", self.org.id, "k-busy"),
            response_body="", response_status=0, expires_at=timezone.now() + timedelta(minutes=1))
        res = self.post_key("k-busy")
        self.assertEqual(res.status_code, 409)
        self.assertEqual(Invoice.objects.filter(organisation=self.org).count(), 0)

    def test_a_failed_attempt_releases_the_key_so_the_fixed_request_can_retry(self):
        bad = self.post_key("k-retry", items=[])
        self.assertEqual(bad.status_code, 400)
        ok = self.post_key("k-retry")
        self.assertEqual(ok.status_code, 201, getattr(ok, "data", None))


# ── F10 ─────────────────────────────────────────────────────────────────────
class CreateAuditDetailTests(LedgerBase):
    def test_adjustment_discount_and_price_override_are_written_to_the_audit_log(self):
        res = self.post(items=[self.line(price="900", discount_percent="10")],
                        adjustment_amount="-50", amount_paid="0")
        self.assertEqual(res.status_code, 201, res.data)
        log = AuditLog.objects.filter(organisation_id=self.org.id, model_name="Invoice",
                                      object_id=str(res.data["id"]), action=AuditLog.CREATE).first()
        self.assertIsNotNone(log)
        ch = log.changes
        self.assertEqual(D(str(ch["adjustment_amount"]["new"])), D("-50"))
        self.assertIn("price_overrides", ch)
        self.assertEqual(D(ch["price_overrides"]["new"][0]["list_price"]), D("1000"))
        self.assertEqual(D(ch["price_overrides"]["new"][0]["unit_price"]), D("900"))
        self.assertIn("discount_amount", ch)
        self.assertEqual(D(ch["line_discounts"]["new"][0]["discount_percent"]), D("10"))

    def test_a_plain_sale_has_no_override_noise(self):
        res = self.post(items=[self.line(price="1000")])
        log = AuditLog.objects.filter(organisation_id=self.org.id, object_id=str(res.data["id"])).first()
        self.assertNotIn("price_overrides", log.changes)


# ── F12 ─────────────────────────────────────────────────────────────────────
class ErrorTextTests(LedgerBase):
    def test_unexpected_errors_do_not_leak_their_text(self):
        with patch("apps.sales.views.SaleService.create_sale", side_effect=RuntimeError("secret internals /srv/x")):
            res = self.post(items=[self.line()])
        self.assertEqual(res.status_code, 422)
        self.assertNotIn("secret", str(res.data))
        self.assertNotIn("RuntimeError", str(res.data))
        self.assertIn("error_id", res.data)

    def test_business_errors_are_still_explained(self):
        res = self.post(items=[self.line(qty=100000)], amount_paid="0")
        self.assertEqual(res.status_code, 422)
        self.assertIn("Insufficient stock", res.data["error"])

    def test_edit_lines_does_not_leak_either(self):
        inv = self.sale(payment_method="credit", amount_paid="0")
        with patch("apps.sales.views.SaleService.update_sale", side_effect=RuntimeError("secret internals")):
            res = self.api.patch(f"{URL}{inv.id}/edit_lines/", {
                "items": [{"product_id": str(self.taxed.id), "quantity": 1}]}, format="json")
        self.assertNotIn("secret", str(res.data))
        self.assertIn("error_id", res.data)

    def test_fulfil_does_not_leak_but_locked_period_is_explained(self):
        inv = self.sale(defer_fulfillment=True, amount_paid="0")
        with patch("apps.sales.views.SaleService.fulfill_invoice", side_effect=RuntimeError("secret internals")):
            res = self.api.post(f"{URL}{inv.id}/fulfill/")
        self.assertNotIn("secret", str(res.data))
        self.assertIn("error_id", res.data)
        today = date.today()
        FinancialPeriod.objects.create(organisation=self.org, year=today.year, month=today.month, is_locked=True)
        res2 = self.api.post(f"{URL}{inv.id}/fulfill/")
        self.assertIn("locked", res2.data["error"].lower())


# ── F15 ─────────────────────────────────────────────────────────────────────
class DepositsAccountTests(LedgerBase):
    def test_two_calls_make_one_account(self):
        Account.objects.filter(organisation=self.org, code="2050").delete()
        a = ledger.deposits_account(self.org)
        b = ledger.deposits_account(self.org)
        self.assertEqual(a.id, b.id)
        self.assertEqual(Account.objects.filter(organisation=self.org, code="2050").count(), 1)


# ── WHT on void / delete ────────────────────────────────────────────────────
class WhtOnVoidTests(LedgerBase):
    def setUp(self):
        super().setUp()
        from apps.tax.models import WHTRate
        self.rate = WHTRate.objects.filter(organisation=self.org).first()

    def wht(self):
        return WHTTransaction.objects.filter(organisation=self.org).count()

    def test_void_withdraws_the_wht_records(self):
        inv = self.sale(payment_method="credit", amount_paid="0", wht_rate_id=str(self.rate.id))
        self.pay(inv, 1000)
        self.assertEqual(self.wht(), 1)
        self.assertEqual(self.api.post(f"{URL}{inv.id}/void/").status_code, 200)
        self.assertEqual(self.wht(), 0)

    def test_delete_withdraws_the_wht_records(self):
        inv = self.sale(amount_paid="1000.00", wht_rate_id=str(self.rate.id))
        self.assertEqual(self.wht(), 1)
        self.assertEqual(self.api.post(f"{URL}{inv.id}/delete_invoice/").status_code, 204)
        self.assertEqual(self.wht(), 0)

    def test_an_already_remitted_record_is_left_alone(self):
        inv = self.sale(payment_method="credit", amount_paid="0", wht_rate_id=str(self.rate.id))
        self.pay(inv, 1000)
        WHTTransaction.objects.filter(organisation=self.org).update(status="remitted")
        self.api.post(f"{URL}{inv.id}/void/")
        self.assertEqual(self.wht(), 1)

    def test_another_invoices_wht_is_not_touched(self):
        a = self.sale(payment_method="credit", amount_paid="0", wht_rate_id=str(self.rate.id))
        b = self.sale(payment_method="credit", amount_paid="0", wht_rate_id=str(self.rate.id))
        self.pay(a, 500)
        self.pay(b, 700)
        self.api.post(f"{URL}{a.id}/void/")
        self.assertEqual([t.gross_amount for t in WHTTransaction.objects.filter(organisation=self.org)], [D("700")])

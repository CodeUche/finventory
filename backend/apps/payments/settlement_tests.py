"""
Card terminal settlement tests.

The matcher's job is to be *certain* or to stand aside. Most of these prove it
refuses rather than guesses — a payout quietly attached to the wrong sale is a
ledger error nobody would notice for months.
"""

from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounting.models import Account
from apps.accounting.services import AccountingService
from apps.authentication.models import User
from apps.customers.models import Customer
from apps.inventory.models import Warehouse
from apps.payments.settlement_models import SettlementBatch, SettlementLine
from apps.payments.settlement_services import SettlementError, SettlementService
from apps.sales.models import Invoice, SalePayment
from apps.subscriptions.models import Plan
from apps.subscriptions.services import SubscriptionService
from apps.tenancy.services import OrganisationService


def _user(email):
    return User.objects.create_user(
        email=email, password="TestPass123!", first_name="Set", last_name="Tle",
        is_verified=True,
    )


class SettlementTestBase(TestCase):
    def setUp(self):
        self.user = _user("settle@example.com")
        self.org = OrganisationService.create_organisation(
            name="Settle Org", owner=self.user, extra={"currency": "NGN", "country": "NG"},
        )
        SubscriptionService.upgrade_plan(self.org, Plan.objects.get(slug="business"))
        self.org.refresh_from_db()
        self.client = APIClient()
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(self.user).access_token}",
            HTTP_X_ORGANISATION_ID=str(self.org.id),
        )
        self.warehouse = Warehouse.objects.create(
            organisation=self.org, name="Main", is_default=True,
        )
        self.customer = Customer.objects.create(
            organisation=self.org, code="C1", name="Walk-in",
        )
        self.now = timezone.now()

    def _card_payment(self, amount, when=None, reference=""):
        invoice = Invoice.objects.create(
            organisation=self.org, customer=self.customer, created_by=self.user,
            warehouse=self.warehouse,
            invoice_number=f"INV-{Invoice.objects.count() + 1:05d}",
            issue_date=self.now.date(), subtotal=Decimal(amount),
            total_amount=Decimal(amount), amount_due=Decimal(amount),
            payment_method=Invoice.PaymentMethod.POS, status=Invoice.Status.CONFIRMED,
        )
        payment = SalePayment.objects.create(
            organisation=self.org, invoice=invoice, amount=Decimal(amount),
            method="pos", reference=reference, received_by=self.user,
        )
        # received_at is auto_now_add, so set the time we actually want.
        SalePayment.objects.filter(pk=payment.pk).update(received_at=when or self.now)
        payment.refresh_from_db()
        return payment

    def _batch(self, rows):
        return SettlementService.import_rows(self.org, rows, provider="Moniepoint")

    def _row(self, amount, ref="RRN1", when=None, narration=""):
        return {
            "provider_reference": ref, "amount": Decimal(amount), "fee": Decimal("0"),
            "paid_at": when or self.now, "terminal_id": "T1", "card_last4": "4242",
            "narration": narration,
        }


class CsvParsingTests(SettlementTestBase):
    def test_a_standard_export_is_understood(self):
        rows = SettlementService.parse_csv(
            "Date,Reference,Amount,Fee\n2026-08-01 10:00:00,RRN123,12400.00,50.00\n"
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["amount"], Decimal("12400.00"))
        self.assertEqual(rows[0]["fee"], Decimal("50.00"))
        self.assertEqual(rows[0]["provider_reference"], "RRN123")

    def test_column_names_vary_between_providers(self):
        rows = SettlementService.parse_csv(
            "Transaction Date,RRN,Amount Paid\n2026-08-01,ABC1,5000\n"
        )
        self.assertEqual(rows[0]["provider_reference"], "ABC1")
        self.assertEqual(rows[0]["amount"], Decimal("5000"))

    def test_currency_symbols_and_thousands_separators_are_handled(self):
        rows = SettlementService.parse_csv("Reference,Amount\nR1,\"₦1,240.50\"\n")
        self.assertEqual(rows[0]["amount"], Decimal("1240.50"))

    def test_semicolon_files_are_handled(self):
        rows = SettlementService.parse_csv("Reference;Amount\nR1;900\n")
        self.assertEqual(rows[0]["amount"], Decimal("900"))

    def test_blank_rows_are_skipped(self):
        rows = SettlementService.parse_csv("Reference,Amount\nR1,100\n,\nR2,200\n")
        self.assertEqual(len(rows), 2)

    def test_a_file_with_no_amount_column_is_refused_clearly(self):
        with self.assertRaises(SettlementError) as ctx:
            SettlementService.parse_csv("Reference,Terminal\nR1,T1\n")
        self.assertIn("amount column", str(ctx.exception))

    def test_an_empty_file_is_refused(self):
        with self.assertRaises(SettlementError):
            SettlementService.parse_csv("Reference,Amount\n")

    def test_day_first_dates_are_read_correctly(self):
        rows = SettlementService.parse_csv("Date,Reference,Amount\n01/08/2026,R1,100\n")
        self.assertIsNotNone(rows[0]["paid_at"])
        self.assertEqual(rows[0]["paid_at"].day, 1)
        self.assertEqual(rows[0]["paid_at"].month, 8)


class ImportTests(SettlementTestBase):
    def test_importing_stores_the_payouts(self):
        batch = self._batch([self._row("1000", "R1"), self._row("2000", "R2")])
        self.assertEqual(batch.line_count, 2)
        self.assertEqual(batch.total_amount, Decimal("3000"))

    def test_the_same_export_cannot_be_imported_twice(self):
        """Re-uploading yesterday's file must not duplicate the money."""
        self._batch([self._row("1000", "R1")])
        second = self._batch([self._row("1000", "R1"), self._row("2000", "R2")])
        self.assertEqual(second.line_count, 1)
        self.assertIn("already imported", second.note)
        self.assertEqual(SettlementLine.objects.filter(organisation=self.org).count(), 2)


class MatchingTests(SettlementTestBase):
    def test_an_exact_amount_on_the_same_day_matches(self):
        payment = self._card_payment("12400")
        batch = self._batch([self._row("12400", "R1")])
        result = SettlementService.match_batch(batch)

        self.assertEqual(result["matched"], 1)
        line = batch.lines.first()
        self.assertEqual(line.payment_id, payment.id)
        self.assertTrue(line.matched_automatically)

    def test_a_near_miss_is_never_matched(self):
        """₦12,400 is not ₦12,000 — being close is the dangerous case."""
        self._card_payment("12000")
        batch = self._batch([self._row("12400", "R1")])
        self.assertEqual(SettlementService.match_batch(batch)["matched"], 0)

    def test_cash_sales_are_never_matched_to_a_terminal_payout(self):
        invoice = Invoice.objects.create(
            organisation=self.org, customer=self.customer, created_by=self.user,
            warehouse=self.warehouse, invoice_number="INV-CASH",
            issue_date=self.now.date(), subtotal=Decimal("5000"),
            total_amount=Decimal("5000"), amount_due=Decimal("0"),
            payment_method=Invoice.PaymentMethod.CASH, status=Invoice.Status.PAID,
        )
        SalePayment.objects.create(
            organisation=self.org, invoice=invoice, amount=Decimal("5000"),
            method="cash", received_by=self.user,
        )
        batch = self._batch([self._row("5000", "R1")])
        self.assertEqual(SettlementService.match_batch(batch)["matched"], 0)

    def test_a_payout_outside_the_date_window_is_not_matched(self):
        self._card_payment("7000", when=self.now - timedelta(days=30))
        batch = self._batch([self._row("7000", "R1")])
        self.assertEqual(SettlementService.match_batch(batch)["matched"], 0)

    def test_next_day_settlement_still_matches(self):
        self._card_payment("7000", when=self.now - timedelta(days=1))
        batch = self._batch([self._row("7000", "R1")])
        self.assertEqual(SettlementService.match_batch(batch)["matched"], 1)

    def test_two_identical_sales_at_the_same_moment_are_left_for_a_human(self):
        """Genuinely ambiguous — picking one at random would be worse than asking."""
        self._card_payment("5000", when=self.now)
        self._card_payment("5000", when=self.now)
        batch = self._batch([self._row("5000", "R1")])
        self.assertEqual(SettlementService.match_batch(batch)["matched"], 0)

    def test_a_reference_breaks_the_tie(self):
        far = self._card_payment("5000", when=self.now - timedelta(hours=2))
        near = self._card_payment("5000", when=self.now, reference="RRN-XYZ")
        batch = self._batch([self._row("5000", "RRN-XYZ")])
        SettlementService.match_batch(batch)
        line = batch.lines.first()
        self.assertEqual(line.payment_id, near.id)
        self.assertNotEqual(line.payment_id, far.id)

    def test_one_payment_settles_only_one_payout(self):
        self._card_payment("3000")
        batch = self._batch([self._row("3000", "R1"), self._row("3000", "R2")])
        self.assertEqual(SettlementService.match_batch(batch)["matched"], 1)
        self.assertEqual(
            batch.lines.filter(status=SettlementLine.Status.UNMATCHED).count(), 1,
        )

    def test_another_organisations_sale_is_never_matched(self):
        other_user = _user("rival-settle@example.com")
        other_org = OrganisationService.create_organisation(
            name="Rival", owner=other_user, extra={"currency": "NGN", "country": "NG"},
        )
        wh = Warehouse.objects.create(organisation=other_org, name="W", is_default=True)
        cust = Customer.objects.create(organisation=other_org, code="X", name="X")
        inv = Invoice.objects.create(
            organisation=other_org, customer=cust, created_by=other_user, warehouse=wh,
            invoice_number="INV-OTHER", issue_date=self.now.date(),
            subtotal=Decimal("9999"), total_amount=Decimal("9999"),
            amount_due=Decimal("0"), payment_method=Invoice.PaymentMethod.POS,
            status=Invoice.Status.PAID,
        )
        SalePayment.objects.create(
            organisation=other_org, invoice=inv, amount=Decimal("9999"),
            method="pos", received_by=other_user,
        )
        batch = self._batch([self._row("9999", "R1")])
        self.assertEqual(SettlementService.match_batch(batch)["matched"], 0)

    def test_rematching_after_the_sale_is_entered_succeeds(self):
        batch = self._batch([self._row("4500", "R1")])
        self.assertEqual(SettlementService.match_batch(batch)["matched"], 0)
        self._card_payment("4500")
        self.assertEqual(SettlementService.match_batch(batch)["matched"], 1)


class ReviewTests(SettlementTestBase):
    def test_a_human_can_assign_a_payout_to_a_sale(self):
        payment = self._card_payment("8000", when=self.now - timedelta(days=20))
        batch = self._batch([self._row("8000", "R1")])
        SettlementService.match_batch(batch)          # too old to match automatically
        line = batch.lines.first()
        self.assertEqual(line.status, SettlementLine.Status.UNMATCHED)

        SettlementService.assign(line, payment, note="Checked against the terminal")
        line.refresh_from_db()
        self.assertEqual(line.payment_id, payment.id)
        self.assertFalse(line.matched_automatically)

    def test_a_payment_cannot_settle_two_payouts(self):
        payment = self._card_payment("8000", when=self.now - timedelta(days=20))
        batch = self._batch([self._row("8000", "R1"), self._row("8000", "R2")])
        lines = list(batch.lines.all())
        SettlementService.assign(lines[0], payment)
        with self.assertRaises(SettlementError):
            SettlementService.assign(lines[1], payment)

    def test_a_payment_from_another_business_is_refused(self):
        other_user = _user("nosy-settle@example.com")
        other_org = OrganisationService.create_organisation(
            name="Nosy", owner=other_user, extra={"currency": "NGN", "country": "NG"},
        )
        wh = Warehouse.objects.create(organisation=other_org, name="W", is_default=True)
        cust = Customer.objects.create(organisation=other_org, code="X", name="X")
        inv = Invoice.objects.create(
            organisation=other_org, customer=cust, created_by=other_user, warehouse=wh,
            invoice_number="INV-N", issue_date=self.now.date(),
            subtotal=Decimal("100"), total_amount=Decimal("100"), amount_due=Decimal("0"),
            payment_method=Invoice.PaymentMethod.POS, status=Invoice.Status.PAID,
        )
        theirs = SalePayment.objects.create(
            organisation=other_org, invoice=inv, amount=Decimal("100"),
            method="pos", received_by=other_user,
        )
        batch = self._batch([self._row("100", "R1")])
        with self.assertRaises(SettlementError):
            SettlementService.assign(batch.lines.first(), theirs)

    def test_money_with_no_sale_can_be_booked_as_other_income(self):
        batch = self._batch([self._row("2500", "R1")])
        line = batch.lines.first()
        SettlementService.record_as_other_income(line, self.user)

        line.refresh_from_db()
        self.assertEqual(line.status, SettlementLine.Status.OTHER_INCOME)
        bank = Account.objects.get(organisation=self.org, code="1002")
        income = Account.objects.get(organisation=self.org, code="4100")
        self.assertEqual(AccountingService._ledger_balance(bank), Decimal("2500"))
        self.assertEqual(AccountingService._ledger_balance(income), Decimal("2500"))

    def test_the_books_still_balance_after_booking_other_income(self):
        batch = self._batch([self._row("2500", "R1")])
        SettlementService.record_as_other_income(batch.lines.first(), self.user)
        bs = AccountingService.balance_sheet(self.org)
        self.assertTrue(bs["balanced"], msg=str(bs))

    def test_a_matched_payout_cannot_be_booked_as_income(self):
        self._card_payment("2500")
        batch = self._batch([self._row("2500", "R1")])
        SettlementService.match_batch(batch)
        with self.assertRaises(SettlementError):
            SettlementService.record_as_other_income(batch.lines.first(), self.user)

    def test_unmatching_frees_the_payment_again(self):
        payment = self._card_payment("6000")
        batch = self._batch([self._row("6000", "R1")])
        SettlementService.match_batch(batch)
        line = batch.lines.first()

        SettlementService.unmatch(line)
        line.refresh_from_db()
        self.assertIsNone(line.payment_id)
        self.assertEqual(line.status, SettlementLine.Status.UNMATCHED)
        self.assertEqual(SettlementService.match_batch(batch)["matched"], 1)
        self.assertEqual(payment.settlement_lines.count(), 1)

    def test_summary_counts_what_needs_a_human(self):
        self._card_payment("1000")
        batch = self._batch([self._row("1000", "R1"), self._row("7777", "R2")])
        SettlementService.match_batch(batch)
        summary = SettlementService.summary(self.org)
        self.assertEqual(summary["matched"], 1)
        self.assertEqual(summary["needs_review"], 1)
        self.assertEqual(summary["needs_review_total"], Decimal("7777"))


class SettlementApiTests(SettlementTestBase):
    def _upload(self, content, name="settlement.csv"):
        from django.core.files.uploadedfile import SimpleUploadedFile
        return self.client.post(
            "/api/v1/payments/settlement-batches/upload/",
            {"file": SimpleUploadedFile(name, content.encode(), content_type="text/csv"),
             "provider": "Moniepoint"},
            format="multipart",
        )

    def test_uploading_imports_and_matches_in_one_go(self):
        self._card_payment("12400")
        stamp = self.now.strftime("%Y-%m-%d %H:%M:%S")
        res = self._upload(f"Date,Reference,Amount\n{stamp},RRN9,12400\n")
        self.assertEqual(res.status_code, 201, msg=str(res.data))
        self.assertEqual(res.data["line_count"], 1)
        self.assertEqual(res.data["matched"], 1)

    def test_a_raw_text_body_is_accepted(self):
        """The desktop build posts raw text — Tauri turns FormData into
        form-urlencoded and the file never arrives."""
        self._card_payment("3300")
        stamp = self.now.strftime("%Y-%m-%d %H:%M:%S")
        res = self.client.post(
            "/api/v1/payments/settlement-batches/upload/",
            data=f"Date,Reference,Amount\n{stamp},RAW1,3300\n",
            content_type="text/csv",
            HTTP_X_FILE_NAME="terminal.csv",
        )
        self.assertEqual(res.status_code, 201, msg=str(res.data))
        self.assertEqual(res.data["line_count"], 1)
        self.assertEqual(res.data["matched"], 1)

    def test_an_empty_raw_body_is_refused(self):
        res = self.client.post(
            "/api/v1/payments/settlement-batches/upload/",
            data="   ", content_type="text/csv",
        )
        self.assertEqual(res.status_code, 400)

    def test_a_file_with_no_amount_column_returns_a_clear_error(self):
        res = self._upload("Reference,Terminal\nR1,T1\n")
        self.assertEqual(res.status_code, 422)
        self.assertIn("amount column", str(res.data["error"]))

    def test_uploading_nothing_is_refused(self):
        res = self.client.post(
            "/api/v1/payments/settlement-batches/upload/", {}, format="multipart",
        )
        self.assertEqual(res.status_code, 400)

    def test_candidates_lists_unsettled_card_payments_only(self):
        self._card_payment("1500")
        res = self.client.get("/api/v1/payments/settlements/candidates/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.data["results"]), 1)

    def test_summary_endpoint(self):
        self._batch([self._row("999", "R1")])
        res = self.client.get("/api/v1/payments/settlements/summary/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["needs_review"], 1)

    def test_another_business_sees_no_settlements(self):
        self._batch([self._row("999", "R1")])
        other_user = _user("outsider@example.com")
        other_org = OrganisationService.create_organisation(
            name="Outsider", owner=other_user, extra={"currency": "NGN", "country": "NG"},
        )
        outsider = APIClient()
        outsider.credentials(
            HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(other_user).access_token}",
            HTTP_X_ORGANISATION_ID=str(other_org.id),
        )
        res = outsider.get("/api/v1/payments/settlements/")
        self.assertEqual(res.data["count"], 0)

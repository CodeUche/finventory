"""
Till session tests.

The point of a till session is that a shortfall becomes a number in the
accounts. These tests hold that line: the count is blind, the variance is
computed from payments actually taken at that till, and it reaches the ledger.
"""

from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounting.models import Account
from apps.accounting.services import AccountingService
from apps.authentication.models import User
from apps.customers.models import Customer
from apps.inventory.models import Warehouse
from apps.pos.models import TillSession
from apps.pos.till_services import TillService, TillSessionError
from apps.sales.models import Invoice
from apps.sales.services import SaleService
from apps.subscriptions.models import Plan
from apps.subscriptions.services import SubscriptionService
from apps.tenancy.services import OrganisationService


def _user(email):
    return User.objects.create_user(
        email=email, password="TestPass123!", first_name="Till", last_name="User",
        is_verified=True,
    )


class TillTestBase(TestCase):
    def setUp(self):
        self.user = _user("till@example.com")
        self.org = OrganisationService.create_organisation(
            name="Till Org", owner=self.user, extra={"currency": "NGN", "country": "NG"},
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

    def _invoice(self, total="1000"):
        return Invoice.objects.create(
            organisation=self.org, customer=self.customer, created_by=self.user,
            warehouse=self.warehouse,
            invoice_number=f"INV-{Invoice.objects.count() + 1:05d}",
            issue_date="2026-08-01", subtotal=Decimal(total),
            total_amount=Decimal(total), amount_due=Decimal(total),
            payment_method=Invoice.PaymentMethod.CASH, status=Invoice.Status.CONFIRMED,
        )

    def _take(self, amount, method="cash"):
        return SaleService.record_payment(
            invoice=self._invoice(amount), amount=Decimal(amount),
            method=method, received_by=self.user,
        )

    def _gl(self, code):
        acct = Account.objects.filter(organisation=self.org, code=code).first()
        return AccountingService._ledger_balance(acct) if acct else Decimal("0")


class OpeningTests(TillTestBase):
    def test_opening_records_the_float(self):
        session = TillService.open_session(self.org, self.user, "20000", self.warehouse)
        self.assertEqual(session.status, TillSession.Status.OPEN)
        self.assertEqual(session.opening_float, Decimal("20000"))

    def test_a_cashier_cannot_open_two_tills(self):
        TillService.open_session(self.org, self.user, "20000")
        with self.assertRaises(TillSessionError) as ctx:
            TillService.open_session(self.org, self.user, "5000")
        self.assertIn("already have a till open", str(ctx.exception))

    def test_negative_float_is_refused(self):
        with self.assertRaises(TillSessionError):
            TillService.open_session(self.org, self.user, "-100")

    def test_current_session_is_found(self):
        session = TillService.open_session(self.org, self.user, "20000")
        self.assertEqual(TillService.current_session(self.org, self.user), session)

    def test_no_open_session_returns_none(self):
        self.assertIsNone(TillService.current_session(self.org, self.user))


class PaymentAttributionTests(TillTestBase):
    """Payments must attach to the shift that took them."""

    def test_payments_taken_during_a_shift_attach_to_it(self):
        session = TillService.open_session(self.org, self.user, "20000")
        self._take("1000")
        self._take("500", method="pos")
        self.assertEqual(session.payments.count(), 2)

    def test_payments_before_a_shift_are_not_attached(self):
        self._take("900")
        session = TillService.open_session(self.org, self.user, "20000")
        self.assertEqual(session.payments.count(), 0)

    def test_gateway_payments_never_touch_the_drawer(self):
        session = TillService.open_session(self.org, self.user, "20000")
        SaleService.record_payment_from_gateway(
            invoice=self._invoice("2500"), amount=Decimal("2500"),
            reference="REF-1", channel="bank_transfer",
        )
        self.assertEqual(session.payments.count(), 0)
        self.assertEqual(TillService.expected_cash(session), Decimal("20000"))


class ExpectedFigureTests(TillTestBase):
    def test_expected_cash_is_float_plus_cash_taken(self):
        session = TillService.open_session(self.org, self.user, "20000")
        self._take("1500")
        self._take("500")
        self.assertEqual(TillService.expected_cash(session), Decimal("22000"))

    def test_card_and_transfer_do_not_change_expected_cash(self):
        session = TillService.open_session(self.org, self.user, "20000")
        self._take("5000", method="pos")
        self._take("3000", method="bank_transfer")
        self.assertEqual(TillService.expected_cash(session), Decimal("20000"))

    def test_expected_is_broken_down_by_tender(self):
        session = TillService.open_session(self.org, self.user, "20000")
        self._take("1000")
        self._take("2000", method="pos")
        self._take("500", method="pos")
        by_tender = TillService.expected_by_tender(session)
        self.assertEqual(by_tender["cash"]["expected"], Decimal("1000"))
        self.assertEqual(by_tender["pos"]["expected"], Decimal("2500"))
        self.assertEqual(by_tender["pos"]["count"], 2)


class ClosingTests(TillTestBase):
    def test_a_matching_count_closes_with_no_variance(self):
        session = TillService.open_session(self.org, self.user, "20000")
        self._take("1000")
        TillService.close_session(session, self.user, {"cash": "21000"})
        session.refresh_from_db()
        self.assertEqual(session.status, TillSession.Status.CLOSED)
        self.assertEqual(session.cash_variance, Decimal("0"))

    def test_a_short_drawer_records_a_negative_variance(self):
        session = TillService.open_session(self.org, self.user, "20000")
        self._take("1000")
        TillService.close_session(session, self.user, {"cash": "20700"}, reason="Short")
        session.refresh_from_db()
        self.assertEqual(session.cash_variance, Decimal("-300"))
        self.assertEqual(session.variance_reason, "Short")

    def test_an_over_drawer_records_a_positive_variance(self):
        session = TillService.open_session(self.org, self.user, "20000")
        self._take("1000")
        TillService.close_session(session, self.user, {"cash": "21250"})
        session.refresh_from_db()
        self.assertEqual(session.cash_variance, Decimal("250"))

    def test_closing_without_counting_cash_is_refused(self):
        """The whole point is the count — closing blind-of-the-blind-count is not allowed."""
        session = TillService.open_session(self.org, self.user, "20000")
        with self.assertRaises(TillSessionError) as ctx:
            TillService.close_session(session, self.user, {})
        self.assertIn("cash you counted", str(ctx.exception))

    def test_a_till_cannot_be_closed_twice(self):
        session = TillService.open_session(self.org, self.user, "20000")
        TillService.close_session(session, self.user, {"cash": "20000"})
        with self.assertRaises(TillSessionError):
            TillService.close_session(session, self.user, {"cash": "20000"})

    def test_uncounted_tenders_are_taken_as_agreeing(self):
        session = TillService.open_session(self.org, self.user, "20000")
        self._take("4000", method="pos")
        TillService.close_session(session, self.user, {"cash": "20000"})
        pos_row = session.tender_counts.get(method="pos")
        self.assertEqual(pos_row.expected, Decimal("4000"))
        self.assertEqual(pos_row.variance, Decimal("0"))

    def test_every_tender_is_recorded_for_the_report(self):
        session = TillService.open_session(self.org, self.user, "20000")
        self._take("1000")
        self._take("2000", method="pos")
        TillService.close_session(session, self.user, {"cash": "21000", "pos": "2000"})
        self.assertEqual(
            set(session.tender_counts.values_list("method", flat=True)), {"cash", "pos"},
        )

    def test_closing_a_till_stops_new_payments_attaching(self):
        session = TillService.open_session(self.org, self.user, "20000")
        TillService.close_session(session, self.user, {"cash": "20000"})
        self._take("1000")
        self.assertEqual(session.payments.count(), 0)


class VarianceLedgerTests(TillTestBase):
    """A shortfall has to be a real number in the accounts."""

    def test_a_shortage_debits_cash_over_and_short(self):
        session = TillService.open_session(self.org, self.user, "20000")
        self._take("1000")
        cash_before = self._gl("1001")
        TillService.close_session(session, self.user, {"cash": "20700"}, reason="Short")

        self.assertEqual(self._gl("6800"), Decimal("300"))       # DR expense
        self.assertEqual(self._gl("1001"), cash_before - Decimal("300"))  # CR cash

    def test_an_overage_credits_cash_over_and_short(self):
        session = TillService.open_session(self.org, self.user, "20000")
        self._take("1000")
        cash_before = self._gl("1001")
        TillService.close_session(session, self.user, {"cash": "21300"})

        self.assertEqual(self._gl("6800"), Decimal("-300"))      # CR expense
        self.assertEqual(self._gl("1001"), cash_before + Decimal("300"))

    def test_no_variance_posts_no_journal(self):
        from apps.accounting.models import JournalEntry
        session = TillService.open_session(self.org, self.user, "20000")
        self._take("1000")
        TillService.close_session(session, self.user, {"cash": "21000"})
        self.assertFalse(
            JournalEntry.objects.filter(organisation=self.org, source_type="till_variance").exists()
        )

    def test_the_books_still_balance_after_a_variance(self):
        session = TillService.open_session(self.org, self.user, "20000")
        self._take("1000")
        TillService.close_session(session, self.user, {"cash": "20500"})
        bs = AccountingService.balance_sheet(self.org)
        self.assertTrue(bs["balanced"], msg=str(bs))


class VarianceNotSilentlyLostTests(TillTestBase):
    """Closing must never be blocked — but an unposted shortfall must never hide.

    The trade-off is deliberate: a cashier has to be able to go home. These
    tests make sure the cost of that is visible and recoverable rather than
    silent.
    """

    def _fail_posting(self):
        """Simulate the ledger refusing the entry (locked period, bad mapping…)."""
        from unittest.mock import patch
        return patch(
            "apps.pos.till_services.TillService._post_variance_journal",
            side_effect=RuntimeError("period is locked"),
        )

    def test_a_failed_posting_still_lets_the_cashier_close(self):
        session = TillService.open_session(self.org, self.user, "20000")
        self._take("1000")
        with self._fail_posting():
            TillService.close_session(session, self.user, {"cash": "20700"})
        session.refresh_from_db()
        self.assertEqual(session.status, TillSession.Status.CLOSED)
        self.assertEqual(session.cash_variance, Decimal("-300"))

    def test_a_failed_posting_is_recorded_not_just_logged(self):
        session = TillService.open_session(self.org, self.user, "20000")
        self._take("1000")
        with self._fail_posting():
            TillService.close_session(session, self.user, {"cash": "20700"})
        session.refresh_from_db()
        self.assertEqual(session.gl_post_status, "failed")
        self.assertIn("period is locked", session.gl_post_error)

    def test_a_successful_posting_is_marked_posted(self):
        session = TillService.open_session(self.org, self.user, "20000")
        self._take("1000")
        TillService.close_session(session, self.user, {"cash": "20700"})
        session.refresh_from_db()
        self.assertEqual(session.gl_post_status, "posted")

    def test_a_balanced_till_is_not_left_looking_unposted(self):
        session = TillService.open_session(self.org, self.user, "20000")
        self._take("1000")
        TillService.close_session(session, self.user, {"cash": "21000"})
        session.refresh_from_db()
        self.assertEqual(session.gl_post_status, "posted")

    def test_an_unposted_shortfall_appears_on_gl_health(self):
        session = TillService.open_session(self.org, self.user, "20000")
        self._take("1000")
        with self._fail_posting():
            TillService.close_session(session, self.user, {"cash": "20700"})

        health = AccountingService.get_gl_health(self.org)
        tills = [f for f in health["failures"] if f["model"] == "till"]
        self.assertEqual(len(tills), 1)
        self.assertIn("period is locked", tills[0]["error"])

    def test_it_can_be_retried_once_the_problem_is_fixed(self):
        session = TillService.open_session(self.org, self.user, "20000")
        self._take("1000")
        with self._fail_posting():
            TillService.close_session(session, self.user, {"cash": "20700"})

        success, err = AccountingService.retry_gl_post(
            self.org, "till", str(session.id), self.user,
        )
        self.assertTrue(success, msg=err)
        session.refresh_from_db()
        self.assertEqual(session.gl_post_status, "posted")
        self.assertEqual(self._gl("6800"), Decimal("300"))

    def test_retry_all_picks_up_a_failed_till(self):
        session = TillService.open_session(self.org, self.user, "20000")
        self._take("1000")
        with self._fail_posting():
            TillService.close_session(session, self.user, {"cash": "20700"})

        res = self.client.post("/api/v1/accounting/gl-health/retry-all/")
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        self.assertGreaterEqual(res.data["succeeded"], 1)
        session.refresh_from_db()
        self.assertEqual(session.gl_post_status, "posted")

    def test_reconciliation_catches_a_variance_that_never_reached_the_ledger(self):
        """The safety net: this holds even if the status flag were wrong."""
        session = TillService.open_session(self.org, self.user, "20000")
        self._take("1000")
        with self._fail_posting():
            TillService.close_session(session, self.user, {"cash": "20700"})

        recon = AccountingService.gl_health_reconciliations(self.org)
        till_row = next(r for r in recon["subledgers"] if "Till" in r["name"])
        self.assertFalse(till_row["reconciled"])
        self.assertEqual(till_row["variance"], Decimal("-300"))
        self.assertFalse(recon["all_reconciled"])

    def test_reconciliation_agrees_once_the_variance_is_posted(self):
        session = TillService.open_session(self.org, self.user, "20000")
        self._take("1000")
        TillService.close_session(session, self.user, {"cash": "20700"})

        recon = AccountingService.gl_health_reconciliations(self.org)
        till_row = next(r for r in recon["subledgers"] if "Till" in r["name"])
        self.assertTrue(till_row["reconciled"], msg=str(till_row))


class ZReportTests(TillTestBase):
    def test_report_summarises_the_shift(self):
        session = TillService.open_session(self.org, self.user, "20000", self.warehouse)
        self._take("1000")
        self._take("4000", method="pos")
        TillService.close_session(session, self.user, {"cash": "20800", "pos": "4000"})

        report = TillService.z_report(session)
        self.assertEqual(report["opening_float"], Decimal("20000"))
        self.assertEqual(report["sales_total"], Decimal("5000"))
        self.assertEqual(report["cash_variance"], Decimal("-200"))
        self.assertEqual(report["location"], "Main")
        self.assertEqual(len(report["tenders"]), 2)


class TillApiTests(TillTestBase):
    def test_open_close_and_report_through_the_api(self):
        res = self.client.post("/api/v1/pos/till-sessions/open/",
                               {"opening_float": "20000"}, format="json")
        self.assertEqual(res.status_code, 201, msg=str(res.data))
        session_id = res.data["id"]

        self._take("1000")

        current = self.client.get("/api/v1/pos/till-sessions/current/")
        self.assertTrue(current.data["open"])
        self.assertEqual(Decimal(str(current.data["expected_cash"])), Decimal("21000"))

        closed = self.client.post(
            f"/api/v1/pos/till-sessions/{session_id}/close/",
            {"counted": {"cash": "20900"}, "reason": "Short by 100"}, format="json",
        )
        self.assertEqual(closed.status_code, 200, msg=str(closed.data))
        self.assertEqual(Decimal(str(closed.data["cash_variance"])), Decimal("-100"))

    def test_current_reports_no_open_till(self):
        res = self.client.get("/api/v1/pos/till-sessions/current/")
        self.assertFalse(res.data["open"])

    def test_opening_twice_returns_a_clear_error(self):
        self.client.post("/api/v1/pos/till-sessions/open/", {"opening_float": "1"}, format="json")
        res = self.client.post("/api/v1/pos/till-sessions/open/", {"opening_float": "1"}, format="json")
        self.assertEqual(res.status_code, 422)
        self.assertIn("already have a till open", str(res.data["error"]))

    def test_closing_without_a_cash_count_is_refused_by_the_api(self):
        opened = self.client.post(
            "/api/v1/pos/till-sessions/open/", {"opening_float": "0"}, format="json",
        )
        res = self.client.post(
            f"/api/v1/pos/till-sessions/{opened.data['id']}/close/",
            {"counted": {}}, format="json",
        )
        self.assertEqual(res.status_code, 422)

    def test_z_report_endpoint(self):
        opened = self.client.post(
            "/api/v1/pos/till-sessions/open/", {"opening_float": "5000"}, format="json",
        )
        self.client.post(
            f"/api/v1/pos/till-sessions/{opened.data['id']}/close/",
            {"counted": {"cash": "5000"}}, format="json",
        )
        res = self.client.get(f"/api/v1/pos/till-sessions/{opened.data['id']}/z_report/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(Decimal(str(res.data["opening_float"])), Decimal("5000"))

    def test_another_cashiers_till_is_not_visible(self):
        """Tenancy: a till belongs to one organisation only."""
        other_user = _user("other@example.com")
        other_org = OrganisationService.create_organisation(
            name="Other Org", owner=other_user, extra={"currency": "NGN", "country": "NG"},
        )
        TillService.open_session(other_org, other_user, "999")
        res = self.client.get("/api/v1/pos/till-sessions/")
        results = res.data.get("results", res.data)
        self.assertEqual(len(results), 0)

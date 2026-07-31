"""
Payment collection tests.

Covers the three ways a merchant can be paid — hosted checkout, a one-time
account number, and a transfer into the merchant's own account — and the two
things that must never go wrong: money recorded twice, or money landing in the
wrong ledger account.
"""

import hashlib
import hmac
import json
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounting.models import Account, AccountMapping
from apps.accounting.services import AccountingService
from apps.authentication.models import User
from apps.customers.models import Customer
from apps.inventory.models import Product, Warehouse
from apps.payments.models import (
    BankTransferClaim, MerchantBankAccount, PaymentEventLog, PaymentGatewayConfig,
    PaymentLink, VirtualAccount,
)
from apps.payments.providers import PaymentProviderError
from apps.payments.providers.base import (
    CheckoutSession, PaymentEvent, VirtualAccountDetails,
)
from apps.payments.services import PaymentService
from apps.sales.models import Invoice
from apps.sales.services import SaleService
from apps.subscriptions.models import Plan
from apps.subscriptions.services import SubscriptionService
from apps.tenancy.services import OrganisationService


def _user(email="pay@example.com"):
    return User.objects.create_user(
        email=email, password="TestPass123!", first_name="Pay", last_name="Tester",
        is_verified=True,
    )


def _org(user, name="Pay Org"):
    org = OrganisationService.create_organisation(
        name=name, owner=user, extra={"currency": "NGN", "country": "NG"},
    )
    SubscriptionService.upgrade_plan(org, Plan.objects.get(slug="business"))
    org.refresh_from_db()
    return org


def _client(user, org):
    client = APIClient()
    client.credentials(
        HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}",
        HTTP_X_ORGANISATION_ID=str(org.id),
    )
    return client


class PaymentTestBase(TestCase):
    def setUp(self):
        self.user = _user()
        self.org = _org(self.user)
        self.client = _client(self.user, self.org)
        self.customer = Customer.objects.create(
            organisation=self.org, code="C1", name="Ada Buyer", email="ada@example.com",
        )
        self.warehouse = Warehouse.objects.create(
            organisation=self.org, name="Main", is_default=True,
        )
        self.product = Product.objects.create(
            organisation=self.org, sku="P1", name="Widget",
            cost_price=Decimal("400"), selling_price=Decimal("1000"),
        )
        self.config = PaymentGatewayConfig.objects.create(
            organisation=self.org, provider="paystack", public_key="pk_test",
            secret_key="sk_test", webhook_secret="whsec", is_active=True,
        )

    def _invoice(self, total="1000", credit=False):
        """An unpaid invoice — the state a storefront order or payment link starts in."""
        return Invoice.objects.create(
            organisation=self.org,
            customer=self.customer,
            created_by=self.user,
            warehouse=self.warehouse,
            invoice_number=f"INV-{Invoice.objects.count() + 1:05d}",
            issue_date="2026-08-01",
            subtotal=Decimal(total),
            total_amount=Decimal(total),
            amount_due=Decimal(total),
            payment_method=Invoice.PaymentMethod.CREDIT if credit else Invoice.PaymentMethod.CASH,
            status=Invoice.Status.CONFIRMED,
        )

    def _event(self, reference, amount="1000", event_id="evt_1", status="success",
               channel="bank_transfer"):
        return PaymentEvent(
            event_id=event_id, reference=reference, amount=Decimal(amount),
            status=status, channel=channel, raw={"id": event_id},
        )

    def _gl(self, code):
        return AccountingService._ledger_balance(
            Account.objects.get(organisation=self.org, code=code)
        )


class GatewayPaymentRecordingTests(PaymentTestBase):
    """SaleService.record_payment_from_gateway — the routine that never existed."""

    def test_gateway_payment_marks_invoice_paid(self):
        invoice = self._invoice()
        SaleService.record_payment_from_gateway(
            invoice=invoice, amount=Decimal("1000"), reference="REF-1",
            channel="bank_transfer", provider="paystack",
        )
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, Invoice.Status.PAID)
        self.assertEqual(invoice.amount_due, Decimal("0"))

    def test_transfer_lands_in_bank_not_cash(self):
        """A transfer posted to cash would make the till count unreconcilable."""
        invoice = self._invoice()
        cash_before = self._gl("1001")
        SaleService.record_payment_from_gateway(
            invoice=invoice, amount=Decimal("1000"), reference="REF-2",
            channel="bank_transfer",
        )
        self.assertEqual(self._gl("1001"), cash_before)
        self.assertEqual(self._gl("1002"), Decimal("1000"))

    def test_card_payment_also_lands_in_bank(self):
        invoice = self._invoice()
        SaleService.record_payment_from_gateway(
            invoice=invoice, amount=Decimal("1000"), reference="REF-3", channel="card",
        )
        self.assertEqual(self._gl("1002"), Decimal("1000"))

    def test_partial_gateway_payment_leaves_balance_outstanding(self):
        invoice = self._invoice(total="1000")
        SaleService.record_payment_from_gateway(
            invoice=invoice, amount=Decimal("400"), reference="REF-4",
        )
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, Invoice.Status.PARTIALLY_PAID)
        self.assertEqual(invoice.amount_due, Decimal("600"))

    def test_unknown_channel_falls_back_to_transfer(self):
        invoice = self._invoice()
        payment = SaleService.record_payment_from_gateway(
            invoice=invoice, amount=Decimal("1000"), reference="REF-5", channel="qr_weirdness",
        )
        self.assertEqual(payment.method, "bank_transfer")


class WebhookReplayTests(PaymentTestBase):
    """Providers resend webhooks. Nothing may be recorded twice."""

    def test_same_event_delivered_twice_pays_once(self):
        invoice = self._invoice()
        link = PaymentLink.objects.create(
            organisation=self.org, invoice=invoice, provider="paystack",
            payment_reference="REF-DUP", amount=Decimal("1000"),
            link_url="https://example.test/pay",
        )
        event = self._event("REF-DUP", event_id="evt_dup")

        first = PaymentService.settle(self.org, "paystack", event)
        second = PaymentService.settle(self.org, "paystack", event)

        self.assertEqual(first, "settled")
        self.assertEqual(second, "duplicate")
        invoice.refresh_from_db()
        self.assertEqual(invoice.amount_paid, Decimal("1000"))
        self.assertEqual(invoice.payments.count(), 1)
        link.refresh_from_db()
        self.assertEqual(link.status, PaymentLink.PAID)

    def test_distinct_events_for_a_settled_invoice_do_not_overpay(self):
        """A provider retrying under a fresh event id must not double-charge."""
        invoice = self._invoice()
        PaymentLink.objects.create(
            organisation=self.org, invoice=invoice, provider="paystack",
            payment_reference="REF-TWICE", amount=Decimal("1000"),
            link_url="https://example.test/pay",
        )
        PaymentService.settle(self.org, "paystack", self._event("REF-TWICE", event_id="e1"))
        outcome = PaymentService.settle(self.org, "paystack", self._event("REF-TWICE", event_id="e2"))

        self.assertEqual(outcome, "already settled")
        invoice.refresh_from_db()
        self.assertEqual(invoice.amount_paid, Decimal("1000"))

    def test_every_event_is_logged_for_support(self):
        invoice = self._invoice()
        PaymentLink.objects.create(
            organisation=self.org, invoice=invoice, provider="paystack",
            payment_reference="REF-LOG", amount=Decimal("1000"),
            link_url="https://example.test/pay",
        )
        PaymentService.settle(self.org, "paystack", self._event("REF-LOG", event_id="e_log"))
        self.assertTrue(
            PaymentEventLog.objects.filter(provider="paystack", event_id="e_log").exists()
        )

    def test_unattributable_payment_is_flagged_not_guessed(self):
        outcome = PaymentService.settle(
            self.org, "paystack", self._event("REF-NOBODY", event_id="e_orphan"),
        )
        self.assertEqual(outcome, "no matching invoice — needs review")

    def test_failed_event_marks_the_link_failed_without_paying(self):
        invoice = self._invoice()
        link = PaymentLink.objects.create(
            organisation=self.org, invoice=invoice, provider="paystack",
            payment_reference="REF-FAIL", amount=Decimal("1000"),
            link_url="https://example.test/pay",
        )
        outcome = PaymentService.settle(
            self.org, "paystack", self._event("REF-FAIL", event_id="e_f", status="failed"),
        )
        self.assertEqual(outcome, "payment failed")
        link.refresh_from_db()
        self.assertEqual(link.status, PaymentLink.FAILED)
        invoice.refresh_from_db()
        self.assertEqual(invoice.amount_paid, Decimal("0"))

    def test_overpayment_applies_only_what_is_owed(self):
        invoice = self._invoice(total="1000")
        PaymentLink.objects.create(
            organisation=self.org, invoice=invoice, provider="paystack",
            payment_reference="REF-OVER", amount=Decimal("1000"),
            link_url="https://example.test/pay",
        )
        outcome = PaymentService.settle(
            self.org, "paystack", self._event("REF-OVER", amount="1500", event_id="e_over"),
        )
        self.assertIn("overpaid", outcome)
        invoice.refresh_from_db()
        self.assertEqual(invoice.amount_paid, Decimal("1000"))


class VirtualAccountTests(PaymentTestBase):
    """One-time account numbers — the answer to fake transfer alerts."""

    def _details(self, reference):
        return VirtualAccountDetails(
            account_number="9021334870", bank_name="Wema Bank",
            account_name="Ada Buyer", reference=reference,
            provider_reference="pv_1", raw={},
        )

    def test_issuing_an_account_stores_the_details(self):
        invoice = self._invoice()
        with patch("apps.payments.providers.paystack.PaystackProvider.create_virtual_account",
                   side_effect=lambda **kw: self._details(kw["reference"])):
            account = PaymentService.create_virtual_account(invoice)
        self.assertEqual(account.account_number, "9021334870")
        self.assertEqual(account.status, VirtualAccount.PENDING)
        self.assertIsNotNone(account.expires_at)

    def test_refreshing_checkout_reuses_the_same_account(self):
        """Otherwise every page refresh burns a new account number."""
        invoice = self._invoice()
        with patch("apps.payments.providers.paystack.PaystackProvider.create_virtual_account",
                   side_effect=lambda **kw: self._details(kw["reference"])):
            first = PaymentService.create_virtual_account(invoice)
            second = PaymentService.create_virtual_account(invoice)
        self.assertEqual(first.id, second.id)
        self.assertEqual(VirtualAccount.objects.filter(invoice=invoice).count(), 1)

    def test_transfer_into_the_account_settles_the_invoice(self):
        invoice = self._invoice()
        with patch("apps.payments.providers.paystack.PaystackProvider.create_virtual_account",
                   side_effect=lambda **kw: self._details(kw["reference"])):
            account = PaymentService.create_virtual_account(invoice)

        outcome = PaymentService.settle(
            self.org, "paystack", self._event(account.reference, event_id="e_va"),
        )
        self.assertEqual(outcome, "settled")
        account.refresh_from_db(); invoice.refresh_from_db()
        self.assertEqual(account.status, VirtualAccount.PAID)
        self.assertEqual(invoice.status, Invoice.Status.PAID)

    def test_notification_carrying_only_the_account_number_still_matches(self):
        """Some transfer alerts identify the account, not our reference."""
        invoice = self._invoice()
        with patch("apps.payments.providers.paystack.PaystackProvider.create_virtual_account",
                   side_effect=lambda **kw: self._details(kw["reference"])):
            account = PaymentService.create_virtual_account(invoice)

        outcome = PaymentService.settle(
            self.org, "paystack", self._event("9021334870", event_id="e_acct"),
        )
        self.assertEqual(outcome, "settled")
        account.refresh_from_db()
        self.assertEqual(account.status, VirtualAccount.PAID)

    def test_expired_accounts_are_swept(self):
        invoice = self._invoice()
        with patch("apps.payments.providers.paystack.PaystackProvider.create_virtual_account",
                   side_effect=lambda **kw: self._details(kw["reference"])):
            account = PaymentService.create_virtual_account(invoice)
        from django.utils import timezone
        from datetime import timedelta
        account.expires_at = timezone.now() - timedelta(minutes=1)
        account.save(update_fields=["expires_at"])

        self.assertTrue(account.is_expired)
        PaymentService.expire_stale_accounts(self.org)
        account.refresh_from_db()
        self.assertEqual(account.status, VirtualAccount.EXPIRED)

    def test_transfer_switched_off_is_refused_clearly(self):
        self.config.allow_transfer = False
        self.config.save(update_fields=["allow_transfer"])
        with self.assertRaises(PaymentProviderError):
            PaymentService.create_virtual_account(self._invoice())


class CheckoutLinkTests(PaymentTestBase):
    """The payment link must come from the provider, never be fabricated."""

    def test_link_is_taken_from_the_provider_response(self):
        invoice = self._invoice()
        session = CheckoutSession(
            reference="AUD-X", url="https://checkout.paystack.com/abc123",
            provider_reference="acc_1", raw={},
        )
        with patch("apps.payments.providers.paystack.PaystackProvider.initialize_checkout",
                   return_value=session):
            link = PaymentService.create_payment_link(invoice)
        self.assertEqual(link.link_url, "https://checkout.paystack.com/abc123")
        self.assertEqual(link.payment_reference, "AUD-X")

    def test_no_active_provider_is_a_clear_message(self):
        self.config.is_active = False
        self.config.save(update_fields=["is_active"])
        with self.assertRaises(PaymentProviderError) as ctx:
            PaymentService.create_payment_link(self._invoice())
        self.assertIn("Settings", str(ctx.exception))

    def test_nothing_to_pay_is_refused(self):
        invoice = self._invoice()
        invoice.amount_due = Decimal("0")
        invoice.save(update_fields=["amount_due"])
        with self.assertRaises(PaymentProviderError):
            PaymentService.create_payment_link(invoice)


class MerchantBankTransferTests(PaymentTestBase):
    """The merchant's own account — no provider, so a person confirms it."""

    def setUp(self):
        super().setUp()
        self.account = MerchantBankAccount.objects.create(
            organisation=self.org, bank_name="GTBank", account_number="0123456789",
            account_name="Kate's Stores", is_default=True,
        )

    def test_claim_does_not_pay_the_invoice_on_its_own(self):
        """A customer's word is not payment — this is the fake-alert case."""
        invoice = self._invoice()
        PaymentService.claim_bank_transfer(invoice, payer_name="Ada")
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, Invoice.Status.CONFIRMED)
        self.assertEqual(invoice.amount_paid, Decimal("0"))

    def test_confirming_records_the_payment_in_bank(self):
        invoice = self._invoice()
        claim = PaymentService.claim_bank_transfer(invoice)
        PaymentService.confirm_bank_transfer(claim, self.user)

        invoice.refresh_from_db(); claim.refresh_from_db()
        self.assertEqual(claim.status, BankTransferClaim.CONFIRMED)
        self.assertEqual(invoice.status, Invoice.Status.PAID)
        self.assertEqual(self._gl("1002"), Decimal("1000"))

    def test_confirming_twice_pays_once(self):
        invoice = self._invoice()
        claim = PaymentService.claim_bank_transfer(invoice)
        PaymentService.confirm_bank_transfer(claim, self.user)
        PaymentService.confirm_bank_transfer(claim, self.user)

        invoice.refresh_from_db()
        self.assertEqual(invoice.amount_paid, Decimal("1000"))
        self.assertEqual(invoice.payments.count(), 1)

    def test_rejecting_leaves_the_invoice_unpaid(self):
        invoice = self._invoice()
        claim = PaymentService.claim_bank_transfer(invoice)
        PaymentService.reject_bank_transfer(claim, self.user, note="Nothing received")
        invoice.refresh_from_db(); claim.refresh_from_db()
        self.assertEqual(claim.status, BankTransferClaim.REJECTED)
        self.assertEqual(invoice.amount_paid, Decimal("0"))

    def test_a_confirmed_transfer_cannot_then_be_rejected(self):
        invoice = self._invoice()
        claim = PaymentService.claim_bank_transfer(invoice)
        PaymentService.confirm_bank_transfer(claim, self.user)
        with self.assertRaises(PaymentProviderError):
            PaymentService.reject_bank_transfer(claim, self.user)

    def test_only_one_default_account_survives(self):
        second = MerchantBankAccount.objects.create(
            organisation=self.org, bank_name="Zenith", account_number="9876543210",
            account_name="Kate's Stores", is_default=True,
        )
        self.account.refresh_from_db()
        self.assertTrue(second.is_default)
        self.assertFalse(self.account.is_default)


class PaymentOptionsTests(PaymentTestBase):
    """Checkout offers exactly what the merchant has configured."""

    def test_options_reflect_provider_and_bank_setup(self):
        options = PaymentService.payment_options(self.org)
        self.assertTrue(options["card"])
        self.assertTrue(options["virtual_account"])
        self.assertFalse(options["bank_transfer"])

        MerchantBankAccount.objects.create(
            organisation=self.org, bank_name="GTBank", account_number="0123456789",
            account_name="Kate's Stores",
        )
        self.assertTrue(PaymentService.payment_options(self.org)["bank_transfer"])

    def test_merchant_with_no_provider_can_still_take_transfers(self):
        self.config.delete()
        MerchantBankAccount.objects.create(
            organisation=self.org, bank_name="GTBank", account_number="0123456789",
            account_name="Kate's Stores",
        )
        options = PaymentService.payment_options(self.org)
        self.assertFalse(options["card"])
        self.assertFalse(options["virtual_account"])
        self.assertTrue(options["bank_transfer"])

    def test_options_endpoint(self):
        res = self.client.get("/api/v1/payments/options/")
        self.assertEqual(res.status_code, 200)
        self.assertIn("card", res.data)


class WebhookEndpointTests(PaymentTestBase):
    """End-to-end through the HTTP webhook, including signature checking."""

    def _post(self, payload, secret="whsec"):
        body = json.dumps(payload)
        signature = hmac.new(
            secret.encode(), msg=body.encode(), digestmod=hashlib.sha512,
        ).hexdigest()
        return self.client.post(
            "/api/v1/payments/webhook/paystack/", data=body,
            content_type="application/json", HTTP_X_PAYSTACK_SIGNATURE=signature,
        )

    def _payload(self, reference, amount_kobo=100000, event_id=987):
        return {
            "event": "charge.success",
            "data": {
                "id": event_id, "reference": reference, "amount": amount_kobo,
                "currency": "NGN", "channel": "card",
                "metadata": {"org_id": str(self.org.id)},
            },
        }

    def test_signed_webhook_settles_the_invoice(self):
        invoice = self._invoice()
        PaymentLink.objects.create(
            organisation=self.org, invoice=invoice, provider="paystack",
            payment_reference="REF-HTTP", amount=Decimal("1000"),
            link_url="https://example.test/pay",
        )
        res = self._post(self._payload("REF-HTTP"))
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, Invoice.Status.PAID)

    def test_wrong_signature_is_rejected_and_nothing_is_paid(self):
        invoice = self._invoice()
        PaymentLink.objects.create(
            organisation=self.org, invoice=invoice, provider="paystack",
            payment_reference="REF-BAD", amount=Decimal("1000"),
            link_url="https://example.test/pay",
        )
        res = self._post(self._payload("REF-BAD"), secret="wrong-secret")
        self.assertEqual(res.status_code, 400)
        invoice.refresh_from_db()
        self.assertEqual(invoice.amount_paid, Decimal("0"))

    def test_unsigned_webhook_is_rejected(self):
        res = self.client.post(
            "/api/v1/payments/webhook/paystack/",
            data=json.dumps(self._payload("REF-X")), content_type="application/json",
        )
        self.assertEqual(res.status_code, 400)

    def test_replayed_http_delivery_pays_once(self):
        invoice = self._invoice()
        PaymentLink.objects.create(
            organisation=self.org, invoice=invoice, provider="paystack",
            payment_reference="REF-RETRY", amount=Decimal("1000"),
            link_url="https://example.test/pay",
        )
        payload = self._payload("REF-RETRY")
        self._post(payload)
        self._post(payload)
        invoice.refresh_from_db()
        self.assertEqual(invoice.amount_paid, Decimal("1000"))
        self.assertEqual(invoice.payments.count(), 1)


class TenderAccountMappingTests(PaymentTestBase):
    """Where each tender lands in the ledger."""

    def test_cash_goes_to_the_drawer_and_transfer_to_the_bank(self):
        cash = AccountingService.tender_asset_account(self.org, "cash")
        bank = AccountingService.tender_asset_account(self.org, "bank_transfer")
        card = AccountingService.tender_asset_account(self.org, "card")
        pos = AccountingService.tender_asset_account(self.org, "pos")
        self.assertEqual(cash.code, "1001")
        self.assertEqual(bank.code, "1002")
        self.assertEqual(card.code, "1002")
        self.assertEqual(pos.code, "1002")

    def test_credit_customer_paying_by_transfer_credits_bank(self):
        from apps.credits.services import CreditService
        CreditService.record_payment(
            self.org, self.customer, Decimal("500"), self.user, method="bank_transfer",
        )
        self.assertEqual(self._gl("1002"), Decimal("500"))
        self.assertEqual(self._gl("1001"), Decimal("0"))

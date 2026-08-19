"""
Payment orchestration.

Two collection methods, one settlement path:

  * hosted checkout   → PaymentLink     (card, USSD, the provider's own page)
  * one-time account  → VirtualAccount  (transfer from any bank)

Both end at :meth:`PaymentService.settle`, which records the payment against the
invoice and posts it to the ledger exactly once however many times the provider
resends the notification.
"""

from __future__ import annotations

import logging
import secrets
from datetime import timedelta
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import (
    BankTransferClaim, MerchantBankAccount, PaymentEventLog, PaymentGatewayConfig,
    PaymentLink, VirtualAccount,
)
from .providers import PaymentProviderError, get_provider

logger = logging.getLogger(__name__)


class PaymentService:
    # ── Configuration ───────────────────────────────────────────────────────
    @staticmethod
    def active_config(organisation, provider=None) -> PaymentGatewayConfig:
        qs = PaymentGatewayConfig.objects.filter(organisation=organisation, is_active=True)
        if provider:
            qs = qs.filter(provider=provider)
        config = qs.first()
        if config is None:
            raise PaymentProviderError(
                "No active payment provider. Add your gateway keys in "
                "Settings → Payment Gateways."
            )
        return config

    @staticmethod
    def _reference(invoice) -> str:
        return f"AUD-{invoice.invoice_number}-{secrets.token_hex(5).upper()}"

    @staticmethod
    def _customer_bits(invoice):
        customer = getattr(invoice, "customer", None)
        return (
            getattr(customer, "name", "") or "Customer",
            getattr(customer, "email", "") or "",
        )

    # ── Hosted checkout ─────────────────────────────────────────────────────
    @staticmethod
    def create_payment_link(invoice, config=None, callback_url="") -> PaymentLink:
        config = config or PaymentService.active_config(invoice.organisation)
        if not config.allow_card:
            raise PaymentProviderError("Card payments are switched off for this business.")
        amount = Decimal(str(invoice.amount_due or 0))
        if amount <= 0:
            raise PaymentProviderError("This invoice has nothing left to pay.")

        provider = get_provider(config)
        reference = PaymentService._reference(invoice)
        name, email = PaymentService._customer_bits(invoice)

        session = provider.initialize_checkout(
            reference=reference,
            amount=amount,
            email=email,
            callback_url=callback_url,
            metadata={
                "org_id": str(invoice.organisation_id),
                "invoice_id": str(invoice.id),
                "invoice_number": invoice.invoice_number,
                "customer_name": name,
                "description": f"Invoice {invoice.invoice_number}",
            },
        )
        return PaymentLink.objects.create(
            organisation=invoice.organisation,
            invoice=invoice,
            provider=config.provider,
            payment_reference=session.reference,
            amount=amount,
            link_url=session.url,
            gateway_response=session.raw,
        )

    # ── One-time account number ─────────────────────────────────────────────
    @staticmethod
    def create_virtual_account(invoice, config=None) -> VirtualAccount:
        config = config or PaymentService.active_config(invoice.organisation)
        if not config.allow_transfer:
            raise PaymentProviderError("Bank transfers are switched off for this business.")
        amount = Decimal(str(invoice.amount_due or 0))
        if amount <= 0:
            raise PaymentProviderError("This invoice has nothing left to pay.")

        # Reuse an account already issued for this invoice and still valid, so
        # refreshing the checkout page doesn't burn a new account each time.
        existing = (
            VirtualAccount.objects
            .filter(organisation=invoice.organisation, invoice=invoice, status=VirtualAccount.PENDING)
            .order_by("-created_at").first()
        )
        if existing and not existing.is_expired and Decimal(str(existing.amount)) == amount:
            return existing
        if existing and existing.is_expired:
            existing.status = VirtualAccount.EXPIRED
            existing.save(update_fields=["status", "updated_at"])

        provider = get_provider(config)
        reference = PaymentService._reference(invoice)
        name, email = PaymentService._customer_bits(invoice)

        details = provider.create_virtual_account(
            reference=reference,
            amount=amount,
            customer_name=name,
            customer_email=email,
            metadata={
                "org_id": str(invoice.organisation_id),
                "invoice_id": str(invoice.id),
                "invoice_number": invoice.invoice_number,
            },
        )
        minutes = config.virtual_account_minutes or 30
        return VirtualAccount.objects.create(
            organisation=invoice.organisation,
            invoice=invoice,
            provider=config.provider,
            reference=details.reference or reference,
            account_number=details.account_number,
            bank_name=details.bank_name,
            account_name=details.account_name,
            amount=amount,
            expires_at=timezone.now() + timedelta(minutes=minutes),
            provider_reference=details.provider_reference,
            gateway_response=details.raw,
        )

    # ── Settlement ──────────────────────────────────────────────────────────
    @staticmethod
    def _find_target(organisation, event):
        """Locate the invoice this event pays for.

        Matches on our own reference first, then on the account number — a
        transfer notification may only carry the account it landed in.
        """
        link = PaymentLink.objects.filter(
            organisation=organisation, payment_reference=event.reference,
        ).select_related("invoice").first()
        if link:
            return link, None

        account = VirtualAccount.objects.filter(
            organisation=organisation, reference=event.reference,
        ).select_related("invoice").first()
        if account is None and event.reference:
            account = VirtualAccount.objects.filter(
                organisation=organisation, account_number=event.reference,
                status=VirtualAccount.PENDING,
            ).select_related("invoice").order_by("-created_at").first()
        return None, account

    @staticmethod
    def settle(organisation, provider_slug: str, event) -> str:
        """Act on a payment event exactly once. Returns a short outcome string."""
        # The unique constraint is the real guard — two concurrent deliveries of
        # the same event both reach here, and only one can insert.
        try:
            with transaction.atomic():
                log = PaymentEventLog.objects.create(
                    organisation=organisation,
                    provider=provider_slug,
                    event_id=event.event_id or event.reference,
                    reference=event.reference,
                    status=event.status,
                    amount=event.amount,
                    payload=event.raw,
                )
        except IntegrityError:
            logger.info("Ignoring replayed %s event %s", provider_slug, event.event_id)
            return "duplicate"

        def note(text):
            log.note = text
            log.save(update_fields=["note"])
            return text

        link, account = PaymentService._find_target(organisation, event)

        if not event.succeeded:
            if link:
                link.status = PaymentLink.FAILED
                link.gateway_response = event.raw
                link.save(update_fields=["status", "gateway_response", "updated_at"])
            return note("payment failed")

        target = link or account
        if target is None:
            # Money arrived that we cannot attribute. Never guess — a human
            # reconciles it against the settlement report.
            return note("no matching invoice — needs review")

        if target.status == "paid":
            return note("already settled")

        invoice = target.invoice
        amount = Decimal(str(event.amount or 0))
        if amount <= 0:
            return note("zero amount")

        # Never credit more than is outstanding — a provider can notify twice
        # under different event ids after a genuine retry on their side.
        outstanding = Decimal(str(invoice.amount_due or 0))
        if outstanding <= 0:
            target.status = "paid"
            target.paid_at = timezone.now()
            target.save(update_fields=["status", "paid_at", "updated_at"])
            return note("invoice already fully paid")
        applied = min(amount, outstanding)

        from apps.sales.services import SaleService
        SaleService.record_payment_from_gateway(
            invoice=invoice,
            amount=applied,
            reference=event.reference or event.provider_reference,
            channel=event.channel or "bank_transfer",
            provider=provider_slug,
        )

        target.status = "paid"
        target.paid_at = timezone.now()
        target.gateway_response = event.raw
        target.save(update_fields=["status", "paid_at", "gateway_response", "updated_at"])

        if applied < amount:
            return note(f"overpaid — {amount - applied} not applied")
        return note("settled")

    # ── Merchant's own bank account (no provider) ───────────────────────────
    @staticmethod
    def payment_options(organisation):
        """What a payer can actually choose right now.

        Driven entirely by what the merchant has set up: a provider gives card
        and one-time accounts; a plain bank account gives manual transfer. A
        merchant with neither still sells — they just take cash.
        """
        # `is_active` alone is not enough: a merchant can tick "enable" and save
        # before pasting their keys, and a config with an empty secret_key would
        # otherwise advertise card and one-time-account buttons that throw
        # "Paystack secret key is missing" the moment they are pressed. Treat a
        # keyless config as not set up, so the caller shows the setup prompt.
        config = (
            PaymentGatewayConfig.objects
            .filter(organisation=organisation, is_active=True)
            .exclude(secret_key='').first()
        )
        accounts = list(
            MerchantBankAccount.objects
            .filter(organisation=organisation, is_active=True)
            .order_by('-is_default', 'bank_name')
        )
        from .providers import supports_virtual_accounts
        return {
            'card': bool(config and config.allow_card),
            'virtual_account': bool(
                config and config.allow_transfer and supports_virtual_accounts(config.provider)
            ),
            'bank_transfer': bool(accounts),
            'provider': config.provider if config else '',
            'bank_accounts': accounts,
        }

    @staticmethod
    def claim_bank_transfer(invoice, *, amount=None, payer_name="", narration="",
                            bank_account=None, proof=None) -> BankTransferClaim:
        """Log that a customer says they have paid into the merchant's account."""
        amount = Decimal(str(amount if amount is not None else (invoice.amount_due or 0)))
        if amount <= 0:
            raise PaymentProviderError("This invoice has nothing left to pay.")
        if bank_account is None:
            bank_account = (
                MerchantBankAccount.objects
                .filter(organisation=invoice.organisation, is_active=True)
                .order_by('-is_default').first()
            )
        return BankTransferClaim.objects.create(
            organisation=invoice.organisation,
            invoice=invoice,
            bank_account=bank_account,
            amount=amount,
            payer_name=payer_name or "",
            narration=narration or invoice.invoice_number,
            proof=proof,
        )

    @staticmethod
    @transaction.atomic
    def confirm_bank_transfer(claim: BankTransferClaim, user, note="") -> BankTransferClaim:
        """Staff confirms the money is really in the bank. Only now does it post."""
        claim = BankTransferClaim.objects.select_for_update().get(pk=claim.pk)
        if claim.status == BankTransferClaim.CONFIRMED:
            return claim  # someone already confirmed it — never post twice
        if claim.status == BankTransferClaim.REJECTED:
            raise PaymentProviderError("This transfer was already rejected.")

        outstanding = Decimal(str(claim.invoice.amount_due or 0))
        if outstanding <= 0:
            raise PaymentProviderError("This invoice has already been paid in full.")

        from apps.sales.services import SaleService
        SaleService.record_payment_from_gateway(
            invoice=claim.invoice,
            amount=min(Decimal(str(claim.amount)), outstanding),
            reference=claim.narration or claim.invoice.invoice_number,
            channel="bank_transfer",
            provider="bank transfer",
        )
        claim.status = BankTransferClaim.CONFIRMED
        claim.reviewed_by = user
        claim.reviewed_at = timezone.now()
        claim.review_note = note
        claim.save(update_fields=["status", "reviewed_by", "reviewed_at", "review_note", "updated_at"])
        return claim

    @staticmethod
    def reject_bank_transfer(claim: BankTransferClaim, user, note="") -> BankTransferClaim:
        # Re-read: the caller may hold a stale copy from before a confirmation,
        # and rejecting an already-posted payment would leave the ledger wrong.
        claim = BankTransferClaim.objects.get(pk=claim.pk)
        if claim.status == BankTransferClaim.CONFIRMED:
            raise PaymentProviderError("This transfer was already confirmed and posted.")
        claim.status = BankTransferClaim.REJECTED
        claim.reviewed_by = user
        claim.reviewed_at = timezone.now()
        claim.review_note = note
        claim.save(update_fields=["status", "reviewed_by", "reviewed_at", "review_note", "updated_at"])
        return claim

    # ── Housekeeping ────────────────────────────────────────────────────────
    @staticmethod
    def expire_stale_accounts(organisation=None) -> int:
        """Mark lapsed one-time accounts expired so they stop being offered."""
        qs = VirtualAccount.objects.filter(
            status=VirtualAccount.PENDING, expires_at__lt=timezone.now(),
        )
        if organisation is not None:
            qs = qs.filter(organisation=organisation)
        return qs.update(status=VirtualAccount.EXPIRED)


class PaystackService:
    """Kept so older imports keep working; new code should use PaymentService."""

    @staticmethod
    def create_payment_link(invoice, config):
        return PaymentService.create_payment_link(invoice, config)

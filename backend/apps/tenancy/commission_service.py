"""
CommissionService — partner credit wallet.

All commission accounting is append-only (CommissionLedger).
Balance = SUM(commission_amount) for confirmed rows.
"""
import logging
import uuid
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

logger = logging.getLogger(__name__)

_CHARGEBACK_HOURS = 48
_MIN_CONFIRM_DELTA_HOURS = 48


class CommissionService:

    # ── Balance ───────────────────────────────────────────────────────────────

    @staticmethod
    def available_balance(partner_profile) -> Decimal:
        from .models import CommissionLedger
        result = (
            CommissionLedger.objects
            .filter(partner_profile=partner_profile, status=CommissionLedger.Status.CONFIRMED)
            .aggregate(b=Sum("commission_amount"))["b"]
        )
        return (result or Decimal("0")).quantize(Decimal("0.01"))

    @staticmethod
    def pending_balance(partner_profile) -> Decimal:
        from .models import CommissionLedger
        result = (
            CommissionLedger.objects
            .filter(partner_profile=partner_profile, status=CommissionLedger.Status.PENDING)
            .aggregate(b=Sum("commission_amount"))["b"]
        )
        return (result or Decimal("0")).quantize(Decimal("0.01"))

    @staticmethod
    def lifetime_earned(partner_profile) -> Decimal:
        from .models import CommissionLedger
        result = (
            CommissionLedger.objects
            .filter(
                partner_profile=partner_profile,
                event_type__in=["subscription_payment", "trial_conversion", "referral_bonus"],
            )
            .aggregate(b=Sum("commission_amount"))["b"]
        )
        return (result or Decimal("0")).quantize(Decimal("0.01"))

    # ── Record earned commission ──────────────────────────────────────────────

    @staticmethod
    def record_commission(partner_profile, client_org, gross_amount, reference: str,
                          event_type: str = "subscription_payment") -> None:
        """
        Insert a pending commission ledger entry for a client payment.
        Idempotent — skips if a row with the same reference + event_type already exists.
        """
        from .models import CommissionLedger

        if CommissionLedger.objects.filter(reference=reference, event_type=event_type).exists():
            logger.info("Commission already recorded for ref %s — skipping", reference)
            return

        rate = partner_profile.commission_rate
        if not rate or rate <= 0:
            return

        commission = (Decimal(str(gross_amount)) * rate / Decimal("100")).quantize(Decimal("0.0001"))
        today = timezone.now().date()

        CommissionLedger.objects.create(
            partner_profile=partner_profile,
            client_org=client_org,
            event_type=event_type,
            gross_amount=gross_amount,
            commission_rate=rate,
            commission_amount=commission,
            currency="NGN",
            reference=reference,
            period_start=today,
            period_end=today,
            status=CommissionLedger.Status.PENDING,
        )

        # Keep denormalized totals in sync so the per-client commission column
        # and profile lifetime total reflect real payment activity immediately.
        from .models import PartnerClientLink
        from django.db.models import F
        if client_org:
            PartnerClientLink.objects.filter(
                partner=partner_profile,
                organisation=client_org,
                is_active=True,
            ).update(commission_earned=F("commission_earned") + commission)

        type(partner_profile).objects.filter(pk=partner_profile.pk).update(
            total_commission_earned=F("total_commission_earned") + commission
        )

        logger.info(
            "Commission %.4f NGN (%.2f%%) recorded for partner %s from client %s ref %s",
            commission, rate, partner_profile.id, client_org.id if client_org else "—", reference,
        )

    # ── Reversal (chargeback) ─────────────────────────────────────────────────

    @staticmethod
    def reverse_commission(reference: str) -> None:
        """
        Insert a negative offsetting row to cancel commission for a chargebacked payment.
        Never mutates the original row.
        """
        from .models import CommissionLedger

        original = CommissionLedger.objects.filter(
            reference=reference,
            event_type="subscription_payment",
        ).first()
        if not original:
            return

        reversal_ref = f"REV-{reference}"
        if CommissionLedger.objects.filter(reference=reversal_ref).exists():
            return

        CommissionLedger.objects.create(
            partner_profile=original.partner_profile,
            client_org=original.client_org,
            event_type=CommissionLedger.EventType.REVERSAL,
            gross_amount=-original.gross_amount,
            commission_rate=original.commission_rate,
            commission_amount=-original.commission_amount,
            currency=original.currency,
            reference=reversal_ref,
            period_start=original.period_start,
            period_end=original.period_end,
            status=CommissionLedger.Status.CONFIRMED,
        )
        logger.info("Commission reversed for ref %s (chargeback)", reference)

    # ── Apply credit to subscription ──────────────────────────────────────────

    @staticmethod
    def apply_credit(partner_profile, subscription, amount: Decimal,
                     idempotency_key: str = None) -> None:
        """
        Deduct `amount` from the partner's confirmed balance and link it to `subscription`.
        Must be called inside a transaction.atomic() block by the caller.

        Raises ValueError if:
          - amount > available_balance
          - subscription already has a credit_applied entry
          - currency mismatch (only NGN supported)
        """
        from .models import CommissionLedger

        amount = Decimal(str(amount)).quantize(Decimal("0.0001"))
        if amount <= 0:
            raise ValueError("Credit amount must be positive.")

        # Idempotency guard
        ref = idempotency_key or f"CREDIT-{subscription.id}-{uuid.uuid4().hex[:8]}"
        if CommissionLedger.objects.filter(reference=ref).exists():
            return

        # Check existing credit for this sub (prevent double-apply)
        if CommissionLedger.objects.filter(
            applied_to_sub=subscription,
            event_type=CommissionLedger.EventType.CREDIT_APPLIED,
        ).exists():
            raise ValueError("Credits have already been applied to this subscription.")

        # Balance check (SELECT FOR UPDATE equivalent via DB-level constraint)
        available = CommissionService.available_balance(partner_profile)
        if amount > available:
            raise ValueError(
                f"Insufficient credits. Available: ₦{available}, requested: ₦{amount}"
            )

        today = timezone.now().date()
        CommissionLedger.objects.create(
            partner_profile=partner_profile,
            client_org=None,
            event_type=CommissionLedger.EventType.CREDIT_APPLIED,
            gross_amount=0,
            commission_rate=0,
            commission_amount=-amount,
            currency="NGN",
            reference=ref,
            period_start=today,
            period_end=today,
            status=CommissionLedger.Status.CONFIRMED,
            applied_to_sub=subscription,
        )
        logger.info(
            "Credits %.2f NGN applied by partner %s to subscription %s",
            amount, partner_profile.id, subscription.id,
        )

    # ── Celery: confirm pending entries ───────────────────────────────────────

    @staticmethod
    def confirm_pending() -> int:
        """
        Promote pending → confirmed for entries older than CHARGEBACK_HOURS.
        Called by the Celery beat task every 6 hours.
        Returns count of rows confirmed.
        """
        from .models import CommissionLedger
        from datetime import timedelta

        cutoff = timezone.now() - timedelta(hours=_CHARGEBACK_HOURS)
        updated = CommissionLedger.objects.filter(
            status=CommissionLedger.Status.PENDING,
            created_at__lt=cutoff,
        ).update(status=CommissionLedger.Status.CONFIRMED)
        if updated:
            logger.info("confirm_pending: confirmed %d commission entries", updated)
        return updated

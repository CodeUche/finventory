"""
Subscription service layer.

Provides feature-gate checking and plan lifecycle management.
PaystackSubscriptionService handles platform-level subscription billing
(users paying Audity Technologies for a plan), separate from the per-org
PaymentGatewayConfig used for customer invoices.
"""

import logging
import uuid
from datetime import timedelta
from decimal import Decimal

import requests
from django.conf import settings
from django.utils import timezone

from .models import PaymentHistory, Plan, Subscription

logger = logging.getLogger(__name__)

# Paystack API base
_PAYSTACK_API = "https://api.paystack.co"


def _get_sub(organisation):
    """Safe accessor for org.subscription — returns None if FK points to deleted row."""
    try:
        return organisation.subscription
    except Exception:
        return None


class SubscriptionService:

    @staticmethod
    def create_trial(organisation, plan: Plan) -> Subscription:
        """Start a free trial for a new organisation."""
        trial_end = timezone.now() + timedelta(days=plan.trial_days)
        sub = Subscription.objects.create(
            plan=plan,
            status=Subscription.Status.TRIALING,
            trial_end=trial_end,
            current_period_start=timezone.now(),
            current_period_end=trial_end,
        )
        organisation.subscription = sub
        organisation.save(update_fields=["subscription"])
        logger.info("Trial started for org %s on plan %s", organisation.id, plan.name)
        return sub

    @staticmethod
    def upgrade_plan(organisation, new_plan: Plan) -> Subscription:
        """Upgrade/downgrade to a different plan (mock — no payment)."""
        sub = _get_sub(organisation)
        if not sub:
            return SubscriptionService.create_trial(organisation, new_plan)
        sub.plan = new_plan
        sub.status = Subscription.Status.ACTIVE
        sub.current_period_start = timezone.now()
        sub.current_period_end = timezone.now() + timedelta(days=30)
        sub.save()
        logger.info("Org %s upgraded to plan %s", organisation.id, new_plan.name)
        return sub

    @staticmethod
    def cancel(organisation) -> Subscription:
        """Cancel a subscription at period end."""
        sub = _get_sub(organisation)
        if sub:
            sub.status = Subscription.Status.CANCELED
            sub.canceled_at = timezone.now()
            sub.save()
        return sub

    @staticmethod
    def start_trial_for_plan(organisation, plan: Plan) -> "Subscription":
        """
        Start a free trial on the chosen plan.
        Partner plans get 30 days; all other plans use plan.trial_days (default 14).
        Replaces any existing subscription. Marks onboarding as completed.
        """
        if organisation.trial_used:
            raise ValueError("This organisation has already used its free trial. Please subscribe directly.")

        is_partner = plan.slug.startswith("partner-")
        days = 30 if is_partner else (plan.trial_days or 14)
        trial_end = timezone.now() + timedelta(days=days)
        sub = _get_sub(organisation)
        if sub:
            sub.plan = plan
            sub.status = Subscription.Status.TRIALING
            sub.trial_end = trial_end
            sub.current_period_start = timezone.now()
            sub.current_period_end = trial_end
            sub.save()
        else:
            sub = Subscription.objects.create(
                plan=plan,
                status=Subscription.Status.TRIALING,
                trial_end=trial_end,
                current_period_start=timezone.now(),
                current_period_end=trial_end,
            )
            organisation.subscription = sub
            organisation.save(update_fields=["subscription"])

        org_fields = []
        if not organisation.onboarding_completed:
            organisation.onboarding_completed = True
            org_fields.append("onboarding_completed")
        if not organisation.trial_used:
            organisation.trial_used = True
            org_fields.append("trial_used")
        if org_fields:
            organisation.save(update_fields=org_fields)

        # Sync PartnerProfile tier/limits when starting a partner plan trial
        if is_partner:
            try:
                PaystackSubscriptionService._provision_partner_profile(organisation, plan)
            except Exception:
                logger.warning("Could not provision partner profile for org %s on trial", organisation.id)

        logger.info("Trial started for org %s on plan %s (%d days)", organisation.id, plan.name, days)
        return sub

    @staticmethod
    def activate_free_plan(organisation) -> "Subscription":
        """
        Set the organisation's subscription to the Free plan with ACTIVE status
        and no expiry date. Safe to call multiple times.
        """
        try:
            plan = Plan.objects.get(slug="free", is_active=True)
        except Plan.DoesNotExist:
            raise ValueError("Free plan not found. Run migrations first.")

        sub = _get_sub(organisation)
        if sub:
            sub.plan = plan
            sub.status = Subscription.Status.ACTIVE
            sub.trial_end = None
            sub.current_period_start = timezone.now()
            sub.current_period_end = None  # Free plan never expires
            sub.save(update_fields=[
                "plan", "status", "trial_end",
                "current_period_start", "current_period_end", "updated_at",
            ])
        else:
            sub = Subscription.objects.create(
                plan=plan,
                status=Subscription.Status.ACTIVE,
                current_period_start=timezone.now(),
                current_period_end=None,
            )
            organisation.subscription = sub
            organisation.save(update_fields=["subscription"])

        if not organisation.onboarding_completed:
            organisation.onboarding_completed = True
            organisation.save(update_fields=["onboarding_completed"])

        logger.info("Free plan activated for org %s", organisation.id)
        return sub

    @staticmethod
    def get_write_limit_error(organisation, limit_key: str, current_count: int) -> str | None:
        """
        Returns an upgrade error message if the org has hit a plan write limit.
        Returns None if within limits or the plan has no limit for this key.
        """
        sub = getattr(organisation, "subscription", None)
        if sub is None:
            return None
        limit = sub.plan.features.get(limit_key)
        if limit is None or int(limit) >= 999999:
            return None
        if current_count >= int(limit):
            friendly = limit_key.replace("_per_month", "/month").replace("max_", "").replace("_", " ")
            return (
                f"You've reached your plan limit of {limit} {friendly}. "
                f"Upgrade your plan to add more."
            )
        return None

    @staticmethod
    def check_feature(organisation, feature_key: str, threshold=None) -> bool:
        """
        Returns True if the organisation's active subscription
        permits the given feature.
        """
        sub = getattr(organisation, "subscription", None)
        if sub is None:
            return False
        return sub.can_use_feature(feature_key, threshold=threshold)

    @staticmethod
    def get_plan_limits(organisation) -> dict:
        """Return all feature values for the current plan."""
        sub = getattr(organisation, "subscription", None)
        if sub:
            return sub.plan.features
        return {}

    @staticmethod
    def _charge_provider(subscription: Subscription, amount, currency: str) -> PaymentHistory:
        """
        Mock payment charging. Replace with real provider SDK calls.
        """
        payment = PaymentHistory.objects.create(
            subscription=subscription,
            amount=amount,
            currency=currency,
            status=PaymentHistory.Status.SUCCEEDED,
            description=f"Subscription payment for {subscription.plan.name}",
        )
        return payment


class PaystackSubscriptionService:
    """
    Handles platform-level subscription billing via Paystack.

    Flow:
      1. initiate_payment(org, plan, user_email)
         → calls Paystack initialize transaction
         → returns { authorization_url, reference }
      2. User completes payment in browser
      3. Paystack fires charge.success webhook → activate_from_webhook(data)
         OR user returns and calls verify_payment(org, reference)
    """

    @staticmethod
    def _secret_key() -> str:
        key = getattr(settings, "PAYSTACK_SECRET_KEY", "")
        if not key:
            raise ValueError("PAYSTACK_SECRET_KEY is not configured in settings.")
        return key

    @staticmethod
    def _headers() -> dict:
        return {
            "Authorization": f"Bearer {PaystackSubscriptionService._secret_key()}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def initiate_payment(organisation, plan: Plan, user_email: str) -> dict:
        """
        Initialize a Paystack transaction for a subscription plan.

        Returns:
            { "authorization_url": "...", "reference": "...", "access_code": "..." }

        Raises:
            ValueError on Paystack API error or missing config.
        """
        reference = f"SUB-{uuid.uuid4().hex[:16].upper()}"
        # Paystack amounts are in kobo (1 NGN = 100 kobo)
        amount_kobo = int(plan.price * 100)

        payload = {
            "email": user_email,
            "amount": amount_kobo,
            "reference": reference,
            "currency": "NGN",
            "metadata": {
                "plan_id": str(plan.id),
                "plan_slug": plan.slug,
                "org_id": str(organisation.id),
            },
        }

        try:
            resp = requests.post(
                f"{_PAYSTACK_API}/transaction/initialize",
                json=payload,
                headers=PaystackSubscriptionService._headers(),
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as e:
            logger.error("Paystack initialize transaction failed for org %s: %s", organisation.id, e)
            raise ValueError("Could not connect to Paystack. Please try again.") from e

        if not data.get("status"):
            msg = data.get("message", "Unknown Paystack error")
            logger.error("Paystack initialize failed: %s", msg)
            raise ValueError(f"Paystack error: {msg}")

        # Record a pending payment so we can match the webhook/verify later
        sub = _get_sub(organisation)
        if sub:
            PaymentHistory.objects.create(
                subscription=sub,
                amount=plan.price,
                currency="NGN",
                status=PaymentHistory.Status.FAILED,  # will be updated on success
                provider_payment_id=reference,
                description=f"Pending payment for {plan.name} plan",
            )

        logger.info(
            "Paystack transaction initialized for org %s, plan %s, ref %s",
            organisation.id, plan.slug, reference,
        )
        public_key = getattr(settings, "PAYSTACK_PUBLIC_KEY", "")
        return {
            "authorization_url": data["data"]["authorization_url"],
            "reference": reference,
            "access_code": data["data"].get("access_code", ""),
            "public_key": public_key,
            "amount_kobo": amount_kobo,
            "email": user_email,
        }

    @staticmethod
    def verify_payment(organisation, reference: str) -> Subscription:
        """
        Verify a Paystack transaction by reference and activate the subscription
        if successful.

        Called when the user returns to the app after completing payment.

        Raises:
            ValueError if payment failed or reference not found.
        """
        try:
            resp = requests.get(
                f"{_PAYSTACK_API}/transaction/verify/{reference}",
                headers=PaystackSubscriptionService._headers(),
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as e:
            logger.error("Paystack verify transaction failed for ref %s: %s", reference, e)
            raise ValueError("Could not verify payment with Paystack. Please try again.") from e

        if not data.get("status") or data["data"].get("status") != "success":
            raise ValueError("Payment was not successful. Please try again or contact support.")

        tx = data["data"]
        plan_id = tx.get("metadata", {}).get("plan_id")
        try:
            plan = Plan.objects.get(id=plan_id, is_active=True)
        except Plan.DoesNotExist:
            raise ValueError("Plan not found for this payment reference.")

        return PaystackSubscriptionService._activate_subscription(
            organisation, plan, reference, tx.get("amount", 0)
        )

    @staticmethod
    def activate_from_webhook(event_data: dict) -> None:
        """
        Activate a subscription from a Paystack charge.success webhook event.
        Called by the webhook view — must not raise (errors are logged only).
        """
        try:
            reference = event_data.get("reference", "")
            metadata = event_data.get("metadata", {})
            org_id = metadata.get("org_id")
            plan_id = metadata.get("plan_id")
            amount_kobo = event_data.get("amount", 0)

            if not org_id or not plan_id:
                logger.warning(
                    "charge.success webhook missing org_id or plan_id in metadata: %s",
                    metadata,
                )
                return

            from apps.tenancy.models import Organisation
            try:
                org = Organisation.objects.select_related("subscription").get(id=org_id)
                plan = Plan.objects.get(id=plan_id, is_active=True)
            except (Organisation.DoesNotExist, Plan.DoesNotExist) as e:
                logger.error("Webhook activation: org or plan not found (%s)", e)
                return

            PaystackSubscriptionService._activate_subscription(
                org, plan, reference, amount_kobo
            )
            logger.info(
                "Subscription activated via webhook for org %s, plan %s, ref %s",
                org_id, plan_id, reference,
            )
        except Exception as e:
            logger.error("Unexpected error in activate_from_webhook: %s", e, exc_info=True)

    @staticmethod
    def _activate_subscription(organisation, plan: Plan, reference: str, amount_kobo: int) -> Subscription:
        """
        Set subscription to ACTIVE for the given plan and record payment.
        Idempotent — safe to call multiple times for the same reference.
        """
        try:
            sub = organisation.subscription
        except Exception:
            sub = None
        if not sub:
            sub = Subscription.objects.create(
                plan=plan,
                status=Subscription.Status.ACTIVE,
                provider="paystack",
                current_period_start=timezone.now(),
                current_period_end=timezone.now() + timedelta(days=30),
            )
            organisation.subscription = sub
            organisation.save(update_fields=["subscription"])
        else:
            sub.plan = plan
            sub.status = Subscription.Status.ACTIVE
            sub.provider = "paystack"
            sub.current_period_start = timezone.now()
            sub.current_period_end = timezone.now() + timedelta(days=30)
            sub.save(update_fields=[
                "plan", "status", "provider",
                "current_period_start", "current_period_end", "updated_at",
            ])

        # Update the pending PaymentHistory to succeeded, or create a new record
        amount_ngn = amount_kobo / 100 if amount_kobo else plan.price
        ph, created = PaymentHistory.objects.get_or_create(
            subscription=sub,
            provider_payment_id=reference,
            defaults={
                "amount": amount_ngn,
                "currency": "NGN",
                "status": PaymentHistory.Status.SUCCEEDED,
                "description": f"Payment for {plan.name} plan",
            },
        )
        if not created and ph.status != PaymentHistory.Status.SUCCEEDED:
            ph.status = PaymentHistory.Status.SUCCEEDED
            ph.amount = amount_ngn
            ph.description = f"Payment for {plan.name} plan"
            ph.save(update_fields=["status", "amount", "description"])

        # Mark onboarding as completed once a paid plan is activated
        if not organisation.onboarding_completed:
            organisation.onboarding_completed = True
            organisation.save(update_fields=["onboarding_completed"])

        # Provision / sync PartnerProfile when a partner plan is activated
        if plan.slug.startswith("partner-"):
            SubscriptionService._provision_partner_profile(organisation, plan)

        # Credit commission to any referring partner (only on real payments)
        if amount_ngn > 0:
            PaystackSubscriptionService._record_partner_commission(organisation, amount_ngn, reference)

        logger.info(
            "Subscription activated: org=%s plan=%s ref=%s",
            organisation.id, plan.slug, reference,
        )
        return sub

    @staticmethod
    def _record_partner_commission(organisation, amount_ngn, reference: str) -> None:
        """
        Credit commission to the referring partner when a client pays.
        Delegates to CommissionService.record_commission (append-only ledger).
        Also keeps the legacy denormalized totals on PartnerClientLink / PartnerProfile
        in sync so existing dashboard queries continue to work during migration.
        """
        try:
            from apps.tenancy.models import PartnerClientLink
            from apps.tenancy.commission_service import CommissionService

            link = PartnerClientLink.objects.select_related("partner").filter(
                organisation=organisation,
                is_active=True,
                is_referred=True,
            ).first()
            if not link:
                return

            partner = link.partner
            rate = partner.commission_rate
            if not rate or rate <= 0:
                return

            # Append-only ledger entry (idempotent)
            CommissionService.record_commission(
                partner_profile=partner,
                client_org=organisation,
                gross_amount=amount_ngn,
                reference=reference,
            )

            # Keep legacy denormalized totals in sync
            commission = (Decimal(str(amount_ngn)) * rate / Decimal("100")).quantize(Decimal("0.0001"))
            from django.db import transaction as _tx
            from django.db.models import F
            from apps.tenancy.models import PartnerProfile
            with _tx.atomic():
                PartnerClientLink.objects.filter(pk=link.pk).update(
                    commission_earned=link.commission_earned + commission
                )
                PartnerProfile.objects.filter(pk=partner.pk).update(
                    total_commission_earned=F("total_commission_earned") + commission
                )
        except Exception as e:
            logger.error("Failed to record partner commission for org %s ref %s: %s", organisation.id, reference, e)

    @staticmethod
    def _provision_partner_profile(organisation, plan):
        """
        Create or update the PartnerProfile for the organisation owner
        when they subscribe to a partner-tier plan.

        Commission rates by tier:
          partner-starter  → 5 %
          partner-pro      → 7.5 %
          partner-agency   → 10 %
        """
        from apps.tenancy.models import PartnerProfile

        TIER_MAP = {
            "partner-starter": ("starter",  10,     Decimal("5.00")),
            "partner-pro":     ("pro",       30,     Decimal("7.50")),
            "partner-agency":  ("agency",    999999, Decimal("10.00")),
        }
        tier, max_clients, commission_rate = TIER_MAP.get(
            plan.slug, ("starter", 10, Decimal("5.00"))
        )
        features = plan.features or {}

        owner = organisation.owner
        if not owner:
            return

        profile, _ = PartnerProfile.objects.get_or_create(
            user=owner,
            defaults={
                "tier": tier,
                "max_clients": max_clients,
                "commission_rate": commission_rate,
            },
        )
        # Always sync tier/limits/rate/features from the plan
        profile.tier = tier
        profile.max_clients = max_clients
        profile.commission_rate = commission_rate
        profile.white_label_reports = features.get("white_label_reports", False)
        profile.consolidated_reporting = features.get("consolidated_reporting", False)
        profile.is_active = True
        profile.save(update_fields=[
            "tier", "max_clients", "commission_rate",
            "white_label_reports", "consolidated_reporting", "is_active", "updated_at",
        ])

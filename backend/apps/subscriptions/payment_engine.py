"""
PaymentEngine — single money-movement code path for everything Audity itself
charges through its own (platform-level) Paystack account.

Why one engine instead of two parallel services (subscription billing +
integration marketplace billing): a payment pipeline is security-sensitive
surface (amount verification, org-ownership verification, idempotent
webhook handling, refund handling). Two independently-maintained copies of
that logic drift — a fix applied to one silently doesn't reach the other.
Here there is exactly one `initiate` / `activate` / `handle_refund_webhook`
code path; what differs per payment "kind" (subscription vs. integration
purchase) is only what a *successful* or *refunded* payment grants, which is
isolated into small `PaymentKindHandler` strategies.

Row-locking (`select_for_update`) on the `PaymentHistory` row in `activate`
is the primary defense against the webhook delivery and the browser-return
`verify-payment` poll racing each other for the same reference — whichever
gets the lock first does the real Paystack verification + grant; the other
sees `status == SUCCEEDED` and returns immediately as a no-op.
"""

import logging
import uuid
from decimal import Decimal
from datetime import timedelta

import requests
from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import (
    IntegrationProduct,
    OrganisationIntegrationEntitlement,
    PaymentHistory,
    Plan,
    Subscription,
)

logger = logging.getLogger(__name__)

_PAYSTACK_API = "https://api.paystack.co"


def _get_sub(organisation):
    """Safe accessor for org.subscription — returns None if FK points to deleted row."""
    try:
        return organisation.subscription
    except Exception:
        return None


def _secret_key() -> str:
    key = getattr(settings, "PAYSTACK_SECRET_KEY", "")
    if not key:
        raise ValueError("PAYSTACK_SECRET_KEY is not configured in settings.")
    return key


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {_secret_key()}",
        "Content-Type": "application/json",
    }


# ── Per-kind strategies: what a success/refund grants ───────────────────────

class PaymentKindHandler:
    def apply_success(self, payment: PaymentHistory) -> None:
        raise NotImplementedError

    def apply_refund(self, payment: PaymentHistory, full: bool) -> None:
        raise NotImplementedError


class SubscriptionHandler(PaymentKindHandler):
    """
    Wraps the existing subscription-activation logic (status -> ACTIVE,
    period dates, onboarding flag, partner-profile provisioning, commission
    crediting). This is a straight port of
    PaystackSubscriptionService._activate_subscription, minus the
    plan-resolution step (the caller has already resolved/attached the plan
    onto payment.subscription or via payment metadata — see PaymentEngine.activate).
    """

    def apply_success(self, payment: PaymentHistory) -> None:
        from .services import PaystackSubscriptionService  # local import avoids a cycle

        organisation = payment.organisation
        plan = payment._resolved_plan  # set by PaymentEngine.activate before calling us
        reference = payment.provider_payment_id
        amount_kobo = int(payment.amount * 100)

        sub = PaystackSubscriptionService._activate_subscription(
            organisation, plan, reference, amount_kobo,
        )
        # Point this PaymentHistory row at the real Subscription row now that
        # it exists (it may have been created inside _activate_subscription).
        if payment.subscription_id != sub.id:
            payment.subscription = sub
            payment.save(update_fields=["subscription"])

    def apply_refund(self, payment: PaymentHistory, full: bool) -> None:
        # Subscription refunds don't currently reverse plan activation —
        # access is governed by Subscription.status/period dates set via the
        # normal cancel flow, not by PaymentHistory.status. Log for visibility;
        # a human/ops decision is required to also cancel the subscription.
        logger.warning(
            "Refund recorded for subscription payment ref=%s full=%s — subscription "
            "status is NOT automatically changed; cancel manually if required.",
            payment.provider_payment_id, full,
        )


class IntegrationHandler(PaymentKindHandler):
    def apply_success(self, payment: PaymentHistory) -> None:
        entitlement = payment.integration_entitlement
        entitlement.status = OrganisationIntegrationEntitlement.Status.ACTIVE
        entitlement.purchased_at = timezone.now()
        entitlement.save(update_fields=["status", "purchased_at", "updated_at"])

    def apply_refund(self, payment: PaymentHistory, full: bool) -> None:
        entitlement = payment.integration_entitlement
        if full:
            entitlement.status = OrganisationIntegrationEntitlement.Status.REVOKED
            entitlement.revoked_at = timezone.now()
            entitlement.revoked_reason = "refunded"
            entitlement.save(update_fields=["status", "revoked_at", "revoked_reason", "updated_at"])
        else:
            # A partial refund must never auto-revoke a boolean entitlement —
            # the org still paid for (and should still have) the integration.
            logger.warning(
                "Partial refund on integration payment ref=%s (entitlement=%s) — "
                "entitlement left ACTIVE; no automatic action taken.",
                payment.provider_payment_id, entitlement.id,
            )


HANDLERS = {
    PaymentHistory.Kind.SUBSCRIPTION: SubscriptionHandler(),
    PaymentHistory.Kind.INTEGRATION: IntegrationHandler(),
}


def org_can_receive_integration_delivery(organisation) -> bool:
    """
    An OrganisationIntegrationEntitlement SURVIVES a lapsed/canceled
    Subscription by design — the org paid for it separately and does not
    lose it or need to re-purchase it merely because their plan lapsed.

    This function is what a *future* webhook-delivery Celery task calls to
    decide whether to actually SEND a webhook right now — it mirrors the
    exact reads-still-work/writes-blocked split that the `SubscriptionActive`
    permission already enforces everywhere else in the app (subscription
    lapsed => outbound/paid actions pause, but nothing already owned is
    deleted or lost), rather than inventing a new bespoke policy here.
    """
    try:
        sub = organisation.subscription
    except Exception:
        sub = None
    if sub is None:
        return False
    return sub.is_active


class PaymentEngine:

    @staticmethod
    def initiate(organisation, kind: str, target, user_email: str) -> dict:
        """
        target = Plan instance when kind == PaymentHistory.Kind.SUBSCRIPTION,
                 IntegrationProduct instance when kind == PaymentHistory.Kind.INTEGRATION.
        """
        if kind == PaymentHistory.Kind.INTEGRATION:
            return PaymentEngine._initiate_integration(organisation, target, user_email)
        if kind == PaymentHistory.Kind.SUBSCRIPTION:
            return PaymentEngine._initiate_subscription(organisation, target, user_email)
        raise ValueError(f"Unknown payment kind: {kind}")

    @staticmethod
    def _initiate_subscription(organisation, plan: Plan, user_email: str) -> dict:
        reference = f"SUB-{uuid.uuid4().hex[:16].upper()}"
        amount_kobo = int(plan.price * 100)

        # Resolve (but do not activate) the org's Subscription row up front,
        # same eager-target pattern as integration_entitlement below. This is
        # required by the DB CHECK constraint
        # `payment_history_exactly_one_target_when_settled`, which demands a
        # non-null `subscription` FK the moment a kind=subscription row is
        # anything other than PENDING (e.g. FAILED on a Paystack API error) —
        # a PaymentHistory row can go PENDING -> FAILED without ever reaching
        # apply_success, so `subscription` cannot be left null until then.
        # SubscriptionHandler.apply_success still does the real activation
        # (status -> ACTIVE, period dates); this only guarantees a row exists
        # to point at.
        sub = _get_sub(organisation)
        if sub is None:
            sub = Subscription.objects.create(plan=plan, status=Subscription.Status.INCOMPLETE)
            organisation.subscription = sub
            organisation.save(update_fields=["subscription"])

        payment = PaymentHistory.objects.create(
            kind=PaymentHistory.Kind.SUBSCRIPTION,
            organisation=organisation,
            subscription=sub,
            expected_amount=plan.price,
            amount=plan.price,
            status=PaymentHistory.Status.PENDING,
            provider_payment_id=reference,
            description=f"Pending payment for {plan.name} plan",
        )

        payload = {
            "email": user_email,
            "amount": amount_kobo,
            "reference": reference,
            "currency": "NGN",
            "metadata": {
                "payment_kind": "subscription",
                "plan_id": str(plan.id),
                "plan_slug": plan.slug,
                "org_id": str(organisation.id),
            },
        }
        return PaymentEngine._call_initialize(payment, payload, user_email, amount_kobo)

    @staticmethod
    def _initiate_integration(organisation, product: IntegrationProduct, user_email: str) -> dict:
        # The entitlement lookup and the subsequent ACTIVE-status check must
        # happen as one atomic check-then-act under a row lock — get_or_create's
        # own atomicity only covers the create, not the .status branch that
        # follows it. Without the lock, two near-simultaneous purchase
        # requests (double-click, two tabs) can both read "not yet ACTIVE"
        # before either commits, minting two separate Paystack references
        # for one entitlement and risking a real double-charge if both
        # checkouts are completed. select_for_update() on the existing row
        # makes the second concurrent caller block until the first commits
        # (and then correctly see ACTIVE/PENDING-with-a-live-payment and be
        # rejected) or rolls back.
        amount_kobo = int(product.price * 100)
        reference = f"INT-{uuid.uuid4().hex[:16].upper()}"

        # The entitlement lookup, the ACTIVE-status check, the in-flight-payment
        # check, and the new PENDING PaymentHistory row must all happen inside
        # ONE locked transaction — get_or_create's own atomicity only covers the
        # create, not the .status branch (or the pending-payment existence
        # check) that follows it. If the lock were released before the PENDING
        # row is inserted, a second concurrent caller's "is there already a
        # pending payment" check could still run in the gap and see nothing,
        # reopening the exact race this fix closes. select_for_update() on the
        # entitlement row makes a second near-simultaneous purchase request
        # (double-click, two tabs) block until the first commits its PENDING
        # row (and the second then correctly sees it and is rejected) or rolls
        # back — preventing two Paystack references, and two real charges, for
        # one entitlement.
        with transaction.atomic():
            entitlement, created = OrganisationIntegrationEntitlement.objects.get_or_create(
                organisation=organisation,
                product=product,
                defaults={"status": OrganisationIntegrationEntitlement.Status.PENDING},
            )
            if not created:
                entitlement = OrganisationIntegrationEntitlement.objects.select_for_update().get(
                    pk=entitlement.pk,
                )
                if entitlement.status == OrganisationIntegrationEntitlement.Status.ACTIVE:
                    raise ValueError("This organisation already owns this integration.")

            # Reject a second concurrent purchase attempt while a prior
            # PENDING payment for this same entitlement is still in flight
            # (not yet succeeded or failed) — the ACTIVE guard above only
            # catches an already-owned integration; two simultaneous
            # first-time purchases both see PENDING/created=True and would
            # otherwise both proceed to mint a reference.
            has_pending_payment = PaymentHistory.objects.filter(
                integration_entitlement=entitlement,
                status=PaymentHistory.Status.PENDING,
            ).exists()
            if has_pending_payment:
                raise ValueError(
                    "A payment for this integration is already in progress. "
                    "Please complete or wait for it to finish before trying again."
                )

            payment = PaymentHistory.objects.create(
                kind=PaymentHistory.Kind.INTEGRATION,
                organisation=organisation,
                integration_entitlement=entitlement,
                expected_amount=product.price,
                amount=product.price,
                status=PaymentHistory.Status.PENDING,
                provider_payment_id=reference,
                description=f"Pending payment for {product.name} integration",
            )

        payload = {
            "email": user_email,
            "amount": amount_kobo,
            "reference": reference,
            "currency": "NGN",
            "metadata": {
                "payment_kind": "integration",
                "product_key": product.key,
                "org_id": str(organisation.id),
            },
        }
        return PaymentEngine._call_initialize(payment, payload, user_email, amount_kobo)

    @staticmethod
    def _call_initialize(payment: PaymentHistory, payload: dict, user_email: str, amount_kobo: int) -> dict:
        try:
            resp = requests.post(
                f"{_PAYSTACK_API}/transaction/initialize",
                json=payload,
                headers=_headers(),
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as e:
            payment.status = PaymentHistory.Status.FAILED
            payment.save(update_fields=["status"])
            logger.error("Paystack initialize transaction failed for ref %s: %s", payment.provider_payment_id, e)
            raise ValueError("Could not connect to Paystack. Please try again.") from e

        if not data.get("status"):
            payment.status = PaymentHistory.Status.FAILED
            payment.save(update_fields=["status"])
            msg = data.get("message", "Unknown Paystack error")
            logger.error("Paystack initialize failed: %s", msg)
            raise ValueError(f"Paystack error: {msg}")

        public_key = getattr(settings, "PAYSTACK_PUBLIC_KEY", "")
        return {
            "authorization_url": data["data"]["authorization_url"],
            "reference": payment.provider_payment_id,
            "access_code": data["data"].get("access_code", ""),
            "public_key": public_key,
            "amount_kobo": amount_kobo,
            "email": user_email,
        }

    @staticmethod
    def _mark_failed(payment: PaymentHistory) -> None:
        """
        Persist a FAILED status in its OWN committed transaction, independent
        of the caller's atomic block. `activate` raises ValueError right after
        calling this on every rejection path — if the FAILED write lived
        inside the same atomic block as the raise, Django would roll the
        whole transaction back (including the FAILED write itself), silently
        leaving the row stuck on PENDING forever with no record of the
        rejection reason ever having been persisted.
        """
        with transaction.atomic():
            payment.status = PaymentHistory.Status.FAILED
            payment.save(update_fields=["status"])

    @staticmethod
    def activate(reference: str) -> PaymentHistory:
        """
        Idempotent, race-safe settlement of a payment reference. Callable from
        the webhook route, the browser-return verify-payment poll, and the
        check-payment silent poll — always the same code path.
        """
        with transaction.atomic():
            try:
                payment = PaymentHistory.objects.select_for_update().get(provider_payment_id=reference)
            except PaymentHistory.DoesNotExist:
                raise ValueError("Payment reference not found.")

            if payment.status == PaymentHistory.Status.SUCCEEDED:
                return payment  # idempotent no-op — duplicate webhook/poll delivery

        # Paystack HTTP call deliberately made OUTSIDE the row lock / atomic
        # block above — an external network call must never hold a DB
        # transaction (and therefore the row lock) open for its duration.
        try:
            resp = requests.get(
                f"{_PAYSTACK_API}/transaction/verify/{reference}",
                headers=_headers(),
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as e:
            logger.error("Paystack verify transaction failed for ref %s: %s", reference, e)
            raise ValueError("Could not verify payment with Paystack. Please try again.") from e

        ps_status = data.get("data", {}).get("status") if data.get("status") else None
        if ps_status != "success":
            # Only a genuinely TERMINAL Paystack status may poison this row.
            # This function is now polled repeatedly (background poll right
            # after checkout opens, a silent check on every page load, plus
            # the manual "Restore access" button) — the very first tick
            # typically fires while the customer hasn't finished paying yet,
            # long before a real "success". Marking FAILED on that first
            # transient "abandoned"/"pending"/"processing" read permanently
            # bricks a payment that goes on to genuinely succeed minutes
            # later, since every subsequent check then finds no PENDING row
            # left to re-verify. A confirmed production incident: a real
            # ₦15k bank-transfer payment succeeded 6 minutes after checkout
            # opened, well past the first poll tick, and was wrongly marked
            # FAILED by this exact line before this fix.
            if ps_status in ("failed", "reversed"):
                PaymentEngine._mark_failed(payment)
            raise ValueError("Payment was not successful. Please try again or contact support.")

        tx = data["data"]

        expected_kobo = int((payment.expected_amount or payment.amount) * 100)
        actual_kobo = int(tx.get("amount") or 0)
        # >= not != : Paystack can add its own convenience fee on top of the
        # amount we initialized with (seen on the bank_transfer channel) and
        # passes that fee's cost to the customer, so a genuine successful
        # payment can legitimately come back slightly ABOVE what we expected.
        # Only genuine underpayment is a real mismatch worth rejecting.
        if actual_kobo < expected_kobo:
            PaymentEngine._mark_failed(payment)
            raise ValueError(
                f"Amount mismatch for payment {reference}: expected at least {expected_kobo} kobo, "
                f"got {actual_kobo} kobo."
            )

        metadata = tx.get("metadata") or {}
        tx_org_id = metadata.get("org_id")
        if tx_org_id != str(payment.organisation_id):
            PaymentEngine._mark_failed(payment)
            raise ValueError(
                f"Organisation mismatch for payment {reference}: payment belongs to "
                f"org {payment.organisation_id}, transaction metadata claims org {tx_org_id}."
            )

        if payment.kind == PaymentHistory.Kind.SUBSCRIPTION:
            plan_id = metadata.get("plan_id")
            try:
                plan = Plan.objects.get(id=plan_id, is_active=True)
            except Plan.DoesNotExist:
                PaymentEngine._mark_failed(payment)
                raise ValueError("Plan not found for this payment reference.")
            payment._resolved_plan = plan  # stashed for SubscriptionHandler.apply_success

        with transaction.atomic():
            # Re-lock: another activate() call could have raced us between the
            # first lock release (above) and here. Re-check SUCCEEDED under
            # lock before committing the grant, so two concurrent callers who
            # both passed verification can't both apply_success.
            payment = PaymentHistory.objects.select_for_update().get(pk=payment.pk)
            if payment.status == PaymentHistory.Status.SUCCEEDED:
                return payment
            if payment.kind == PaymentHistory.Kind.SUBSCRIPTION:
                payment._resolved_plan = plan

            payment.amount = Decimal(actual_kobo) / Decimal("100")
            payment.status = PaymentHistory.Status.SUCCEEDED
            payment.save(update_fields=["amount", "status"])

            HANDLERS[payment.kind].apply_success(payment)
        return payment

    @staticmethod
    @transaction.atomic
    def handle_refund_webhook(refund_data: dict) -> None:
        """
        refund_data is the Paystack refund event's `data` object
        (refund.processed / refund.failed / refund.pending).

        Shape assumption (see module report for the WebFetch/WebSearch
        verification attempt and outcome — Paystack's own docs returned 403
        to automated fetches; no source produced a fully authoritative literal
        JSON example): the primary path is a nested transaction object,
        refund_data['transaction']['reference'], matching Paystack's
        documented Refund object which embeds the full Transaction object
        under the `transaction` key. A flat `transaction_reference` field was
        also referenced by a third-party integration guide as an alternative
        shape actually seen in production payloads, so it's tried as a
        fallback. The refunded amount is refund_data['amount'] in kobo either
        way. If neither shape matches, we log and return without raising —
        never crash the webhook endpoint or cause Paystack to retry-storm on
        a payload shape we didn't anticipate; this must be confirmed against
        a real Paystack refund webhook delivery before this path is trusted
        in production, e.g. via the dashboard's webhook log/replay tool.
        """
        transaction_obj = refund_data.get("transaction") or {}
        reference = transaction_obj.get("reference") or refund_data.get("transaction_reference")
        if not reference:
            logger.error("Refund webhook missing transaction reference: %s", refund_data)
            return

        try:
            payment = PaymentHistory.objects.select_for_update().get(provider_payment_id=reference)
        except PaymentHistory.DoesNotExist:
            logger.error("Refund webhook: no PaymentHistory found for ref %s", reference)
            return

        try:
            refunded_amount = Decimal(str(refund_data.get("amount", 0))) / Decimal("100")
        except Exception:
            logger.error("Refund webhook: could not parse amount for ref %s: %s", reference, refund_data)
            return

        full = refunded_amount >= payment.amount
        payment.status = (
            PaymentHistory.Status.REFUNDED if full else PaymentHistory.Status.PARTIALLY_REFUNDED
        )
        payment.save(update_fields=["status"])

        HANDLERS[payment.kind].apply_refund(payment, full=full)
        logger.info(
            "Refund processed for ref=%s kind=%s full=%s amount=%s",
            reference, payment.kind, full, refunded_amount,
        )

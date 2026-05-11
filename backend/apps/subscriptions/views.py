"""Subscription views."""

import json
import logging

import requests as http_requests
from django.conf import settings
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from apps.core.permissions import IsOwnerOrAdmin

from .models import PaymentHistory, Plan, Subscription
from .serializers import PaymentHistorySerializer, PlanSerializer, SubscriptionSerializer
from .services import PaystackSubscriptionService, SubscriptionService

logger = logging.getLogger(__name__)

_SENTINEL = "00000000-0000-0000-0000-000000000000"


def _resolve_org_for_user_raw(user, org_id_hint=None):
    """Resolve an Organisation for a user, bypassing RLS via raw SQL with both GUCs."""
    from django.db import connection as _conn, transaction as _tx
    from apps.tenancy.models import Organisation

    try:
        with _tx.atomic():
            with _conn.cursor() as cur:
                cur.execute("SELECT set_config('app.current_org_id', %s, TRUE)", [_SENTINEL])
                cur.execute("SELECT set_config('app.current_user_id', %s, TRUE)", [str(user.pk)])

                if org_id_hint:
                    cur.execute(
                        "SELECT organisation_id FROM tenancy_membership"
                        " WHERE user_id = %s AND organisation_id = %s AND is_active = TRUE",
                        [str(user.pk), str(org_id_hint)],
                    )
                else:
                    cur.execute(
                        "SELECT organisation_id FROM tenancy_membership"
                        " WHERE user_id = %s AND is_active = TRUE LIMIT 1",
                        [str(user.pk)],
                    )
                row = cur.fetchone()
                if not row:
                    logger.warning(
                        "_resolve_org_for_user_raw: no active membership for user=%s hint=%s",
                        user.pk, org_id_hint,
                    )
                    return None
                org_id = str(row[0])

            # Set org GUC to the resolved org so the ORM query passes RLS
            with _conn.cursor() as cur:
                cur.execute("SELECT set_config('app.current_org_id', %s, TRUE)", [org_id])

            return Organisation.objects.get(id=org_id)
    except Exception as exc:
        logger.warning("_resolve_org_for_user_raw: failed for user=%s: %s", user.pk, exc)
        return None


_GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
_GROQ_MODEL = "llama-3.1-8b-instant"


def _ai_recommend(answers: dict, plan_context: list, api_key: str) -> dict:
    """Call Groq AI for a structured plan recommendation."""
    prompt = f"""You are a business software consultant recommending the best Audity subscription plan.

User's business profile:
- Business type: {answers.get('business_type', 'not specified')}
- Monthly transactions: {answers.get('monthly_transactions', 'not specified')}
- Team size (staff using the system): {answers.get('team_size', 'not specified')}
- Manages physical inventory: {answers.get('has_inventory', 'not specified')}
- Number of locations/warehouses: {answers.get('locations', 'not specified')}
- Most important feature: {answers.get('priority_feature', 'not specified')}
- Business stage: {answers.get('business_stage', 'not specified')}

Available plans (ordered by price):
{json.dumps(plan_context, indent=2)}

Recommend the single most suitable plan. Consider max_users vs team size, multi_warehouse vs locations, advanced_reports for established businesses, and value for money.

Respond ONLY with valid JSON (no markdown, no explanation outside JSON):
{{
  "recommended_plan_slug": "<slug>",
  "confidence": "high",
  "reasons": ["reason 1 tailored to their answers", "reason 2", "reason 3"],
  "alternative_plan_slug": "<slug of second-best>",
  "alternative_reasons": ["one reason why this is also a good fit"]
}}"""

    resp = http_requests.post(
        _GROQ_API_URL,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": _GROQ_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,
            "max_tokens": 600,
        },
        timeout=20,
    )
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"].strip()

    # Strip markdown code fences if present
    if "```" in content:
        parts = content.split("```")
        content = parts[1] if len(parts) > 1 else parts[0]
        if content.startswith("json"):
            content = content[4:].strip()

    return json.loads(content)


def _rule_recommend(answers: dict, plans: list) -> dict:
    """Rule-based fallback recommendation when AI is unavailable."""
    team_str = str(answers.get("team_size", "just me")).lower()
    locations_str = str(answers.get("locations", "one")).lower()
    transactions_str = str(answers.get("monthly_transactions", "less than 50")).lower()
    stage = str(answers.get("business_stage", "starting")).lower()

    # Infer team count
    if "just me" in team_str or "1" == team_str.strip():
        team_count = 1
    elif "2" in team_str or "3" in team_str or "4" in team_str or "5" in team_str:
        team_count = 5
    elif "6" in team_str:
        team_count = 6
    else:
        team_count = 15

    needs_multi = any(w in locations_str for w in ["2", "3", "multiple", "more", "branch"])
    high_volume = any(w in transactions_str for w in ["1,000", "1000", "200-1,000", "200–1,000"])
    is_established = any(w in stage for w in ["established", "3+", "years"])

    plan_slugs = [p.slug for p in plans]

    if team_count > 10 or (needs_multi and is_established) or high_volume:
        rec, alt = "business", "professional"
        reasons = [
            f"Your team of {answers.get('team_size', '')} requires the expanded user seats on the Business plan.",
            "High transaction volume and multi-location needs are best handled with unlimited capacity.",
            "The Business plan's advanced reports and API access will support your established operations.",
        ]
    elif team_count > 3 or needs_multi or is_established:
        rec, alt = "professional", "business"
        reasons = [
            f"Your team size of {answers.get('team_size', '')} fits perfectly within the Professional plan's 5-user limit.",
            "Multi-warehouse support is included, matching your location requirements.",
            "Advanced reports and the full tax engine are available for your growing business needs.",
        ]
    else:
        rec, alt = "starter", "professional"
        reasons = [
            "The Starter plan is ideal for getting started with up to 100 products and 3 users.",
            "Core invoicing, inventory, and supplier management cover your stated priorities.",
            "At ₦5,000/month, it offers excellent value for your current stage.",
        ]

    # Ensure slugs exist
    if rec not in plan_slugs and plan_slugs:
        rec = plan_slugs[0]
    if alt not in plan_slugs and plan_slugs:
        alt = plan_slugs[-1]

    return {
        "recommended_plan_slug": rec,
        "confidence": "medium",
        "reasons": reasons,
        "alternative_plan_slug": alt,
        "alternative_reasons": [
            "Consider this if you expect significant growth in the next 6 months."
        ],
    }


class PlanViewSet(viewsets.ReadOnlyModelViewSet):
    """GET /api/v1/subscriptions/plans/ — Public plan listing."""

    queryset = Plan.objects.filter(is_active=True, is_public=True)
    serializer_class = PlanSerializer
    permission_classes = [AllowAny]


class SubscriptionViewSet(viewsets.GenericViewSet):
    """Manage the current organisation's subscription."""

    serializer_class = SubscriptionSerializer
    permission_classes = [IsAuthenticated, IsOwnerOrAdmin]

    def get_object(self):
        org = self.request.organisation
        if org is None:
            return None
        try:
            return org.subscription
        except Exception:
            # subscription_id FK points to a deleted row — treat as no subscription
            return None

    @action(detail=False, methods=["get"])
    def current(self, request):
        """GET /api/v1/subscriptions/current/ — Current subscription status."""
        sub = self.get_object()
        if not sub:
            return Response({"detail": "No active subscription."}, status=404)
        return Response(SubscriptionSerializer(sub).data)

    @action(detail=False, methods=["post"])
    def upgrade(self, request):
        """POST /api/v1/subscriptions/upgrade/ — Upgrade/downgrade plan."""
        plan_id = request.data.get("plan_id")
        try:
            plan = Plan.objects.get(id=plan_id, is_active=True)
        except Plan.DoesNotExist:
            return Response({"error": "Plan not found."}, status=400)

        sub = SubscriptionService.upgrade_plan(request.organisation, plan)
        return Response(SubscriptionSerializer(sub).data)

    @action(detail=False, methods=["post"])
    def cancel(self, request):
        """POST /api/v1/subscriptions/cancel/ — Cancel subscription."""
        sub = SubscriptionService.cancel(request.organisation)
        return Response(SubscriptionSerializer(sub).data)

    @action(detail=False, methods=["get"])
    def payments(self, request):
        """GET /api/v1/subscriptions/payments/ — Payment history."""
        sub = self.get_object()
        if not sub:
            return Response([])
        payments = sub.payments.order_by("-created_at")
        return Response(PaymentHistorySerializer(payments, many=True).data)

    @action(detail=False, methods=["post"], url_path="initiate-payment")
    def initiate_payment(self, request):
        """
        POST /api/v1/subscriptions/initiate-payment/
        Body: { "plan_id": "<uuid>" }

        Initialises a Paystack transaction. Returns { authorization_url, reference }.
        """
        plan_id = request.data.get("plan_id")
        if not plan_id:
            return Response({"error": "plan_id is required."}, status=400)

        try:
            plan = Plan.objects.get(id=plan_id, is_active=True)
        except Plan.DoesNotExist:
            return Response({"error": "Plan not found."}, status=400)

        if plan.price == 0:
            return Response({"error": "Cannot process payment for a free plan."}, status=400)

        user_email = request.user.email
        try:
            result = PaystackSubscriptionService.initiate_payment(
                request.organisation, plan, user_email
            )
        except ValueError as e:
            return Response({"error": str(e)}, status=400)
        except Exception:
            logger.exception(
                "Unexpected error in initiate_payment for org %s, plan %s",
                request.organisation.id, plan.slug,
            )
            return Response(
                {"error": "Payment initialization failed. Please try again."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response(result, status=status.HTTP_200_OK)

    @action(detail=False, methods=["post"], url_path="verify-payment")
    def verify_payment(self, request):
        """
        POST /api/v1/subscriptions/verify-payment/
        Body: { "reference": "SUB-XXXXXXXX" }
        """
        reference = request.data.get("reference", "").strip()
        if not reference:
            return Response({"error": "reference is required."}, status=400)

        try:
            sub = PaystackSubscriptionService.verify_payment(request.organisation, reference)
        except ValueError as e:
            return Response({"error": str(e)}, status=400)

        return Response(SubscriptionSerializer(sub).data)

    @action(detail=False, methods=["get"], url_path="check-payment")
    def check_payment(self, request):
        """
        GET /api/v1/subscriptions/check-payment/?reference=SUB-XXXX

        Poll-safe status check. Returns:
          { "status": "success", "subscription": {...} }  — paid & activated
          { "status": "pending" }                         — not yet paid
        Used by onboarding to auto-detect payment completion without user action.
        """
        reference = request.query_params.get("reference", "").strip()
        if not reference:
            return Response({"error": "reference is required."}, status=400)

        # 1. Check local DB first (fastest — set by webhook or verify_payment)
        # Scope to request.organisation to prevent cross-org reference leakage
        ph = PaymentHistory.objects.filter(
            provider_payment_id=reference,
            status=PaymentHistory.Status.SUCCEEDED,
            subscription__organisation=request.organisation,
        ).select_related("subscription").first()

        if ph and ph.subscription:
            return Response({
                "status": "success",
                "subscription": SubscriptionSerializer(ph.subscription).data,
            })

        # 2. Silently ask Paystack
        try:
            sub = PaystackSubscriptionService.verify_payment(request.organisation, reference)
            return Response({
                "status": "success",
                "subscription": SubscriptionSerializer(sub).data,
            })
        except ValueError:
            return Response({"status": "pending"})

    @action(detail=False, methods=["post"], url_path="start-trial",
            permission_classes=[IsAuthenticated])
    def start_trial(self, request):
        """
        POST /api/v1/subscriptions/start-trial/
        Body: { "plan_id": "<uuid>", "org_id": "<uuid>" (optional) }

        Start a 14-day free trial on the chosen paid plan.
        Permission is relaxed to IsAuthenticated because this is called during
        onboarding before the Tauri client has a reliable X-Organisation-ID header.
        Org resolution falls back to raw SQL (bypassing RLS) using the SENTINEL GUC
        pattern so pgBouncer transaction-mode connections work correctly.
        """
        plan_id = request.data.get("plan_id")
        if not plan_id:
            return Response({"error": "plan_id is required."}, status=400)

        org = getattr(request, "organisation", None)
        if org is None:
            org_id_hint = (
                request.data.get("org_id")
                or request.headers.get("X-Organisation-ID")
                or request.query_params.get("org")
            )
            org = _resolve_org_for_user_raw(request.user, org_id_hint)
        if org is None:
            return Response({"error": "No organisation context found."}, status=400)

        try:
            plan = Plan.objects.get(id=plan_id, is_active=True)
        except Plan.DoesNotExist:
            return Response({"error": "Plan not found."}, status=400)

        # Free plan (price=0): activate with no expiry instead of starting a trial
        if float(plan.price) == 0:
            sub = SubscriptionService.activate_free_plan(org)
            return Response(SubscriptionSerializer(sub).data, status=status.HTTP_200_OK)

        sub = SubscriptionService.start_trial_for_plan(org, plan)
        return Response(SubscriptionSerializer(sub).data, status=status.HTTP_201_CREATED)

    @action(
        detail=False, methods=["post"],
        url_path="recommend-plan",
        permission_classes=[IsAuthenticated],
    )
    def recommend_plan(self, request):
        """
        POST /api/v1/subscriptions/recommend-plan/
        Body: { "answers": { "business_type": "...", "team_size": "...", ... } }

        Uses Groq AI (with rule-based fallback) to recommend the best plan.
        Returns:
          {
            "recommended_plan_slug": "professional",
            "confidence": "high",
            "reasons": ["...", "...", "..."],
            "alternative_plan_slug": "starter",
            "alternative_reasons": ["..."],
            "plans": [{ id, name, slug, price, features, ... }]
          }
        """
        answers = request.data.get("answers", {})
        if not answers:
            return Response({"error": "answers are required."}, status=400)

        plans = list(
            Plan.objects.filter(is_active=True, is_public=True).order_by("display_order", "price")
        )
        if not plans:
            return Response({"error": "No plans available."}, status=503)

        plan_context = [
            {
                "name": p.name,
                "slug": p.slug,
                "price": f"₦{float(p.price):,.0f}/month",
                "features": p.features,
            }
            for p in plans
        ]

        groq_key = getattr(settings, "GROQ_API_KEY", "")
        recommendation = None

        if groq_key:
            try:
                recommendation = _ai_recommend(answers, plan_context, groq_key)
                logger.info("AI plan recommendation: %s (confidence: %s)",
                            recommendation.get("recommended_plan_slug"),
                            recommendation.get("confidence"))
            except Exception as exc:
                logger.warning("AI recommendation failed, using rules: %s", exc)

        if recommendation is None:
            recommendation = _rule_recommend(answers, plans)

        # Attach full plan data so frontend has everything in one call
        recommendation["plans"] = PlanSerializer(plans, many=True).data
        return Response(recommendation)

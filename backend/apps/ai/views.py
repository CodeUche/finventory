"""
AI Financial Assistant — "Explain My Money"

Aggregates the organisation's real financial data and queries Groq's free
LLM API to produce plain-English insights and answer user questions.

Uses Groq (groq.com) — free tier: 14,400 req/day, 30 req/min, globally
available including Nigeria.  No billing required.  Uses the
`requests` package which is already a dependency (no extra SDK needed).

Security:
  - All endpoints require IsAuthenticated + IsStaff.
  - Financial data is always scoped to request.organisation (tenant isolation).
  - The Groq API key is stored server-side only; it never reaches the client.
  - User input is sanitised and length-capped before being sent to the LLM.
"""

import logging
from decimal import Decimal

from django.conf import settings
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import IsStaff

logger = logging.getLogger(__name__)

# Maximum characters the user can send in a single message
MAX_USER_MSG_LEN = 1_000


# ── Data aggregation ──────────────────────────────────────────────────────────

def _gather_financial_summary(organisation) -> dict:
    """
    Gather key financial metrics for the organisation.

    Returns a dict safe to serialise into an LLM system prompt.
    All monetary values are strings to avoid Decimal serialisation issues.
    """
    from datetime import date
    from django.db.models import Sum, Count, Q

    today = date.today()
    month_start = today.replace(day=1)

    # ── Revenue (confirmed + credit invoices) ────────────────────────────────
    try:
        from apps.sales.models import Invoice
        invoices = Invoice.objects.filter(
            organisation=organisation,
            status__in=["confirmed", "credit", "partial"],
        )
        revenue_mtd = invoices.filter(
            invoice_date__gte=month_start
        ).aggregate(s=Sum("total_amount"))["s"] or Decimal("0")
        revenue_total = invoices.aggregate(s=Sum("total_amount"))["s"] or Decimal("0")
        invoice_count = invoices.count()
        overdue_count = invoices.filter(
            due_date__lt=today,
            status__in=["confirmed", "partial"],
        ).count()
    except Exception:
        revenue_mtd = revenue_total = Decimal("0")
        invoice_count = overdue_count = 0

    # ── Expenses ─────────────────────────────────────────────────────────────
    try:
        from apps.expenses.models import Expense
        expenses = Expense.objects.filter(organisation=organisation)
        expense_mtd = expenses.filter(
            date__gte=month_start
        ).aggregate(s=Sum("amount"))["s"] or Decimal("0")
        expense_total = expenses.aggregate(s=Sum("amount"))["s"] or Decimal("0")

        top_exp_cats = (
            expenses.values("category__name")
            .annotate(total=Sum("amount"))
            .order_by("-total")[:5]
        )
        top_expense_categories = [
            {"category": r["category__name"] or "Uncategorised", "amount": str(r["total"])}
            for r in top_exp_cats
        ]
    except Exception:
        expense_mtd = expense_total = Decimal("0")
        top_expense_categories = []

    # ── Payroll ───────────────────────────────────────────────────────────────
    try:
        from apps.payroll.models import PayrollRun, Employee
        latest_run = PayrollRun.objects.filter(
            organisation=organisation,
        ).order_by("-created_at").first()
        payroll_net = str(latest_run.total_net) if latest_run else "0"
        payroll_gross = str(latest_run.total_gross) if latest_run else "0"
        employee_count = Employee.objects.filter(
            organisation=organisation, is_active=True
        ).count()
    except Exception:
        payroll_net = payroll_gross = "0"
        employee_count = 0

    # ── Cash position ─────────────────────────────────────────────────────────
    try:
        from apps.sales.models import SalePayment
        cash_in = SalePayment.objects.filter(
            invoice__organisation=organisation,
            payment_method="cash",
        ).aggregate(s=Sum("amount"))["s"] or Decimal("0")
        bank_in = SalePayment.objects.filter(
            invoice__organisation=organisation,
            payment_method__in=["bank_transfer", "pos"],
        ).aggregate(s=Sum("amount"))["s"] or Decimal("0")
    except Exception:
        cash_in = bank_in = Decimal("0")

    # ── Inventory ─────────────────────────────────────────────────────────────
    try:
        from apps.inventory.models import Product, StockItem
        product_count = Product.objects.filter(organisation=organisation).count()
        low_stock_count = StockItem.objects.filter(
            product__organisation=organisation,
            quantity__lte=models_low_stock_threshold(organisation),
        ).count()
    except Exception:
        product_count = low_stock_count = 0

    # ── Bills / AP ────────────────────────────────────────────────────────────
    try:
        from apps.bills.models import Bill
        bills_due = Bill.objects.filter(
            organisation=organisation,
            status__in=["received", "partial"],
        ).aggregate(s=Sum("total_amount"))["s"] or Decimal("0")
        overdue_bills = Bill.objects.filter(
            organisation=organisation,
            status__in=["received", "partial"],
            due_date__lt=today,
        ).count()
    except Exception:
        bills_due = Decimal("0")
        overdue_bills = 0

    # ── Customers with outstanding credit ────────────────────────────────────
    try:
        from apps.customers.models import Customer
        outstanding_credit = Customer.objects.filter(
            organisation=organisation,
            outstanding_balance__gt=0,
        ).aggregate(s=Sum("outstanding_balance"))["s"] or Decimal("0")
        credit_customer_count = Customer.objects.filter(
            organisation=organisation,
            outstanding_balance__gt=0,
        ).count()
    except Exception:
        outstanding_credit = Decimal("0")
        credit_customer_count = 0

    currency = organisation.currency or "NGN"

    return {
        "currency": currency,
        "org_name": organisation.name,
        "revenue_this_month": str(revenue_mtd),
        "revenue_all_time": str(revenue_total),
        "invoice_count": invoice_count,
        "overdue_invoices": overdue_count,
        "expense_this_month": str(expense_mtd),
        "expense_all_time": str(expense_total),
        "top_expense_categories": top_expense_categories,
        "payroll_latest_gross": payroll_gross,
        "payroll_latest_net": payroll_net,
        "active_employees": employee_count,
        "cash_collected": str(cash_in),
        "bank_transfers_collected": str(bank_in),
        "accounts_payable": str(bills_due),
        "overdue_bills": overdue_bills,
        "outstanding_credit_from_customers": str(outstanding_credit),
        "customers_with_credit": credit_customer_count,
        "product_count": product_count,
    }


def models_low_stock_threshold(organisation):
    return 5


def _build_system_prompt(organisation, summary: dict) -> str:
    """Build the system prompt sent to Claude with org financial context."""
    custom_ctx = organisation.ai_custom_context.strip() if organisation.ai_custom_context else ""

    lines = [
        f"You are Audity AI, the intelligent financial assistant for {summary['org_name']}.",
        "You help business owners understand their finances in plain, friendly English.",
        "You are concise, insightful, and action-oriented — never use jargon without explaining it.",
        "",
        f"Current financial snapshot ({summary['currency']}):",
        f"- Revenue this month: {summary['currency']} {summary['revenue_this_month']}",
        f"- Revenue all time: {summary['currency']} {summary['revenue_all_time']}",
        f"- Expenses this month: {summary['currency']} {summary['expense_this_month']}",
        f"- Total invoices: {summary['invoice_count']} (overdue: {summary['overdue_invoices']})",
        f"- Active employees: {summary['active_employees']}",
        f"- Latest payroll gross/net: {summary['payroll_latest_gross']} / {summary['payroll_latest_net']}",
        f"- Accounts payable (bills due): {summary['currency']} {summary['accounts_payable']} ({summary['overdue_bills']} overdue)",
        f"- Customer credit outstanding: {summary['currency']} {summary['outstanding_credit_from_customers']} ({summary['customers_with_credit']} customers)",
        f"- Products: {summary['product_count']}",
    ]

    if summary["top_expense_categories"]:
        lines.append("- Top expense categories:")
        for cat in summary["top_expense_categories"]:
            lines.append(f"    • {cat['category']}: {summary['currency']} {cat['amount']}")

    if custom_ctx:
        lines += ["", "Business context provided by the owner:", custom_ctx]

    lines += [
        "",
        "Always be helpful, accurate, and compassionate. If you detect a financial risk, mention it gently.",
        "Format responses clearly — use bullet points for lists and bold for key numbers.",
        "Never fabricate data. Only comment on what the data above shows.",
    ]

    return "\n".join(lines)


# ── Views ─────────────────────────────────────────────────────────────────────

# Groq free tier: 14,400 req/day, 30 req/min — available globally including Nigeria.
# Get a free key at https://console.groq.com/keys
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.1-8b-instant"  # Fast, free, 131k context window


class AIStatusView(APIView):
    """GET /api/v1/ai/status/ — Check if AI is available for this org."""
    permission_classes = [IsAuthenticated, IsStaff]

    def get(self, request):
        api_key = getattr(settings, "GROQ_API_KEY", "")
        available = bool(api_key)
        return Response({"available": available, "provider": "groq"})


class AIChatView(APIView):
    """
    POST /api/v1/ai/chat/
    Body: { "message": "Am I making profit?" }
    Returns: { "response": "...", "summary": {...} }
    """
    permission_classes = [IsAuthenticated, IsStaff]

    def post(self, request):
        api_key = getattr(settings, "GROQ_API_KEY", "")
        if not api_key:
            return Response(
                {"error": "AI assistant is not configured. Add GROQ_API_KEY to your server environment. Get a free key at console.groq.com/keys"},
                status=503,
            )

        raw_message = (request.data.get("message") or "").strip()
        if not raw_message:
            return Response({"error": "Message is required."}, status=400)

        # Sanitise: cap length to prevent prompt injection via long inputs
        message = raw_message[:MAX_USER_MSG_LEN]

        try:
            org = request.organisation
            summary = _gather_financial_summary(org)
            system_prompt = _build_system_prompt(org, summary)
        except Exception as exc:
            logger.exception("Failed to gather financial data for AI: %s", exc)
            return Response({"error": "Could not load financial data."}, status=500)

        try:
            import requests as http_requests

            # Groq uses the OpenAI-compatible chat completions format
            payload = {
                "model": GROQ_MODEL,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": message},
                ],
                "max_tokens": 1024,
                "temperature": 0.7,
            }

            resp = http_requests.post(
                GROQ_API_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=30,
            )

            if resp.status_code != 200:
                err_body = resp.json() if resp.content else {}
                err_detail = err_body.get("error", {}).get("message", resp.text[:300])
                err_status = resp.status_code
                logger.error("Groq API error %s: %s", err_status, err_detail)

                if err_status == 401:
                    friendly = "Invalid Groq API key. Check GROQ_API_KEY in your server .env file."
                elif err_status == 429:
                    friendly = "AI rate limit reached (30 req/min on free tier). Please wait a moment and try again."
                else:
                    friendly = f"AI service error: {err_detail[:200]}"

                return Response({"error": friendly}, status=502)

            data = resp.json()
            answer = data["choices"][0]["message"]["content"]

        except Exception as exc:
            logger.exception("Groq API error: %s", exc)
            return Response(
                {"error": f"AI service error: {str(exc)[:200]}"},
                status=502,
            )

        return Response({"response": answer, "summary": summary})


class AIModelsView(APIView):
    """GET /api/v1/ai/models/ — diagnostic endpoint (no longer needed)."""
    permission_classes = [IsAuthenticated, IsStaff]

    def get(self, request):
        return Response({
            "provider": "groq",
            "model": GROQ_MODEL,
            "models": [{"name": GROQ_MODEL, "displayName": "Llama 3.1 8B (Groq)"}],
        })
        return Response({"models": supported})

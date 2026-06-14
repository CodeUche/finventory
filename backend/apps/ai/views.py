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
from apps.core.throttles import AISupportRateThrottle

logger = logging.getLogger(__name__)

# Maximum characters the user can send in a single message
MAX_USER_MSG_LEN = 1_000

# Prompt injection defence — cap length and strip newlines from data values
# embedded in the system prompt (org name, category names, custom context).
_PROMPT_DATA_MAX = 200
_CUSTOM_CTX_MAX = 500


def _sanitize(value: str, max_len: int = _PROMPT_DATA_MAX) -> str:
    """Strip control characters and newlines to prevent prompt injection."""
    if not value:
        return ""
    # Replace any whitespace sequence (including \n \r \t) with a single space
    import re
    value = re.sub(r'\s+', ' ', value).strip()
    return value[:max_len]


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

    # ── Revenue (all invoices that represent actual sales) ────────────────────
    # Includes: paid, confirmed, partially_paid, credit, overdue.
    # Excludes: proforma (not yet confirmed), voided, returned.
    REVENUE_STATUSES = ["paid", "confirmed", "partially_paid", "credit", "overdue"]
    try:
        from apps.sales.models import Invoice
        invoices = Invoice.objects.filter(
            organisation=organisation,
            status__in=REVENUE_STATUSES,
        )
        revenue_mtd = invoices.filter(
            issue_date__gte=month_start
        ).aggregate(s=Sum("total_amount"))["s"] or Decimal("0")
        revenue_total = invoices.aggregate(s=Sum("total_amount"))["s"] or Decimal("0")
        invoice_count = invoices.count()
        overdue_count = invoices.filter(
            due_date__lt=today,
            status__in=["confirmed", "partially_paid", "overdue"],
        ).count()
    except Exception:
        logger.exception("AI: failed to gather invoice/revenue data")
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
        logger.exception("AI: failed to gather expense data")
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
        logger.exception("AI: failed to gather payroll data")
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
        logger.exception("AI: failed to gather cash/payment data")
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
        logger.exception("AI: failed to gather inventory data")
        product_count = low_stock_count = 0

    # ── Bills / AP ────────────────────────────────────────────────────────────
    try:
        from apps.bills.models import Bill
        bills_due = Bill.objects.filter(
            organisation=organisation,
            status__in=["received", "approved", "partially_paid"],
        ).aggregate(s=Sum("total_amount"))["s"] or Decimal("0")
        overdue_bills = Bill.objects.filter(
            organisation=organisation,
            status__in=["received", "approved", "partially_paid"],
            due_date__lt=today,
        ).count()
    except Exception:
        logger.exception("AI: failed to gather bills/AP data")
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
        logger.exception("AI: failed to gather customer credit data")
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
    custom_ctx = _sanitize(organisation.ai_custom_context or "", max_len=_CUSTOM_CTX_MAX)
    org_name = _sanitize(summary['org_name'])

    lines = [
        f"You are Audity AI, the intelligent financial assistant for {org_name}.",
        "You help business owners understand their finances in plain, friendly English.",
        "You are concise, insightful, and action-oriented — never use jargon without explaining it.",
        "",
        f"LIVE FINANCIAL DATA for {org_name} (currency: {summary['currency']}):",
        "",
        "REVENUE & SALES:",
        f"- Revenue this month: {summary['currency']} {summary['revenue_this_month']}",
        f"- Revenue all time (total invoiced): {summary['currency']} {summary['revenue_all_time']}",
        f"- Total invoices raised: {summary['invoice_count']}",
        f"- Overdue invoices: {summary['overdue_invoices']}",
        "",
        "CASH COLLECTED (actual payments received):",
        f"- Cash payments collected: {summary['currency']} {summary['cash_collected']}",
        f"- Bank/POS transfers collected: {summary['currency']} {summary['bank_transfers_collected']}",
        "",
        "EXPENSES:",
        f"- Expenses this month: {summary['currency']} {summary['expense_this_month']}",
        f"- Total expenses all time: {summary['currency']} {summary['expense_all_time']}",
        "",
        "PEOPLE & PAYROLL:",
        f"- Active employees: {summary['active_employees']}",
        f"- Latest payroll gross: {summary['currency']} {summary['payroll_latest_gross']}",
        f"- Latest payroll net (take-home): {summary['currency']} {summary['payroll_latest_net']}",
        "",
        "PAYABLES & CREDIT:",
        f"- Accounts payable (bills owed to suppliers): {summary['currency']} {summary['accounts_payable']} ({summary['overdue_bills']} overdue bills)",
        f"- Credit owed by customers: {summary['currency']} {summary['outstanding_credit_from_customers']} ({summary['customers_with_credit']} customers with outstanding balance)",
        "",
        "INVENTORY:",
        f"- Total products in catalogue: {summary['product_count']}",
    ]

    if summary["top_expense_categories"]:
        lines.append("")
        lines.append("TOP EXPENSE CATEGORIES:")
        for cat in summary["top_expense_categories"]:
            lines.append(f"  • {_sanitize(cat['category'])}: {summary['currency']} {cat['amount']}")

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
            from apps.core.permissions import _get_or_resolve_org
            org = _get_or_resolve_org(request)
            if org is None:
                return Response({"error": "No organisation context. Please include the X-Organisation-ID header."}, status=400)
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


# ── Support Chat ───────────────────────────────────────────────────────────────

SUPPORT_SYSTEM_PROMPT = """
You are Audity Support, the friendly and knowledgeable in-app support assistant for Audity — a business management suite for Nigerian SMBs. You help users understand how to use every feature of the app.

Be concise, warm, and practical. Use bullet points for steps. Never make up features that don't exist.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
AUDITY COMPLETE FEATURE KNOWLEDGE BASE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

## ACCOUNT & AUTHENTICATION
- **Create account**: Go to audity.app → "Create Account" → enter your name, email, and password → verify your email via the link sent to your inbox.
- **Login**: Enter your registered email and password. If MFA is enabled, enter the 6-digit code from your authenticator app.
- **Forgot password**: On the login page, click "Forgot password?" → enter your email → check your inbox for a reset link.
- **Multi-Factor Authentication (MFA)**: Go to Settings → Security tab → enable MFA → scan the QR code with Google Authenticator or Authy → enter the 6-digit code to confirm.
- **Change password**: Settings → Security tab → Change Password section.
- **Update profile**: Settings → Profile tab → update your name, email, or phone number.
- **Dark/Light mode**: Settings → Appearance tab → choose Dark or Light theme. The preference is saved locally.

## ORGANISATION SETUP
- **Create an organisation**: After registering, the onboarding wizard guides you to name your business, select your currency and industry.
- **Switch between organisations**: Click your organisation name in the sidebar → a list of your organisations appears → click to switch.
- **Update organisation details**: Settings → Organisation tab → update name, address, phone, business registration number, etc.
- **Set your logo**: Settings → Organisation tab → upload a logo (used on invoices and receipts).
- **Currency**: Set during onboarding. Currently cannot be changed after setup — contact support if needed.
- **Invoice template**: Settings → Organisation tab → choose between Classic, Modern, or Minimal invoice layouts.

## PLANS & BILLING
- **Free plan**: Up to 20 products, 20 customers, 10 invoices/month, 10 expenses/month, 1 user, 1 warehouse. Includes VAT Classes. Permanently free — no expiry.
- **Professional plan**: ₦19,500/month — up to 500 products, 5 users, 3 warehouses, advanced reports, quotes, recurring invoices, purchase orders, bills, budgets, audit log, team permissions.
- **Business plan**: ₦35,000/month — unlimited everything, plus payroll, full accounting ledger, API access, owner analytics, WHT, excise duty, filing guide.
- **Annual plans**: Professional Annual = ₦214,500/year (save 1 month). Business Annual = ₦385,000/year (save 1 month).
- **Upgrade plan**: Billing & Plans page → click "Get Started" on your desired plan → complete payment via Paystack.
- **Plan limit reached**: You'll see an orange error toast. Upgrade your plan to increase limits.
- **Payment method**: Audity uses Paystack for all subscription payments — card, bank transfer, or USSD.
- **Billing & Plans page**: Accessible from the sidebar under ACCOUNT → Billing & Plans (owner only).

## PRODUCTS & INVENTORY
- **Add a product**: Inventory → Products → "Add Product" → fill in type, name, SKU, prices, and optionally an opening stock quantity.
- **Product types**:
  - Physical: Items you can touch and track (clothing, drinks, electronics). Stock is tracked.
  - Service: Things you do for customers (consulting, repairs). No stock tracking.
  - Digital: Files or downloads. No stock tracking.
- **SKU**: A unique code you create for each product (e.g. "COKE-50CL", "SHIRT-RED-L"). Leave blank to auto-generate.
- **Opening stock**: When creating a physical product, enter the current quantity and select a warehouse location. This sets the starting inventory count.
- **Cost Price**: What you paid to buy or produce each unit. Never shown to customers. Used for profit calculations.
- **Selling Price**: The price charged to customers — appears on invoices.
- **Owner Cost Price**: A private cost price only visible to the owner. Used in owner profit analytics. Hidden from staff.
- **Reorder level**: A threshold quantity. When stock falls below this, you'll get a low-stock alert.
- **Edit a product**: Click the pencil icon on any product row.
- **Sales history per product**: Click the History (clock) icon on a product row to see all past sales of that product.
- **Stock levels**: Inventory → Stock Levels — shows stock per product per warehouse.
- **Low stock badge**: Red = below reorder level; Amber = between reorder level and 1.5× reorder level; Green = healthy.
- **Adjust stock manually**: Inventory → Stock Levels → Adjust button → enter quantity and reason. Useful for corrections or write-offs.
- **Batches & Lots**: Inventory → Batches & Lots — track products with expiry dates (e.g. food, medicine). Set batch number, quantity, unit cost, manufacture date, and expiry date. Expiring batches (within 30 days) show as orange notifications in the bell icon.
- **Warehouses / Locations**: Inventory → Locations — manage multiple store locations or warehouses. Set a default location for new stock.
- **Profit/margin column**: Products table shows profit per unit and percentage margin for each product.

## SALES & INVOICING
- **Create an invoice**: Sales → New Sale → select customer (or "Walk-in / No customer") → add products/services → set payment method and date → Save.
- **Invoice statuses**:
  - Draft: Saved but not yet confirmed. No stock is deducted.
  - Proforma: A quotation in invoice format. No stock deducted. Confirm it later.
  - Confirmed: Stock deducted, customer balance updated.
  - Partial: Customer has paid some but not all.
  - Paid/Credit: Fully paid.
  - Overdue: Due date has passed without full payment.
- **Proforma invoices**: In New Sale, click "Save as Proforma". Later, open the invoice and click "Confirm Proforma → Invoice" to convert it to a real invoice and deduct stock.
- **Record a payment**: Open an invoice → click "Record Payment" in the drawer → enter amount and payment method.
- **Payment methods**: Cash, Bank Transfer, POS, Cheque, Credit (deferred payment).
- **VAT on invoices**: If a product has a VAT class assigned, VAT is auto-calculated when added to an invoice.
- **Send invoice by email**: Open an invoice → click the email icon → enter recipient email → the invoice is sent as an HTML email from your configured SMTP.
- **Download invoice PDF**: Open an invoice → click the PDF/download icon.
- **Delivery notes**: Open an invoice → click "Delivery Note" → a PDF delivery note is generated.
- **Sales returns / Refunds**: Open an invoice → "Process Return" → select items and quantities to return → stock is automatically restocked.
- **Invoice folders**: Create folders to organise invoices (e.g. by client or project). Click the folder icon in the Sales header.
- **Recurring invoices**: Sales → Recurring — set up invoices that auto-generate on a schedule (weekly, monthly, etc.) for retainer clients.
- **Invoice number format**: Auto-generated as INV-XXXX-000001 (unique per organisation). Cannot be changed manually.
- **Overdue invoices**: Automatically marked overdue when the due date passes. You'll see them in the overdue count on the dashboard.

## QUOTES & ESTIMATES
- **Create a quote**: Quotes → New Quote → select customer → add products/services → save. Set status (Draft, Sent, Accepted, Rejected).
- **Convert quote to invoice**: Open a quote → click "Convert to Invoice". Stock is then deducted.
- **Quote validity**: Expired quotes (past validity date) are highlighted with an amber left border.
- **Quote statuses**: Draft → Sent → Accepted or Rejected.

## CUSTOMERS
- **Add a customer**: Customers → Add Customer → enter name, email, phone, address.
- **Customer types**: Retail, Wholesale, Distributor, Corporate, Client, Passenger, VIP, Government, NGO.
- **Customer credit**: When you record a "Credit" payment on an invoice, the customer's outstanding balance increases. Manage credits under CRM → Credits.
- **Customer statement**: Open a customer → click "Statement" → choose a date range → see all invoices, payments, and running balance.
- **Customer credit balance**: Shown on the customer drawer. Red = owes money. Track multiple customers with balances on the Credits page.
- **Free plan limit**: Up to 20 customers. Upgrade to Professional for unlimited customers.

## PURCHASE ORDERS & SUPPLIERS
- **Add a supplier**: Procurement → Suppliers → Add Supplier.
- **Create a purchase order (PO)**: Procurement → Purchase Orders → New PO → select supplier → add items with quantity and unit cost → save.
- **Receive a PO**: Open a PO → "Mark as Received" → stock is automatically added to the selected warehouse.
- **Walk-in / no supplier**: You can create a PO without selecting a supplier by choosing "Walk-in / No supplier".
- **PO receipt upload**: Attach a receipt image or PDF to a received PO.
- **PO statuses**: Draft → Ordered → Partially Received → Received → Cancelled.
- **Unit cost auto-fill**: When you select a product in a PO line, the cost price auto-fills from the product's cost price.

## BILLS & ACCOUNTS PAYABLE
- **Add a bill**: Procurement → Bills (AP) → New Bill → enter supplier, due date, line items (with categories), and any tax.
- **Bill statuses**: Draft → Received → Partial → Paid → Overdue.
- **Mark a bill paid**: Open a bill → Record Payment → enter amount and date.
- **Edit a bill**: Bills in Draft or Received status can be edited by clicking the edit (pencil) icon.
- **Bill folders**: Organise bills into folders (e.g. "FIRS", "Utilities"). Click "Folders" in the Bills header.
- **AP Aging report**: Reports page → AP Aging — shows how long outstanding bills have been unpaid (Current, 1–30 days, 31–60 days, etc.).
- **Tax on bills**: Select a VAT class or enter a manual percentage. The tax amount is auto-calculated.
- **Filter by status tiles**: Click the Total Payable, Overdue, Due This Week, or Paid This Month tiles to filter the bill list.

## EXPENSES & INCOME
- **Record an expense**: Cash Flow → Income & Expenses → Add Expense → enter amount, category, date, and optional notes.
- **Record income**: Same page → Add Income → tracks non-invoice income (e.g. grants, interest).
- **Expense categories**: Choose from preset categories (rent, salaries, utilities, etc.). New categories are auto-created if you type a new name.
- **Previous price**: Enter what you paid previously for the same expense — the app shows real-time savings.
- **Group by category**: Toggle "Group by Category" on the Expenses page to see totals per expense category as card tiles above the table.
- **Free plan limit**: Up to 10 expenses/month. Upgrade to Professional for unlimited.

## TAX MANAGEMENT
- **VAT Classes**: Tax → VAT Classes tab — create rate groups (e.g. "Standard VAT" at 7.5%, "Zero-Rated" at 0%, "Exempt"). Assign a VAT class to products. Available on all plans.
- **Income Tax**: Tax → Income Tax tab — configure tax brackets or flat rates for PAYE calculations. Available on Professional and Business plans.
- **Tax Tools**: Tax → Tax Tools — calculate income tax for a given gross income. Available on Professional and Business plans.
- **WHT (Withholding Tax)**: Tax → WHT tab — set up WHT rates for different payment types. Business plan only.
- **Excise Duty**: Tax → Excise Duty tab — track excise duty on regulated products (alcohol, tobacco). Business plan only.
- **Filing Guide**: Tax → Filing Guide tab — step-by-step guide for Nigerian tax filing (VAT returns, PAYE remittance, etc.). Business plan only.
- **VAT on invoices**: Assign a VAT class to a product → when added to an invoice, VAT is auto-calculated and shown as a line item.
- **VAT Summary report**: Reports → VAT Summary — shows total VAT collected and reclaimable within a date range.

## PAYROLL (Business plan only)
- **Add an employee**: Payroll → Employees → Add Employee → fill in name, email, department, gross salary, bank details.
- **Bank verification**: Enter account number and select bank → click "Verify" to auto-fill the account name via Paystack bank resolve.
- **Run payroll**: Payroll → Payroll Runs → New Run → select month/year → the system auto-calculates PAYE tax and pension deductions for all active employees.
- **PAYE**: Automatically computed using the configured income tax brackets. Uses the Nigerian progressive tax scale by default.
- **Pension**: Computed as 8% employee + 10% employer of gross salary (PENCOM standard).
- **Payroll net pay**: Gross salary minus PAYE minus employee pension contribution.
- **FIRS PAYE remittance**: After running payroll, click the FIRS link to go to the TaxProMax portal for official remittance.
- **Payroll history**: Each run is saved with a breakdown per employee.

## REPORTS & ANALYTICS
- **Profit & Loss (P&L)**: Reports → P&L — shows revenue, cost of goods sold, gross profit, expenses, and net profit for any date range.
- **Sales Summary**: Reports → Sales — total revenue, invoice count, average order value, and a daily revenue chart for the selected period.
- **Top Products**: Reports → Top Products — ranked by revenue and units sold.
- **Top Customers**: Reports → Top Customers — ranked by total spend.
- **Expense Breakdown**: Reports → Expenses — donut chart showing spending by category.
- **Cash Flow Statement**: Reports → Cash Flow — operating, investing, and financing activities.
- **Inventory Valuation**: Reports → Inventory — total stock value per product/warehouse.
- **AR Aging**: Reports → AR Aging — how long customers have owed money (Current, 1–30, 31–60, 61–90, 90+ days).
- **AP Aging**: Reports → AP Aging — same but for bills you owe suppliers.
- **VAT Summary**: Reports → VAT Summary — total VAT collected and reclaimable for a period.
- **Balance Sheet**: Accounting → Balance Sheet — assets, liabilities, and equity as of today. Auto-calculated from your transactions.
- **Export/Print reports**: Most reports have an Export CSV or Print button at the top right.
- **Date range**: Use the "From / To" date pickers to filter any report by date range.

## ACCOUNTING (Business plan only)
- **Chart of Accounts (COA)**: Accounting → Chart of Accounts — view all GL accounts. Seeded automatically when you create an organisation.
- **Journal entries**: Accounting → Journal Entries — create manual double-entry journal entries. Every sale, bill, expense, and payroll run also auto-posts a journal entry.
- **Trial Balance**: Accounting → Chart of Accounts → "Trial Balance" button — shows all accounts with debit/credit totals. Has a CSV export and a balanced/not balanced indicator.
- **Fixed Assets**: Accounting → Fixed Assets — record depreciable assets (equipment, vehicles). Monthly depreciation is auto-posted via a scheduled task.
- **Bank Reconciliation**: Accounting → Bank Reconciliation — create a reconciliation, mark journal lines as cleared, and reconcile when the difference is < ₦0.01.
- **GL auto-posting**: All transactions (sales, bills, expenses, payroll) automatically post double-entry journal entries to the General Ledger. No manual posting needed.

## BUDGETS
- **Create a budget**: Cash Flow → Budgets → New Budget → set a name, period (daily/weekly/monthly/quarterly/annual), and start date.
- **Add budget lines**: Per category — enter unit price × quantity to auto-calculate the budgeted amount.
- **Activate a budget**: Managers and owners can activate/deactivate budgets.
- **Budget vs Actual**: See actual spend vs budgeted amount per category. Variance is shown as a percentage.
- **Budget audit trail**: All changes to budgets are logged with who made them and when.

## TEAM & PERMISSIONS (Professional & Business)
- **Invite a team member**: Settings → Team tab → Invite → enter email and select role.
- **Roles**:
  - Owner: Full access to everything. Created automatically.
  - Admin: Full access except billing.
  - Manager: Can manage sales, purchases, inventory, and expenses.
  - Accountant: Access to accounting, reports, and tax.
  - Staff: Basic sales and customer access.
  - Viewer: Read-only access.
- **Module permissions**: Beyond roles, you can set per-module access (None / View / Write / Edit) for each team member in Settings → Team → expand a member row.
- **Deactivate a member**: Toggle the active status on a team member's row.
- **Maximum members**: Free plan = 1 user. Professional = up to 5. Business = unlimited.

## EMAIL & SMTP SETTINGS
- **Configure email**: Settings → Email tab → enter SMTP host, port, username, password, and sender name. Used to send invoices to customers.
- **Test email**: After saving SMTP settings, use the test email button to verify.
- **Common SMTP settings**:
  - Gmail: smtp.gmail.com, port 587, TLS. Use an App Password (not your main password).
  - Outlook: smtp.office365.com, port 587.
  - Zoho: smtp.zoho.com, port 587.

## PAYMENT GATEWAY
- **Set up Paystack for customer invoices**: Settings → Payment Gateway tab → enter your Paystack public and secret keys. This lets you accept card/USSD payments from customers.
- **Paystack for Audity subscriptions**: Audity itself uses Paystack to bill you for your plan — separate from your customer payment gateway.

## NOTIFICATIONS
- **Bell icon (top right)**: Shows two alert types:
  1. Low stock: Products at or below reorder level.
  2. Overdue invoices: Invoices past their due date.
  3. Expiring batches: Batches expiring within 30 days (shown in orange).
- **Notifications refresh**: Automatically refreshed every 30 seconds.

## AI FINANCIAL ASSISTANT
- **Access**: Available on the Dashboard — look for the "Explain My Money" or AI chat section.
- **What it does**: Analyses your real financial data (revenue, expenses, invoices, payroll) and answers questions in plain English.
- **Powered by**: Groq's Llama model (free tier).
- **Requires**: GROQ_API_KEY configured by your server administrator.
- **Questions you can ask**: "Am I making a profit?", "What are my biggest expenses?", "How much do customers owe me?", "Is my cash flow healthy?".

## SEARCH (Top bar)
- **Global search**: Type in the top search bar to instantly search across products, invoices, and customers.
- **Debounced search**: Results appear after 350ms automatically.
- **Click a result**: Navigates directly to that invoice, product, or customer.

## COMMON ISSUES & TROUBLESHOOTING
- **"Plan limit reached" error**: You've hit your plan's limit (e.g. 20 products on Free). Upgrade your plan from Billing & Plans.
- **Invoice not saving**: Check that all required fields are filled. If you see a red error, hover over it for details.
- **Stock not updating**: Ensure the product type is "Physical". Service and Digital products don't track stock.
- **Email not sending**: Go to Settings → Email tab and verify your SMTP settings. Try the test email button.
- **Paystack payment failed**: Ensure your Paystack public and secret keys are correct in Settings → Payment Gateway.
- **"Token not valid" error**: Your session has expired. Log out and log back in.
- **App loads slowly**: Check your internet connection. If offline, a yellow banner appears at the top — changes are queued and sync when reconnected.
- **Can't see a menu item**: The feature may not be available on your current plan, or your role may not have permission. Check Billing & Plans and Settings → Team.
- **MFA code not working**: Ensure your phone's time is synced. TOTP codes are time-based and only valid for 30 seconds.
- **Data not appearing after save**: Refresh the page or navigate away and back. If the issue persists, check your internet connection.
- **Can't edit a bill**: Only Draft and Received bills can be edited. Paid bills are locked.
- **Forgot to set opening stock**: Go to Inventory → Stock Levels → Adjust → enter the correct quantity for the product and warehouse.
- **Duplicate invoice number error**: Rarely happens — invoice numbers are auto-generated per organisation. Contact support if you see this repeatedly.
- **Customer statement is blank**: Ensure you've selected the correct date range and that the customer has invoices within that period.

## CONTACT & SUPPORT
- **In-app support**: Use this chat assistant (that's me!).
- **Email support**: support@audity.app
- **Response time**: Within 24 hours on business days.
- **Feedback / bugs**: Report issues at https://github.com/anthropics/claude-code/issues or email support.

Always be friendly, specific, and guide the user step-by-step. If a feature is plan-restricted, mention which plan unlocks it.
""".strip()


class AISupportView(APIView):
    """
    POST /api/v1/ai/support/
    Body: { "message": "How do I create an invoice?" }
    Returns: { "response": "..." }

    Stateless support chat — answers questions about how to use Audity.
    Uses the same Groq backend as the financial assistant.
    """
    authentication_classes = []
    permission_classes = []
    throttle_classes = [AISupportRateThrottle]

    def post(self, request):
        api_key = getattr(settings, "GROQ_API_KEY", "")
        if not api_key:
            return Response(
                {"error": "Support AI is not configured. Contact support@audity.app for help."},
                status=503,
            )

        raw_message = (request.data.get("message") or "").strip()
        if not raw_message:
            return Response({"error": "Message is required."}, status=400)

        message = raw_message[:MAX_USER_MSG_LEN]

        try:
            import requests as http_requests

            payload = {
                "model": GROQ_MODEL,
                "messages": [
                    {"role": "system", "content": SUPPORT_SYSTEM_PROMPT},
                    {"role": "user", "content": message},
                ],
                "max_tokens": 768,
                "temperature": 0.4,
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
                logger.error("Groq support API error %s: %s", resp.status_code, err_detail)
                if resp.status_code == 429:
                    return Response({"error": "Support AI is busy right now. Please try again in a moment."}, status=429)
                return Response({"error": "Support AI is temporarily unavailable."}, status=502)

            data = resp.json()
            answer = data["choices"][0]["message"]["content"]

        except Exception as exc:
            logger.exception("Support chat error: %s", exc)
            return Response({"error": "Support AI is temporarily unavailable."}, status=502)

        return Response({"response": answer})

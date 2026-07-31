"""
Till sessions — opening float, blind count, and the variance that follows.

The count is deliberately *blind*: the cashier enters what is physically in the
drawer before the system says what it expected. A confirmed count proves
nothing; a blind one is evidence. Any difference posts to Cash Over & Short so a
shortfall is a real number in the accounts rather than a note in someone's book.
"""

from __future__ import annotations

import logging
from decimal import Decimal

from django.db import transaction
from django.db.models import Count, Sum
from django.utils import timezone

from .models import TillSession, TillTenderCount

logger = logging.getLogger(__name__)
ZERO = Decimal("0")

# Only cash physically sits in a drawer. Card and transfer settle to the bank,
# so a "variance" there means a reconciliation problem, not a miscount.
CASH = "cash"

CASH_OVER_SHORT_CODE = "6800"
CASH_OVER_SHORT_NAME = "Cash Over and Short"


class TillSessionError(Exception):
    """Something about the shift is wrong — surfaced to the cashier as-is."""


class TillService:
    # ── Opening ─────────────────────────────────────────────────────────────
    @staticmethod
    def open_session(organisation, user, opening_float=ZERO, location=None, notes="") -> TillSession:
        """Start a shift. One open till per cashier — two would split the count."""
        existing = TillSession.objects.filter(
            organisation=organisation, opened_by=user, status=TillSession.Status.OPEN,
        ).first()
        if existing:
            raise TillSessionError(
                "You already have a till open. Close it before starting another."
            )
        opening_float = Decimal(str(opening_float or 0))
        if opening_float < 0:
            raise TillSessionError("The opening float cannot be negative.")

        return TillSession.objects.create(
            organisation=organisation, opened_by=user,
            opening_float=opening_float, location=location, notes=notes,
        )

    @staticmethod
    def current_session(organisation, user) -> TillSession | None:
        return TillSession.objects.filter(
            organisation=organisation, opened_by=user, status=TillSession.Status.OPEN,
        ).first()

    # ── Expected figures ────────────────────────────────────────────────────
    @staticmethod
    def expected_by_tender(session: TillSession) -> dict:
        """What the system says passed through this till, per tender.

        Driven by the payments actually linked to the session, so it cannot
        drift the way a timestamp window does when a shift runs past midnight
        or two cashiers overlap.
        """
        rows = (
            session.payments
            .values("method")
            .annotate(total=Sum("amount"), n=Count("id"))
            .order_by("method")
        )
        return {
            r["method"]: {"expected": Decimal(str(r["total"] or 0)), "count": r["n"]}
            for r in rows
        }

    @staticmethod
    def expected_cash(session: TillSession) -> Decimal:
        """Cash in the drawer = opening float + cash taken."""
        taken = session.payments.filter(method=CASH).aggregate(t=Sum("amount"))["t"] or ZERO
        return Decimal(str(session.opening_float)) + Decimal(str(taken))

    @staticmethod
    def summary(session: TillSession) -> dict:
        """Everything the close-till screen needs — without revealing the count."""
        by_tender = TillService.expected_by_tender(session)
        sales_total = sum((v["expected"] for v in by_tender.values()), ZERO)
        return {
            "id": str(session.id),
            "status": session.status,
            "opened_at": session.opened_at,
            "closed_at": session.closed_at,
            "opening_float": Decimal(str(session.opening_float)),
            "expected_cash": TillService.expected_cash(session),
            "sales_total": sales_total,
            "transaction_count": sum(v["count"] for v in by_tender.values()),
            "by_tender": by_tender,
            "cash_variance": Decimal(str(session.cash_variance)),
        }

    # ── Closing ─────────────────────────────────────────────────────────────
    @staticmethod
    @transaction.atomic
    def close_session(session: TillSession, user, counted: dict, reason="", notes="") -> TillSession:
        """Close the shift against a blind count.

        `counted` maps tender → amount physically counted. A tender the cashier
        did not count is treated as agreeing with the system, so only cash —
        which is the one that can actually go missing — forces a number.
        """
        session = TillSession.objects.select_for_update().get(pk=session.pk)
        if session.status == TillSession.Status.CLOSED:
            raise TillSessionError("This till has already been closed.")

        counted = counted or {}
        if CASH not in counted:
            raise TillSessionError("Enter the cash you counted before closing.")

        by_tender = TillService.expected_by_tender(session)
        # Cash carries the opening float; other tenders are sales only.
        expected_map = {m: v["expected"] for m, v in by_tender.items()}
        expected_map[CASH] = TillService.expected_cash(session)

        cash_variance = ZERO
        for method in sorted(set(expected_map) | set(counted)):
            expected = Decimal(str(expected_map.get(method, 0)))
            raw = counted.get(method)
            counted_amt = Decimal(str(raw)) if raw not in (None, "") else expected
            variance = counted_amt - expected
            if method == CASH:
                cash_variance = variance
            TillTenderCount.objects.update_or_create(
                organisation=session.organisation, session=session, method=method,
                defaults={
                    "expected": expected,
                    "counted": counted_amt,
                    "variance": variance,
                    "transaction_count": by_tender.get(method, {}).get("count", 0),
                },
            )

        session.status = TillSession.Status.CLOSED
        session.closed_by = user
        session.closed_at = timezone.now()
        session.cash_variance = cash_variance
        session.variance_reason = reason
        if notes:
            session.notes = notes
        session.save(update_fields=[
            "status", "closed_by", "closed_at", "cash_variance", "variance_reason",
            "notes", "updated_at",
        ])

        if cash_variance != ZERO:
            TillService.post_variance(session, user)
        else:
            # Nothing to post — say so explicitly rather than leaving it
            # 'pending', which would look like an unposted shortfall forever.
            session.gl_post_status = "posted"
            session.save(update_fields=["gl_post_status"])
        return session

    @staticmethod
    def post_variance(session: TillSession, user=None):
        """Short: DR Cash Over & Short / CR Cash. Over: the reverse.

        Routed through safe_post_gl so a failure lands on the session as
        `gl_post_status='failed'` instead of only a log line. Closing the till
        still never blocks — but an unposted shortfall now shows up on the GL
        Health screen and can be retried from there like any other posting.
        """
        from apps.accounting.services import safe_post_gl
        return safe_post_gl(
            TillService._post_variance_journal, session, user,
            model_instance=session,
        )

    @staticmethod
    def _post_variance_journal(session: TillSession, user=None):
        from apps.accounting.models import AccountType
        from apps.accounting.services import AccountingService, AccountMappingService

        org = session.organisation
        variance = Decimal(str(session.cash_variance))
        cash_acct = AccountMappingService.resolve(org, "cash_account")
        over_short = AccountingService._get_or_create_account(
            org, CASH_OVER_SHORT_CODE, CASH_OVER_SHORT_NAME, AccountType.EXPENSE,
        )
        amount = abs(variance)
        if variance < ZERO:   # short — cash is missing
            lines = [(over_short, amount, ZERO), (cash_acct, ZERO, amount)]
            label = "shortage"
        else:                 # over — more cash than the system expected
            lines = [(cash_acct, amount, ZERO), (over_short, ZERO, amount)]
            label = "overage"

        return AccountingService.post_journal_entry(
            org,
            description=f"Till {label} — {session.opened_by.get_full_name() or session.opened_by.email}",
            entry_date=(session.closed_at or timezone.now()).date(),
            lines=lines,
            created_by=user,
            ref="TILL",
            source_type="till_variance",
            source_ref=str(session.id),
        )

    # ── Z-report ────────────────────────────────────────────────────────────
    @staticmethod
    def z_report(session: TillSession) -> dict:
        """End-of-shift figures a manager can act on."""
        # Re-read: close_session works on a locked re-fetch, so a caller holding
        # the pre-close instance would otherwise report a zero variance.
        session = TillSession.objects.select_related("opened_by", "location").get(pk=session.pk)
        counts = list(session.tender_counts.all())
        sales_total = sum((Decimal(str(c.expected)) for c in counts
                           if c.method != CASH), ZERO)
        cash_sales = next(
            (Decimal(str(c.expected)) - Decimal(str(session.opening_float))
             for c in counts if c.method == CASH), ZERO,
        )
        return {
            "session_id": str(session.id),
            "cashier": session.opened_by.get_full_name() or session.opened_by.email,
            "location": session.location.name if session.location else "",
            "opened_at": session.opened_at,
            "closed_at": session.closed_at,
            "opening_float": Decimal(str(session.opening_float)),
            "sales_total": sales_total + cash_sales,
            "cash_variance": Decimal(str(session.cash_variance)),
            "variance_reason": session.variance_reason,
            "tenders": [
                {
                    "method": c.method,
                    "expected": Decimal(str(c.expected)),
                    "counted": Decimal(str(c.counted)),
                    "variance": Decimal(str(c.variance)),
                    "transaction_count": c.transaction_count,
                }
                for c in counts
            ],
        }

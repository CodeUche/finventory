"""
Settlement import and matching.

Same principles as the bank reconciliation matcher that already ships: exact
amount, a date window, a reference hit as a tie-breaker, one-to-one, and no
guessing. A payout that cannot be matched confidently is left for a person —
silently attaching it to the nearest sale would corrupt the ledger in a way
nobody would notice for months.
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from .settlement_models import SettlementBatch, SettlementLine

logger = logging.getLogger(__name__)
ZERO = Decimal("0")

# A terminal payout is usually same-day but can land the next working day.
DATE_TOLERANCE_DAYS = 3

# Column names seen across Nigerian terminal exports. Matching is case- and
# space-insensitive so a merchant never has to reformat their file.
_COLUMNS = {
    "provider_reference": [
        "reference", "transactionreference", "transactionref", "rrn", "retrievalreferencenumber",
        "paymentreference", "transactionid", "id",
    ],
    "amount": ["amount", "amountpaid", "transactionamount", "value", "credit"],
    "fee": ["fee", "charge", "charges", "commission", "mdr"],
    "paid_at": ["date", "datetime", "transactiondate", "paidat", "time", "createdat"],
    "terminal_id": ["terminal", "terminalid", "tid"],
    "card_last4": ["last4", "cardlast4", "maskedpan", "pan"],
    "narration": ["narration", "description", "remark", "details"],
}


class SettlementError(Exception):
    """Something a merchant should see, phrased for them."""


def _norm(header: str) -> str:
    return "".join(ch for ch in (header or "").lower() if ch.isalnum())


def _money(raw) -> Decimal:
    """Parse an amount from a spreadsheet cell: '₦12,400.00', '(500)', '1 200'."""
    text = str(raw or "").strip()
    if not text:
        return ZERO
    negative = text.startswith("(") and text.endswith(")")
    cleaned = "".join(ch for ch in text if ch.isdigit() or ch in ".-")
    if not cleaned or cleaned in {"-", "."}:
        return ZERO
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        return ZERO
    return -value if negative else value


class SettlementService:
    # ── Import ──────────────────────────────────────────────────────────────
    @staticmethod
    def parse_csv(content: str) -> list[dict]:
        """Turn a terminal export into rows we understand."""
        try:
            sample = content[:4096]
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        except Exception:
            dialect = csv.excel
        reader = csv.DictReader(io.StringIO(content), dialect=dialect)
        if not reader.fieldnames:
            raise SettlementError("That file has no column headings.")

        lookup = {}
        for field in reader.fieldnames:
            key = _norm(field)
            for target, names in _COLUMNS.items():
                if key in names and target not in lookup:
                    lookup[target] = field

        if "amount" not in lookup:
            raise SettlementError(
                "Could not find an amount column. Expected one named Amount, "
                "Amount Paid or Value."
            )

        rows = []
        for index, raw in enumerate(reader, start=2):
            amount = _money(raw.get(lookup["amount"]))
            if amount == ZERO:
                continue  # blank or heading row
            reference = str(raw.get(lookup.get("provider_reference", ""), "") or "").strip()
            rows.append({
                # Fall back to the row number so a file with no reference column
                # still imports — and still cannot be imported twice.
                "provider_reference": reference or f"row-{index}",
                "amount": amount,
                "fee": abs(_money(raw.get(lookup.get("fee", ""), 0))),
                "paid_at": SettlementService._parse_when(raw.get(lookup.get("paid_at", ""))),
                "terminal_id": str(raw.get(lookup.get("terminal_id", ""), "") or "")[:60],
                "card_last4": str(raw.get(lookup.get("card_last4", ""), "") or "")[-4:],
                "narration": str(raw.get(lookup.get("narration", ""), "") or "")[:300],
            })
        if not rows:
            raise SettlementError("No payouts were found in that file.")
        return rows

    @staticmethod
    def _parse_when(raw):
        text = str(raw or "").strip()
        if not text:
            return None
        parsed = parse_datetime(text)
        if parsed:
            return parsed if timezone.is_aware(parsed) else timezone.make_aware(parsed)
        day = parse_date(text[:10])
        if day:
            return timezone.make_aware(
                timezone.datetime.combine(day, timezone.datetime.min.time())
            )
        for fmt in ("%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%d/%m/%Y %H:%M", "%d/%m/%Y %H:%M:%S"):
            try:
                naive = timezone.datetime.strptime(text, fmt)
                return timezone.make_aware(naive)
            except ValueError:
                continue
        return None

    @staticmethod
    @transaction.atomic
    def import_rows(organisation, rows: list[dict], *, provider="", reference="",
                    source=SettlementBatch.Source.UPLOAD) -> SettlementBatch:
        """Store a batch, skipping payouts already imported.

        Re-importing yesterday's export must not duplicate the money, so the
        provider reference is unique per organisation and clashes are skipped
        rather than raising.
        """
        batch = SettlementBatch.objects.create(
            organisation=organisation, provider=provider, reference=reference, source=source,
        )
        imported, skipped = 0, 0
        total = ZERO
        for row in rows:
            try:
                with transaction.atomic():
                    SettlementLine.objects.create(
                        organisation=organisation, batch=batch, **row,
                    )
            except IntegrityError:
                skipped += 1
                continue
            imported += 1
            total += row["amount"]

        batch.line_count = imported
        batch.total_amount = total
        if skipped:
            batch.note = f"{skipped} payout(s) already imported and skipped."
        batch.save(update_fields=["line_count", "total_amount", "note", "updated_at"])
        return batch

    # ── Matching ────────────────────────────────────────────────────────────
    @staticmethod
    @transaction.atomic
    def match_batch(batch: SettlementBatch, tolerance_days=DATE_TOLERANCE_DAYS) -> dict:
        """Tie each payout to the card sale it settles.

        Exact amount only. A payout of ₦12,400 is never matched to a ₦12,000
        sale, because a near-miss is the one case where being wrong is
        indistinguishable from being right.
        """
        from apps.sales.models import SalePayment

        org = batch.organisation
        lines = list(batch.lines.filter(status=SettlementLine.Status.UNMATCHED))
        if not lines:
            return {"matched": 0, "unmatched": 0}

        stamps = [line.paid_at for line in lines if line.paid_at]
        window_start = (min(stamps) - timedelta(days=tolerance_days)) if stamps else None
        window_end = (max(stamps) + timedelta(days=tolerance_days)) if stamps else None

        # Card tenders only — cash never arrives through a terminal, and a
        # transfer settles straight to the bank.
        candidates = SalePayment.objects.filter(
            organisation=org, method__in=["pos", "card"],
        ).exclude(settlement_lines__isnull=False).select_related("invoice")
        if window_start and window_end:
            candidates = candidates.filter(received_at__gte=window_start, received_at__lte=window_end)
        pool = list(candidates)

        taken: set = set()
        matched = 0
        for line in lines:
            best = SettlementService._best_match(line, pool, taken, tolerance_days)
            if best is None:
                continue
            taken.add(best.id)
            line.payment = best
            line.status = SettlementLine.Status.MATCHED
            line.matched_automatically = True
            line.save(update_fields=["payment", "status", "matched_automatically", "updated_at"])
            matched += 1

        return {"matched": matched, "unmatched": len(lines) - matched}

    @staticmethod
    def _best_match(line, pool, taken, tolerance_days):
        """Exact amount, nearest in time, reference hit wins a tie."""
        amount = Decimal(str(line.amount))
        options = [
            p for p in pool
            if p.id not in taken and Decimal(str(p.amount)) == amount
        ]
        if not options:
            return None

        if line.paid_at:
            limit = timedelta(days=tolerance_days)
            options = [p for p in options if abs(p.received_at - line.paid_at) <= limit]
            if not options:
                return None

        needle = f"{line.provider_reference} {line.narration}".lower()

        def score(payment):
            reference_hit = bool(
                payment.reference and payment.reference.lower() in needle
            )
            gap = abs((payment.received_at - line.paid_at).total_seconds()) if line.paid_at else 0
            # Lower is better: a reference hit beats everything, then closeness.
            return (0 if reference_hit else 1, gap)

        options.sort(key=score)

        # Two identical amounts at nearly the same moment are genuinely
        # ambiguous — refuse rather than pick one at random.
        if len(options) > 1 and score(options[0])[0] == score(options[1])[0]:
            first, second = score(options[0])[1], score(options[1])[1]
            if abs(first - second) < 1:
                return None
        return options[0]

    # ── Review ──────────────────────────────────────────────────────────────
    @staticmethod
    def assign(line: SettlementLine, payment, note="") -> SettlementLine:
        """A human ties a payout to a sale the matcher would not guess."""
        if payment.organisation_id != line.organisation_id:
            raise SettlementError("That payment belongs to another business.")
        if SettlementLine.objects.filter(payment=payment).exclude(pk=line.pk).exists():
            raise SettlementError("That payment is already settled by another payout.")
        line.payment = payment
        line.status = SettlementLine.Status.MATCHED
        line.matched_automatically = False
        line.review_note = note
        line.save(update_fields=[
            "payment", "status", "matched_automatically", "review_note", "updated_at",
        ])
        return line

    @staticmethod
    def record_as_other_income(line: SettlementLine, user=None, note="") -> SettlementLine:
        """Money with no sale behind it — rung up on the terminal directly.

        Posts DR Bank / CR Other Income so the bank still reconciles, rather
        than leaving an unexplained balance.
        """
        from apps.accounting.models import AccountType
        from apps.accounting.services import AccountingService, AccountMappingService

        if line.status == SettlementLine.Status.MATCHED:
            raise SettlementError("That payout is already matched to a sale.")

        org = line.organisation
        amount = Decimal(str(line.amount))
        try:
            bank = AccountMappingService.resolve(org, "bank_account")
            other_income = AccountingService._get_or_create_account(
                org, "4100", "Other Income", AccountType.REVENUE,
            )
            AccountingService.post_journal_entry(
                org,
                description=f"Terminal payout {line.provider_reference}",
                entry_date=(line.paid_at or timezone.now()).date(),
                lines=[(bank, amount, ZERO), (other_income, ZERO, amount)],
                created_by=user,
                ref="SETTLE",
                source_type="settlement_other_income",
                source_ref=str(line.id),
            )
        except Exception as exc:
            raise SettlementError(f"Could not post that to the ledger: {exc}")

        line.status = SettlementLine.Status.OTHER_INCOME
        line.review_note = note
        line.save(update_fields=["status", "review_note", "updated_at"])
        return line

    @staticmethod
    def ignore(line: SettlementLine, note="") -> SettlementLine:
        if line.status == SettlementLine.Status.MATCHED:
            raise SettlementError("Unmatch it before ignoring it.")
        line.status = SettlementLine.Status.IGNORED
        line.review_note = note
        line.save(update_fields=["status", "review_note", "updated_at"])
        return line

    @staticmethod
    def unmatch(line: SettlementLine) -> SettlementLine:
        line.payment = None
        line.status = SettlementLine.Status.UNMATCHED
        line.matched_automatically = False
        line.save(update_fields=["payment", "status", "matched_automatically", "updated_at"])
        return line

    @staticmethod
    def summary(organisation) -> dict:
        """What still needs a human."""
        from django.db.models import Count, Sum
        rows = (
            SettlementLine.objects.filter(organisation=organisation)
            .values("status").annotate(n=Count("id"), total=Sum("amount"))
        )
        by_status = {r["status"]: {"count": r["n"], "total": r["total"] or ZERO} for r in rows}
        return {
            "needs_review": by_status.get(SettlementLine.Status.UNMATCHED, {}).get("count", 0),
            "needs_review_total": by_status.get(SettlementLine.Status.UNMATCHED, {}).get("total", ZERO),
            "matched": by_status.get(SettlementLine.Status.MATCHED, {}).get("count", 0),
            "by_status": by_status,
        }

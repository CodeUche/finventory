"""
Repairs organisations whose "VAT Input" mapping points at Prepaid Expenses (1300)
instead of VAT Receivable / Input VAT (1400).

    # Read-only report for every organisation (this is the default)
    python manage.py repair_vat_input_account

    # One organisation only
    python manage.py repair_vat_input_account --org <uuid>

    # Make the changes. A licensed accountant must approve the report first.
    python manage.py repair_vat_input_account --org <uuid> --apply

What it does, per organisation whose VAT Input mapping is on Prepaid Expenses
(or code 1300), or that still has Input VAT sitting in 1300:
  1. Repoints the vat_input_account mapping to code 1400 (creating 1400 when
     it is missing).
  2. Adds up the VAT that goods-received, PO-converted-to-bill and purchase
     return entries left in 1300 and posts ONE balanced reclass journal
     (DR 1400 / CR 1300; the other way round when returns exceed bills),
     source_type "vat_input_reclass". Idempotent: amounts already reclassed
     are subtracted, so running twice posts nothing the second time.
  3. Never unlocks a period. The reclass is dated today; when today's month is
     locked, the organisation is reported as blocked and nothing is changed.
"""

from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

CENT = Decimal("0.01")
SOURCE_TYPES = ("po_receipt", "po_convert_to_bill", "purchase_return")
RECLASS_SOURCE_TYPE = "vat_input_reclass"
SYSTEM_EMAIL = "data-repair@system.audity.africa"


def _d(v):
    return Decimal(str(v or 0))


class Command(BaseCommand):
    help = "Move Input VAT from Prepaid Expenses (1300) to VAT Receivable (1400). Dry-run unless --apply."

    def add_arguments(self, parser):
        parser.add_argument("--org", help="Only this organisation (uuid).")
        parser.add_argument("--apply", action="store_true",
                            help="Make the changes. Without this nothing is written.")

    def handle(self, *args, **opts):
        from apps.core.tenant_context import organisation_context
        from apps.tenancy.models import Organisation

        orgs = Organisation.objects.all()
        if opts["org"]:
            orgs = orgs.filter(id=opts["org"])
            if not orgs.exists():
                raise CommandError("No such organisation.")
        orgs = list(orgs)

        apply_ = opts["apply"]
        self.stdout.write("APPLYING CHANGES." if apply_
                          else "DRY RUN: nothing will be written. Add --apply to make the changes.")
        counts = {"ok": 0, "repair": 0, "blocked": 0}
        for org in orgs:
            with organisation_context(org.id):
                result = self.repair_org(org, apply_)
            counts[result["status"]] += 1
        self.stdout.write(
            f"Done. Organisations checked: {len(orgs)}; fine: {counts['ok']}; "
            f"{'repaired' if apply_ else 'need repair'}: {counts['repair']}; blocked: {counts['blocked']}.")

    def repair_org(self, org, apply_):
        """Check (and with apply_=True fix) one organisation. Returns {"status", "amount"}."""
        from apps.accounting.exceptions import PeriodLockedError
        from apps.accounting.models import Account, AccountMapping, AccountType, JournalLine
        from apps.accounting.services import AccountingService

        mapping = AccountMapping.objects.filter(organisation=org).select_related("vat_input_account").first()
        mapped = mapping.vat_input_account if mapping else None
        mapping_is_bad = bool(mapped) and (
            mapped.code == "1300" or "prepaid expenses" in (mapped.name or "").lower())

        acct_1300 = mapped if mapping_is_bad else Account.objects.filter(
            organisation=org, code="1300", is_deleted=False).first()
        entries, to_move = [], Decimal("0")
        if acct_1300 is not None:
            base = JournalLine.objects.filter(
                journal_entry__organisation=org, journal_entry__status="posted", account=acct_1300)
            lines = base.filter(journal_entry__source_type__in=SOURCE_TYPES).select_related("journal_entry")
            for ln in lines.order_by("journal_entry__entry_date", "journal_entry_id"):
                amt = _d(ln.debit) - _d(ln.credit)
                if amt:
                    entries.append((ln.journal_entry, amt))
                    to_move += amt
            # Amounts already moved by an earlier run (credits on 1300).
            for ln in base.filter(journal_entry__source_type=RECLASS_SOURCE_TYPE):
                to_move -= _d(ln.credit) - _d(ln.debit)
        to_move = to_move.quantize(CENT)

        if not mapping_is_bad and to_move == 0:
            self.stdout.write(f"[{org.name}] fine: VAT Input mapping is not on Prepaid Expenses and nothing to move.")
            return {"status": "ok", "amount": Decimal("0")}

        acct_1400 = Account.objects.filter(organisation=org, code="1400", is_deleted=False).first()
        self.stdout.write(f"[{org.name}] VAT Input mapping: "
                          f"{(mapped.code + ' ' + mapped.name) if mapped else 'not set'}")
        self.stdout.write("    Target account: 1400 VAT Receivable (Input VAT)"
                          + ("" if acct_1400 else " (does not exist, will be created)"))
        for je, amt in entries:
            self.stdout.write(f"    {je.entry_date}  {je.source_type:<20} {je.reference:<14} {amt:>14,.2f}")
        by_month = {}
        for je, amt in entries:
            key = je.entry_date.strftime("%Y-%m")
            by_month[key] = by_month.get(key, Decimal("0")) + amt
        self.stdout.write("    By month of the original entries:")
        for key in sorted(by_month):
            self.stdout.write(f"        {key}  {by_month[key]:>14,.2f}")
        self.stdout.write(f"    Input VAT to reclass from 1300 to 1400: {to_move:,.2f}")
        self.stdout.write("    Note: only VAT posted by goods-received, PO-converted-to-bill and purchase-return "
                          "entries is moved. Any journal keyed by hand into 1300 is left alone for the accountant.")
        months_text = ", ".join(f"{k} {by_month[k]:,.2f}" for k in sorted(by_month)) or "none"
        if len(months_text) > 280:
            months_text = months_text[:277] + "..."

        today = timezone.now().date()
        if to_move != 0:
            try:
                # Also in the dry run, so the accountant learns about a lock up front.
                AccountingService.assert_period_open(
                    org, today, None, ref="VAT-RECLASS", source=RECLASS_SOURCE_TYPE)
            except PeriodLockedError as exc:
                self.stdout.write(self.style.WARNING(f"    BLOCKED: {exc} Nothing changed for this organisation."))
                return {"status": "blocked", "amount": to_move}

        if not apply_:
            return {"status": "repair", "amount": to_move}

        system_user = None
        with transaction.atomic():
            if acct_1400 is None:
                acct_1400 = AccountingService._get_or_create_account(
                    org, "1400", "VAT Receivable (Input VAT)", AccountType.ASSET)
            if mapping_is_bad:
                mapping.vat_input_account = acct_1400
                mapping.save()
            if to_move != 0:
                system_user = self._system_user()
                zero = Decimal("0")
                amt = abs(to_move)
                lines = ([(acct_1400, amt, zero), (acct_1300, zero, amt)] if to_move > 0
                         else [(acct_1300, amt, zero), (acct_1400, zero, amt)])
                AccountingService.post_journal_entry(
                    org,
                    "Reclass Input VAT from Prepaid Expenses (1300) to VAT Receivable (1400) "
                    f"- VAT Input mapping repair. Original months: {months_text}",
                    today, lines, system_user,
                    ref="VAT-RECLASS",
                    source_type=RECLASS_SOURCE_TYPE,
                    source_ref=f"{org.id}:{today.isoformat()}",
                )
            try:
                from apps.core.models import AuditLog
                AuditLog.log(
                    action=AuditLog.UPDATE, user=system_user, organisation=org,
                    model_name="AccountMapping", object_id=str(mapping.id) if mapping else "",
                    object_repr="vat_input_account repair",
                    changes={"event": "vat_input_account_repaired", "reclass_amount": str(to_move),
                             "from": mapped.code if mapped else None, "to": "1400"},
                )
            except Exception:
                pass
        self.stdout.write(self.style.SUCCESS(f"    REPAIRED: mapping now on 1400; reclassed {to_move:,.2f}."))
        return {"status": "repair", "amount": to_move}

    def _system_user(self):
        from apps.authentication.models import User
        user = User.objects.filter(email=SYSTEM_EMAIL).first()
        if user is None:
            user = User(email=SYSTEM_EMAIL, first_name="Data", last_name="Repair", is_verified=True)
            user.set_unusable_password()
            user.save()
        return user

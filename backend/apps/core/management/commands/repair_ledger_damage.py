"""
Corrects ledger damage found by `find_ledger_damage`, one company at a time,
only with the owner's approval of each correction.

    # 1. Read-only: write the proposed corrections to a file
    python manage.py repair_ledger_damage plan --org <uuid> --out plan.json

    # 2. The owner reads the file and sets "approved": true on what they accept
    #    (and may change "method" on a payment to "bank_transfer", etc.)

    # 3. Rehearse: posts inside a transaction, shows before/after balances, rolls back
    python manage.py repair_ledger_damage apply --plan plan.json --approved-by owner@x.com

    # 4. For real, once the rehearsal (ideally on a copy of production) looks right
    python manage.py repair_ledger_damage apply --plan plan.json --approved-by owner@x.com --commit

Rules (agreed with the accountant):
  * Each correction posts on its original date when that month is open; when the
    month is locked it posts today and the description names the original date.
    A locked month is never unlocked.
  * Idempotent: journal source_type "data_repair", source_ref "<bug id>:<record id>".
    Running twice posts nothing the second time.
  * Posted by a named, login-less system user, and the whole batch is written to
    the audit trail with the approver and a batch id.
  * Only corrections the owner approved are posted. Anything that needs a human
    decision (VAT shown as owed, over-billed invoices, quotes, till variances)
    is listed under "manual" and never posted by this command.
"""

import json
import uuid
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

CENT = Decimal("0.01")
SYSTEM_EMAIL = "data-repair@system.audity.africa"
SOURCE_TYPE = "data_repair"
MANUAL_KINDS = ("overpaid_payments", "vat_left_unpaid", "vat_charged_twice", "quote_billed_above_quote",
                "till_missed_takings", "depreciation_fractions")


def _d(v):
    return Decimal(str(v or 0))


class Command(BaseCommand):
    help = "Plan and apply owner-approved corrections for ledger damage (see module docstring)."

    def add_arguments(self, parser):
        sub = parser.add_subparsers(dest="mode", required=True)
        p = sub.add_parser("plan", help="Read-only: write proposed corrections to a file.")
        p.add_argument("--org", required=True)
        p.add_argument("--out", required=True)
        a = sub.add_parser("apply", help="Post the corrections the owner approved.")
        a.add_argument("--plan", required=True)
        a.add_argument("--approved-by", required=True, help="Email of the organisation's owner.")
        a.add_argument("--commit", action="store_true", help="Without this, everything is rolled back.")

    def handle(self, *args, **opts):
        if opts["mode"] == "plan":
            self._plan(opts["org"], opts["out"])
        else:
            self._apply(opts["plan"], opts["approved_by"], opts["commit"])

    # ── plan ─────────────────────────────────────────────────────────────────
    def _plan(self, org_id, out_path):
        from apps.core.management.commands.find_ledger_damage import Command as Finder
        from apps.core.tenant_context import organisation_context
        from apps.tenancy.models import Organisation

        org = Organisation.objects.filter(id=org_id).first()
        if org is None:
            raise CommandError("No such organisation.")
        with transaction.atomic():
            with organisation_context(org.id):
                findings = Finder()._scan(org)
                corrections = self._credit_payment_corrections(org, findings["missed_credit_payments"])
                corrections += self._po_receipt_corrections(org, findings["missed_po_receipts"])
            transaction.set_rollback(True)
        manual = {k: findings[k]["items"] for k in MANUAL_KINDS if findings[k]["items"]}
        plan = {
            "organisation": str(org.id), "name": org.name,
            "generated": timezone.now().isoformat(),
            "corrections": corrections, "manual": manual,
        }
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(plan, fh, indent=1, default=str)
        self.stdout.write(
            f"{org.name}: {len(corrections)} correction(s) proposed, "
            f"{sum(len(v) for v in manual.values())} item(s) need a human decision. Plan: {out_path}\n"
            "Nothing was changed. The owner must set \"approved\": true on each correction to accept it."
        )

    def _credit_payment_corrections(self, org, finding):
        out = []
        for item in finding["items"]:
            out.append({
                "id": f"BUG-001:{item['payment']}", "bug": "BUG-001", "record": item["payment"],
                "kind": "credit_payment", "customer": item["customer"],
                "original_date": item["date"], "amount": item["amount"], "method": "cash",
                "what": f"Customer payment of {item['amount']} from {item['customer']} on {item['date']} "
                        "was recorded but never reached the ledger: post DR Cash/Bank, CR Accounts Receivable. "
                        "The payment method was not stored; Cash is assumed (change \"method\" if it was a transfer).",
                "approved": False,
            })
        return out

    def _po_receipt_corrections(self, org, finding):
        from apps.bills.models import Bill

        out = []
        for item in finding["items"]:
            bill = Bill.objects.filter(organisation=org, bill_number=item["bill"]).first()
            if bill is None:
                continue
            missing = _d(item["missing"])
            total = _d(bill.total_amount)
            vat = (_d(bill.tax_amount) * missing / total).quantize(CENT) if total else Decimal("0")
            out.append({
                "id": f"BUG-004:{bill.id}", "bug": "BUG-004", "record": str(bill.id),
                "kind": "po_receipt", "bill": item["bill"], "purchase_order": item["purchase_order"],
                "original_date": str(bill.issue_date) if getattr(bill, "issue_date", None) else timezone.now().date().isoformat(),
                "amount": str(missing), "vat": str(vat),
                "what": f"Bill {item['bill']} grew by later part-deliveries worth {missing} that never reached the "
                        "ledger: post DR Inventory and Input VAT, CR Accounts Payable.",
                "approved": False,
            })
        return out

    # ── apply ────────────────────────────────────────────────────────────────
    def _apply(self, plan_path, approver_email, commit):
        from apps.authentication.models import User
        from apps.core.models import AuditLog
        from apps.core.tenant_context import organisation_context
        from apps.tenancy.models import Membership, Organisation

        with open(plan_path, encoding="utf-8") as fh:
            plan = json.load(fh)
        org = Organisation.objects.filter(id=plan["organisation"]).first()
        if org is None:
            raise CommandError("The plan's organisation no longer exists.")
        approver = User.objects.filter(email__iexact=approver_email).first()
        if approver is None or not Membership.objects.filter(
            user=approver, organisation=org, role=Membership.Role.OWNER, is_active=True,
        ).exists():
            raise CommandError(f"{approver_email} is not an active owner of {org.name}; refusing.")

        approved = [c for c in plan["corrections"] if c.get("approved") is True]
        if not approved:
            self.stdout.write("No correction is marked approved. Nothing to do.")
            return

        batch = uuid.uuid4().hex[:12]
        system_user = self._system_user()
        results = {"posted": 0, "already_done": 0, "skipped": 0}
        with transaction.atomic():
            with organisation_context(org.id):
                before = self._balances(org)
                for c in approved:
                    results[self._post(org, c, system_user, batch)] += 1
                after = self._balances(org)
                if commit:
                    AuditLog.log(
                        action=AuditLog.CREATE, user=system_user, organisation=org,
                        model_name="DataRepairBatch", object_id=batch, object_repr=f"Data repair {batch}",
                        changes={"approved_by": approver.email, "plan_generated": plan.get("generated"),
                                 "results": results, "corrections": [c["id"] for c in approved],
                                 "before": before, "after": after},
                    )
            if not commit:
                transaction.set_rollback(True)

        self.stdout.write(f"Batch {batch} for {org.name}: {results}")
        for name in before:
            self.stdout.write(f"  {name:28} {before[name]:>16} -> {after[name]:>16}")
        self.stdout.write("COMMITTED." if commit else "REHEARSAL ONLY: everything was rolled back. Add --commit to post for real.")

    def _system_user(self):
        from apps.authentication.models import User
        user = User.objects.filter(email=SYSTEM_EMAIL).first()
        if user is None:
            user = User(email=SYSTEM_EMAIL, first_name="Data", last_name="Repair", is_verified=True)
            user.set_unusable_password()
            user.save()
        return user

    def _balances(self, org):
        """Ledger totals for the accounts a repair touches (debit minus credit)."""
        from django.db.models import Sum

        from apps.accounting.models import JournalLine
        out = {}
        for label, prefix in (("Cash and bank", "10"), ("Accounts Receivable", "1100"),
                              ("Inventory", "1200"), ("Input VAT", "1400"), ("Accounts Payable", "2001")):
            row = JournalLine.objects.filter(
                journal_entry__organisation=org, journal_entry__status="posted", account__code__startswith=prefix,
            ).aggregate(d=Sum("debit"), c=Sum("credit"))
            out[label] = str((_d(row["d"]) - _d(row["c"])).quantize(CENT))
        return out

    def _post(self, org, c, user, batch):
        """Post one approved correction. Returns 'posted', 'already_done' or 'skipped'."""
        from datetime import date

        from apps.accounting.models import FinancialPeriod, JournalEntry
        from apps.accounting.services import AccountingService, AccountMappingService

        ref = c["id"]
        if JournalEntry.objects.filter(organisation=org, source_type=SOURCE_TYPE, source_ref=ref).exists():
            return "already_done"
        original = date.fromisoformat(str(c["original_date"])[:10])
        locked = FinancialPeriod.objects.filter(
            organisation=org, year=original.year, month=original.month, is_locked=True).exists()
        entry_date = timezone.now().date() if locked else original
        note = f" [data repair {batch}; original date {original.isoformat()}]" if locked else f" [data repair {batch}]"
        amount, zero = _d(c["amount"]), Decimal("0")

        if c["kind"] == "credit_payment":
            from apps.credits.models import CreditTransaction
            txn = CreditTransaction.objects.select_related("customer").filter(organisation=org, id=c["record"]).first()
            if txn is None:
                return "skipped"
            asset = AccountingService.tender_asset_account(org, c.get("method", "cash"))
            ar = AccountingService._resolve_party_account(
                org, txn.customer, "receivable_account", "accounts_receivable", "1100")
            lines = [(asset, amount, zero), (ar, zero, amount)]
            desc = f"Correction: payment from {c['customer']}{note}"
        elif c["kind"] == "po_receipt":
            from apps.bills.models import Bill
            bill = Bill.objects.select_related("supplier").filter(organisation=org, id=c["record"]).first()
            if bill is None:
                return "skipped"
            vat = _d(c.get("vat"))
            inv = AccountMappingService.resolve(org, "inventory_account")
            ap = AccountingService._resolve_party_account(
                org, bill.supplier, "payable_account", "accounts_payable", "2001")
            lines = [(inv, amount - vat, zero), (ap, zero, amount)]
            if vat > zero:
                lines.append((AccountMappingService.resolve(org, "vat_input_account"), vat, zero))
            desc = f"Correction: goods received on bill {c['bill']}{note}"
        else:
            return "skipped"

        entry = AccountingService.post_journal_entry(
            org, desc, entry_date, lines, user, ref=f"REPAIR-{batch}",
            source_type=SOURCE_TYPE, source_ref=ref,
        )
        return "posted" if entry is not None else "skipped"

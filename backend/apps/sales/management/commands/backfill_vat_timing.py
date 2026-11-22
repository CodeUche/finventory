"""
Stamps older proformas that already took a deposit with vat_timing = "invoice".

    python manage.py backfill_vat_timing            # report only (default)
    python manage.py backfill_vat_timing --org <uuid>
    python manage.py backfill_vat_timing --apply    # write the stamp

An unstamped invoice follows the rule in force, which is now always "invoice"
(VAT is due at the earliest of invoice, receipt or delivery). This only makes the
stamp explicit on proformas whose deposits (ledger entries "sale_deposit") booked
VAT on receipt, so a later change can never reinterpret them. It changes one
column on those invoices and nothing in the ledger. Safe to run twice.
"""
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Stamp vat_timing='invoice' on unstamped proformas that already have a deposit entry."

    def add_arguments(self, parser):
        parser.add_argument("--org", help="Only this organisation (uuid).")
        parser.add_argument("--apply", action="store_true", help="Write the stamp. Without this nothing changes.")

    def handle(self, *args, **opts):
        from apps.accounting.models import JournalEntry
        from apps.core.tenant_context import organisation_context
        from apps.sales.models import Invoice, SalePayment
        from apps.tenancy.models import Organisation

        orgs = Organisation.objects.all()
        if opts["org"]:
            orgs = orgs.filter(id=opts["org"])
            if not orgs.exists():
                raise CommandError("No such organisation.")
        total = 0
        for org in list(orgs):
            with organisation_context(org.id):
                refs = list(JournalEntry.objects.filter(
                    organisation=org, source_type="sale_deposit").values_list("source_ref", flat=True))
                if not refs:
                    continue
                inv_ids = set(SalePayment.objects.filter(
                    organisation=org, id__in=refs).values_list("invoice_id", flat=True))
                qs = Invoice.objects.filter(organisation=org, id__in=inv_ids, vat_timing__isnull=True)
                n = qs.count()
                if n:
                    self.stdout.write(f"{org.name}: {n} invoice(s) to stamp")
                    total += n
                    if opts["apply"]:
                        qs.update(vat_timing="invoice")
        verb = "Stamped" if opts["apply"] else "Would stamp (run with --apply)"
        self.stdout.write(f"{verb}: {total} invoice(s).")

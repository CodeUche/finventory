"""
Management command: reseed chart of accounts for orgs that are missing it.

Usage:
    # Fix all orgs missing a COA
    python manage.py reseed_coa

    # Fix one specific org
    python manage.py reseed_coa --org <uuid>

    # Dry run — just report which orgs are affected
    python manage.py reseed_coa --dry-run
"""

from django.core.management.base import BaseCommand

from apps.accounting.models import Account
from apps.accounting.services import AccountingService
from apps.tenancy.models import Organisation


class Command(BaseCommand):
    help = "Reseed chart of accounts for organisations that are missing it."

    def add_arguments(self, parser):
        parser.add_argument(
            "--org",
            type=str,
            default=None,
            help="UUID of a specific organisation to fix (default: all missing).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report affected orgs without making changes.",
        )

    def handle(self, *args, **options):
        org_id = options["org"]
        dry_run = options["dry_run"]

        if org_id:
            try:
                orgs = Organisation.objects.filter(id=org_id, is_deleted=False)
                if not orgs.exists():
                    self.stderr.write(self.style.ERROR(f"No org found with id={org_id}"))
                    return
            except Exception as exc:
                self.stderr.write(self.style.ERROR(f"Invalid org id: {exc}"))
                return
        else:
            # Find orgs with no accounts at all
            orgs_with_coa = Account.objects.values_list("organisation_id", flat=True).distinct()
            orgs = Organisation.objects.filter(is_deleted=False).exclude(id__in=orgs_with_coa)

        count = orgs.count()
        if count == 0:
            self.stdout.write(self.style.SUCCESS("All organisations have a chart of accounts. Nothing to do."))
            return

        self.stdout.write(f"Found {count} organisation(s) missing a chart of accounts.")

        if dry_run:
            for org in orgs:
                self.stdout.write(f"  [DRY RUN] Would reseed: {org.name} ({org.id})")
            return

        fixed = 0
        failed = 0
        for org in orgs:
            try:
                before = Account.objects.filter(organisation=org).count()
                AccountingService.seed_chart_of_accounts(org)
                after = Account.objects.filter(organisation=org).count()
                added = after - before
                self.stdout.write(
                    self.style.SUCCESS(f"  Reseeded: {org.name} ({org.id}) — {added} accounts added")
                )
                fixed += 1
            except Exception as exc:
                self.stderr.write(self.style.ERROR(f"  FAILED: {org.name} ({org.id}) — {exc}"))
                failed += 1

        self.stdout.write(f"\nDone. Fixed: {fixed}  Failed: {failed}")

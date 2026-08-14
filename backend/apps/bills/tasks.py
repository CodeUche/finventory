"""Celery tasks for the bills app."""
import logging
from datetime import date

from celery import shared_task
from django.utils import timezone

from apps.core.tenant_context import for_each_organisation

logger = logging.getLogger(__name__)


@shared_task(name="bills.create_year_archive_folders", bind=True, max_retries=3)
def create_bill_year_archive_folders(self):
    """
    Runs on Jan 1 each year (00:35).
    Creates a BillFolder named "<YYYY> Archive" for every organisation
    and moves all unarchived bills from the just-ended year into it.
    Safe to re-run: uses get_or_create, never creates duplicate folders.
    """
    from .models import Bill, BillFolder

    prev_year = timezone.now().year - 1
    folder_name = f"{prev_year} Archive"
    folder_date = date(prev_year, 12, 31)

    # Runs per organisation inside that tenant's RLS context. Without it the
    # BillFolder INSERT is refused by the policy's WITH CHECK clause and the
    # Bill update matches zero rows (NEW-7).
    stats = {"folders_created": 0, "bills_moved": 0}

    def _archive(org):
        folder, created = BillFolder.objects.get_or_create(
            organisation=org,
            name=folder_name,
            defaults={
                'folder_date': folder_date,
                'description': f'Automatically archived bills from {prev_year}',
            },
        )
        if created:
            stats["folders_created"] += 1

        count = Bill.objects.filter(
            organisation=org,
            issue_date__year=prev_year,
            folder__isnull=True,
        ).update(folder=folder)
        stats["bills_moved"] += count
        return count

    for_each_organisation(_archive, task_name="bills.create_year_archive_folders")

    logger.info(
        "create_bill_year_archive_folders: %d folders created, %d bills moved for year %d",
        stats["folders_created"], stats["bills_moved"], prev_year,
    )
    return {"year": prev_year, **stats}

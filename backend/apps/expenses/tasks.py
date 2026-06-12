"""
Celery tasks for the expenses app.

Registered in CELERY_BEAT_SCHEDULE (config/settings/base.py).
"""

import logging
from datetime import date

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name="expenses.archive_to_monthly_folders", bind=True, max_retries=2)
def archive_to_monthly_folders(self):
    """
    Runs on the 1st of each month at 00:20.

    For every organisation, finds all Expense / Income records from the
    PREVIOUS calendar month that are not yet assigned to any folder (group),
    creates (or gets) a folder named "Month YYYY" (e.g. "June 2026"), and
    assigns those records to it.

    This keeps the Expenses page organised without requiring manual folder
    management from users.
    """
    from django.db import transaction
    from apps.tenancy.models import Organisation
    from apps.expenses.models import Expense, ExpenseGroup

    today = date.today()
    # Previous month
    if today.month == 1:
        prev_year, prev_month = today.year - 1, 12
    else:
        prev_year, prev_month = today.year, today.month - 1

    month_name = date(prev_year, prev_month, 1).strftime("%B %Y")  # e.g. "June 2026"

    orgs = Organisation.objects.filter(is_active=True)
    total_assigned = 0
    total_orgs = 0

    for org in orgs:
        unfoldered = Expense.objects.filter(
            organisation=org,
            group__isnull=True,
            expense_date__year=prev_year,
            expense_date__month=prev_month,
        )
        count = unfoldered.count()
        if count == 0:
            continue

        try:
            with transaction.atomic():
                folder, _ = ExpenseGroup.objects.get_or_create(
                    organisation=org,
                    name=month_name,
                    defaults={
                        "description": f"Auto-archived expenses and income for {month_name}",
                        "group_date": date(prev_year, prev_month, 1),
                    },
                )
                unfoldered.update(group=folder)
            total_assigned += count
            total_orgs += 1
            logger.info(
                "archive_to_monthly_folders: org=%s assigned %d records → '%s'",
                org.id, count, month_name,
            )
        except Exception as exc:
            logger.error(
                "archive_to_monthly_folders: org=%s failed: %s", org.id, exc, exc_info=True
            )

    logger.info(
        "archive_to_monthly_folders complete: %d records across %d orgs → '%s'",
        total_assigned, total_orgs, month_name,
    )
    return {"assigned": total_assigned, "orgs": total_orgs, "folder_name": month_name}

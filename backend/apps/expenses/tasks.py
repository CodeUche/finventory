"""
Celery tasks for the expenses app.

Registered in CELERY_BEAT_SCHEDULE (config/settings/base.py).
"""

import logging
from datetime import date

from celery import shared_task

from apps.core.tenant_context import for_each_organisation

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
    from apps.expenses.models import Expense, ExpenseGroup

    today = date.today()
    # Previous month
    if today.month == 1:
        prev_year, prev_month = today.year - 1, 12
    else:
        prev_year, prev_month = today.year, today.month - 1

    month_name = date(prev_year, prev_month, 1).strftime("%B %Y")  # e.g. "June 2026"

    # Per-organisation RLS context: Celery does not run RLSMiddleware, so
    # without this the Expense query returns zero rows and the ExpenseGroup
    # INSERT is refused by the policy's WITH CHECK (NEW-7).
    stats = {"orgs": 0}

    def _archive(org):
        unfoldered = Expense.objects.filter(
            organisation=org,
            group__isnull=True,
            expense_date__year=prev_year,
            expense_date__month=prev_month,
        )
        count = unfoldered.count()
        if count == 0:
            return 0

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
        stats["orgs"] += 1
        logger.info(
            "archive_to_monthly_folders: org=%s assigned %d records → '%s'",
            org.id, count, month_name,
        )
        return count

    result = for_each_organisation(
        _archive, task_name="expenses.archive_to_monthly_folders",
    )

    logger.info(
        "archive_to_monthly_folders complete: %d records across %d orgs → '%s'",
        result["processed"], stats["orgs"], month_name,
    )
    return {"assigned": result["processed"], "orgs": stats["orgs"], "folder_name": month_name}

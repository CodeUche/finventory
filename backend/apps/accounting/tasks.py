"""
Celery tasks for the accounting app.

Registered in CELERY_BEAT_SCHEDULE (config/settings/base.py).
"""

import logging
from datetime import date

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name="accounting.run_monthly_depreciation", bind=True, max_retries=3)
def run_monthly_depreciation(self):
    """
    Run straight-line / reducing-balance depreciation for all active orgs.

    Should be scheduled to run on the 1st of each month for the previous month.
    """
    from apps.tenancy.models import Organisation
    from .services import AccountingService

    today = date.today()
    # Target: previous month
    if today.month == 1:
        year, month = today.year - 1, 12
    else:
        year, month = today.year, today.month - 1

    orgs = Organisation.objects.filter(is_active=True)
    total_entries = 0
    for org in orgs:
        try:
            entries = AccountingService.run_depreciation(org, year, month)
            total_entries += len(entries)
        except Exception as exc:
            logger.warning("Depreciation failed for org %s: %s", org.id, exc)

    logger.info("run_monthly_depreciation: %d entries created for %d-%02d", total_entries, year, month)
    return {"entries": total_entries, "year": year, "month": month}

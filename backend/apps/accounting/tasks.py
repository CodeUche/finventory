"""
Celery tasks for the accounting app.

Registered in CELERY_BEAT_SCHEDULE (config/settings/base.py).
"""

import logging
from datetime import date

from celery import shared_task

from apps.core.tenant_context import for_each_organisation

logger = logging.getLogger(__name__)


@shared_task(name="accounting.run_monthly_depreciation", bind=True, max_retries=3)
def run_monthly_depreciation(self):
    """
    Run straight-line / reducing-balance depreciation for all active orgs.

    Should be scheduled to run on the 1st of each month for the previous month.
    """
    from .services import AccountingService

    today = date.today()
    # Target: previous month
    if today.month == 1:
        year, month = today.year - 1, 12
    else:
        year, month = today.year, today.month - 1

    # This task already iterated organisations, but ran every query under the
    # SENTINEL org id because Celery does not run RLSMiddleware — so
    # run_depreciation() saw zero fixed assets and posted nothing (NEW-7).
    def _depreciate(org):
        return len(AccountingService.run_depreciation(org, year, month))

    result = for_each_organisation(
        _depreciate, task_name="accounting.run_monthly_depreciation",
    )
    logger.info(
        "run_monthly_depreciation: %d entries created for %d-%02d",
        result["processed"], year, month,
    )
    return {"entries": result["processed"], "year": year, "month": month}

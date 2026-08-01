"""Scheduled HR jobs."""

import logging
from datetime import date

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name="payroll.accrue_monthly_leave")
def accrue_monthly_leave():
    """
    Add one month's entitlement to every monthly-accrual leave balance.

    Runs on the 1st of each month and accrues for the month just completed, so
    an employee's balance reflects service already given rather than service
    they are about to give.
    """
    from apps.tenancy.models import Organisation

    from .services import LeaveService

    today = date.today()
    if today.month == 1:
        year, month = today.year - 1, 12
    else:
        year, month = today.year, today.month - 1

    total = 0
    for org in Organisation.objects.filter(is_active=True):
        try:
            total += LeaveService.accrue_month(org, year, month)
        except Exception as exc:
            logger.exception("Leave accrual failed for org %s: %s", org.id, exc)
    logger.info("Leave accrual %s-%02d: %d balances updated", year, month, total)
    return total


@shared_task(name="payroll.flag_overdue_remittances")
def flag_overdue_remittances():
    """
    Nothing to write — ``is_overdue`` is derived from the due date — but this
    surfaces a log line and a count that the alerting stack can pick up, and it
    is the hook a future notification job would hang off.
    """
    from django.utils import timezone

    from .models import StatutoryRemittance

    overdue = StatutoryRemittance.objects.exclude(
        status=StatutoryRemittance.REMITTED
    ).filter(due_date__lt=timezone.localdate())
    count = overdue.count()
    if count:
        logger.warning("%d statutory remittance(s) are overdue", count)
    return count


@shared_task(name="payroll.expire_stale_advances")
def expire_stale_advances():
    """
    Cancel salary-advance requests left pending past the period they were
    raised against. An advance is a claim on wages earned in one specific
    month; once payroll for that month has run, approving it would recover
    against the wrong period.
    """
    from .models import AdvanceRequest, PayrollRun

    today = date.today()
    cancelled = 0
    stale = AdvanceRequest.objects.filter(status=AdvanceRequest.PENDING)
    for advance in stale.select_related('organisation'):
        period_over = (
            advance.period_year < today.year
            or (advance.period_year == today.year and advance.period_month < today.month)
        )
        if not period_over:
            continue
        run_done = PayrollRun.objects.filter(
            organisation=advance.organisation,
            period_year=advance.period_year,
            period_month=advance.period_month,
            status__in=[PayrollRun.APPROVED, PayrollRun.PAID],
        ).exists()
        if run_done:
            advance.status = AdvanceRequest.CANCELLED
            advance.decision_note = 'Auto-cancelled: payroll for the period has been processed.'
            advance.save(update_fields=['status', 'decision_note'])
            cancelled += 1
    if cancelled:
        logger.info("Auto-cancelled %d stale salary advance request(s)", cancelled)
    return cancelled

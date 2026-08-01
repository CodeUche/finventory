"""
Celery tasks for the tax compliance calendar.

Scheduled tasks:
  - generate_monthly_vat_obligations: runs on 1st of each month, creates VAT return obligation for prior month
  - generate_monthly_paye_obligations: runs on 1st of each month, creates PAYE obligation for prior month
  - flag_overdue_tax_obligations: runs daily, marks pending obligations past due_date as overdue
"""

import logging
from datetime import date, timedelta

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)

MONTHS = [
    '', 'January', 'February', 'March', 'April', 'May', 'June',
    'July', 'August', 'September', 'October', 'November', 'December',
]


def _prior_month(today=None):
    today = today or date.today()
    first_of_this = today.replace(day=1)
    last_of_prior = first_of_this - timedelta(days=1)
    return last_of_prior.year, last_of_prior.month


@shared_task(name='tax.generate_monthly_vat_obligations')
def generate_monthly_vat_obligations():
    """
    Create VAT return obligation for the prior month for all active orgs.
    VAT return is due by the 21st of the current month (for prior month).
    """
    from apps.tenancy.models import Organisation
    from .models import TaxObligation

    year, month = _prior_month()
    due_date = date(date.today().year, date.today().month, 21)

    orgs = Organisation.objects.filter(is_active=True)
    created = 0
    for org in orgs:
        label = f"VAT Return — {MONTHS[month]} {year}"
        _, was_created = TaxObligation.objects.get_or_create(
            organisation=org,
            obligation_type=TaxObligation.VAT,
            period_year=year,
            period_month=month,
            defaults={
                'label': label,
                'due_date': due_date,
                'status': TaxObligation.PENDING,
                'is_auto_generated': True,
            },
        )
        if was_created:
            created += 1

    logger.info("Generated VAT obligations for %d/%d: %d new", year, month, created)
    return created


@shared_task(name='tax.generate_monthly_paye_obligations')
def generate_monthly_paye_obligations():
    """
    Create PAYE remittance obligation for the prior month for all active orgs.
    PAYE is due by the 10th of the current month (for prior month).
    """
    from decimal import Decimal

    from django.db.models import Sum

    from apps.tenancy.models import Organisation
    from apps.payroll.models import StatutoryRemittance
    from .models import TaxObligation

    year, month = _prior_month()
    due_date = date(date.today().year, date.today().month, 10)

    orgs = Organisation.objects.filter(is_active=True)
    created = 0
    for org in orgs:
        label = f"PAYE Remittance — {MONTHS[month]} {year}"
        obligation, was_created = TaxObligation.objects.get_or_create(
            organisation=org,
            obligation_type=TaxObligation.PAYE,
            period_year=year,
            period_month=month,
            defaults={
                'label': label,
                'due_date': due_date,
                'status': TaxObligation.PENDING,
                'is_auto_generated': True,
            },
        )
        if was_created:
            created += 1

        # PAYE is now split across the State IRS of each employee's residence,
        # so the obligation total is the sum of every authority's row for the
        # period rather than a single record.
        total = StatutoryRemittance.objects.filter(
            organisation=org,
            remittance_type=StatutoryRemittance.PAYE,
            period_year=year,
            period_month=month,
        ).aggregate(total=Sum('amount_due'))['total']
        if total is not None and obligation.amount_due != total:
            obligation.amount_due = Decimal(str(total))
            obligation.save(update_fields=['amount_due'])

    logger.info("Generated PAYE obligations for %d/%d: %d new", year, month, created)
    return created


@shared_task(name='tax.flag_overdue_tax_obligations')
def flag_overdue_tax_obligations():
    """Daily: mark pending obligations whose due_date has passed as overdue."""
    from .models import TaxObligation

    today = date.today()
    updated = TaxObligation.objects.filter(
        status=TaxObligation.PENDING,
        due_date__lt=today,
    ).update(status=TaxObligation.OVERDUE)

    logger.info("Flagged %d overdue tax obligations", updated)
    return updated

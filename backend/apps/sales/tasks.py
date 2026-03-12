"""
Celery tasks for the sales app.

Registered in CELERY_BEAT_SCHEDULE (config/settings/base.py).
"""

import logging
from datetime import date, timedelta
from decimal import Decimal

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(name="sales.mark_overdue_invoices", bind=True, max_retries=3)
def mark_overdue_invoices(self):
    """
    Mark confirmed/partially-paid invoices as OVERDUE when their due_date has passed.

    Runs daily. Safe to re-run — already-overdue invoices are skipped.
    """
    from .models import Invoice

    today = timezone.now().date()
    qs = Invoice.objects.filter(
        status__in=[Invoice.Status.CONFIRMED, Invoice.Status.PARTIALLY_PAID],
        due_date__lt=today,
    )
    count = qs.update(status=Invoice.Status.OVERDUE)
    logger.info("mark_overdue_invoices: %d invoices marked overdue", count)
    return {"updated": count}


@shared_task(name="sales.generate_recurring_invoices", bind=True, max_retries=3)
def generate_recurring_invoices(self):
    """
    Generate invoices for all active RecurringInvoice schedules whose
    next_run_date is today or in the past.

    Runs daily. Advances next_run_date after each generation to prevent duplicates.
    """
    from .models import RecurringInvoice, RecurringInvoiceLog
    from .services import SaleService
    from apps.inventory.models import Warehouse

    today = timezone.now().date()
    due = RecurringInvoice.objects.filter(
        is_active=True,
        next_run_date__lte=today,
    ).select_related("customer", "warehouse", "created_by", "organisation")

    generated = 0
    failed = 0

    for ri in due:
        # Stop if past end_date or max_occurrences reached
        if ri.end_date and today > ri.end_date:
            ri.is_active = False
            ri.save(update_fields=["is_active"])
            continue
        if ri.max_occurrences and ri.occurrences_count >= ri.max_occurrences:
            ri.is_active = False
            ri.save(update_fields=["is_active"])
            continue

        try:
            invoice = SaleService.create_sale(
                organisation=ri.organisation,
                created_by=ri.created_by,
                customer=ri.customer,
                warehouse=ri.warehouse,
                items=ri.items,
                payment_method=ri.payment_method,
                notes=ri.notes,
                issue_date=today,
            )
            RecurringInvoiceLog.objects.create(
                organisation=ri.organisation,
                recurring_invoice=ri,
                invoice=invoice,
                status=RecurringInvoiceLog.SUCCESS,
            )
            ri.occurrences_count += 1
            ri.next_run_date = _next_run(today, ri.frequency, ri.interval)
            ri.save(update_fields=["occurrences_count", "next_run_date"])
            generated += 1
            logger.info("Recurring invoice generated: %s → %s", ri.template_name, invoice.invoice_number)
        except Exception as exc:
            failed += 1
            RecurringInvoiceLog.objects.create(
                organisation=ri.organisation,
                recurring_invoice=ri,
                invoice=None,
                status=RecurringInvoiceLog.FAILED,
                error_message=str(exc),
            )
            logger.warning("Recurring invoice failed for %s: %s", ri.template_name, exc)

    logger.info("generate_recurring_invoices: %d generated, %d failed", generated, failed)
    return {"generated": generated, "failed": failed}


def _next_run(from_date: date, frequency: str, interval: int) -> date:
    """Compute the next run date given a frequency and interval."""
    if frequency == "daily":
        return from_date + timedelta(days=interval)
    if frequency == "weekly":
        return from_date + timedelta(weeks=interval)
    if frequency == "monthly":
        month = from_date.month - 1 + interval
        year = from_date.year + month // 12
        month = month % 12 + 1
        day = min(from_date.day, _days_in_month(year, month))
        return date(year, month, day)
    if frequency == "quarterly":
        return _next_run(from_date, "monthly", interval * 3)
    if frequency == "annual":
        return from_date.replace(year=from_date.year + interval)
    return from_date + timedelta(days=30)


def _days_in_month(year: int, month: int) -> int:
    import calendar
    return calendar.monthrange(year, month)[1]


@shared_task(name="sales.create_year_archive_folders", bind=True, max_retries=3)
def create_year_archive_folders(self):
    """
    Runs on Jan 1 each year (00:30).
    Creates an InvoiceFolder named "<YYYY> Archive" for every organisation
    and moves all unarchived invoices from the just-ended year into it.
    Safe to re-run: uses get_or_create, never creates duplicate folders.
    """
    from .models import Invoice, InvoiceFolder
    from apps.tenancy.models import Organisation

    prev_year = timezone.now().year - 1
    folder_name = f"{prev_year} Archive"
    folder_date = date(prev_year, 12, 31)

    orgs = Organisation.objects.filter(is_active=True, is_deleted=False)
    folders_created = 0
    invoices_moved = 0

    for org in orgs:
        try:
            folder, created = InvoiceFolder.objects.get_or_create(
                organisation=org,
                name=folder_name,
                defaults={
                    'folder_date': folder_date,
                    'description': f'Automatically archived invoices from {prev_year}',
                },
            )
            if created:
                folders_created += 1

            count = Invoice.objects.filter(
                organisation=org,
                issue_date__year=prev_year,
                folder__isnull=True,
            ).update(folder=folder)
            invoices_moved += count
        except Exception as exc:
            logger.warning("create_year_archive_folders: failed for org %s: %s", org.id, exc)

    logger.info(
        "create_year_archive_folders: %d folders created, %d invoices moved for year %d",
        folders_created, invoices_moved, prev_year,
    )
    return {"year": prev_year, "folders_created": folders_created, "invoices_moved": invoices_moved}

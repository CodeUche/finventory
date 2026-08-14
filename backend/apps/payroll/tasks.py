"""Scheduled HR jobs."""

import logging
from datetime import date, timedelta

from celery import shared_task

from apps.core.tenant_context import for_each_organisation

logger = logging.getLogger(__name__)


@shared_task(name="payroll.accrue_monthly_leave")
def accrue_monthly_leave():
    """
    Add one month's entitlement to every monthly-accrual leave balance.

    Runs on the 1st of each month and accrues for the month just completed, so
    an employee's balance reflects service already given rather than service
    they are about to give.
    """
    from .services import LeaveService

    today = date.today()
    if today.month == 1:
        year, month = today.year - 1, 12
    else:
        year, month = today.year, today.month - 1

    # Per-org RLS context — accrue_month reads payroll_employee, which is
    # RLS-protected and returns zero rows under the SENTINEL (NEW-7).
    result = for_each_organisation(
        lambda org: LeaveService.accrue_month(org, year, month),
        task_name="payroll.accrue_monthly_leave",
    )
    total = result["processed"]
    logger.info("Leave accrual %s-%02d: %d balances updated", year, month, total)
    return total


@shared_task(name="payroll.send_payslips_async")
def send_payslips_async(run_id, employee_ids=None):
    """
    Generate and email payslip PDFs entirely server-side — no client
    involvement. Complements (does not replace) the existing
    PayrollRunViewSet.send_payslips endpoint, which still accepts a
    client-rendered pdf_base64 for callers that render client-side.
    """
    from email import encoders
    from email.mime.base import MIMEBase

    from django.core.mail import EmailMultiAlternatives

    from .models import PayrollRun, PayslipDelivery, PayslipLine
    from .pdf import build_payslip_pdf

    try:
        run = PayrollRun.objects.get(id=run_id)
    except PayrollRun.DoesNotExist:
        logger.warning("send_payslips_async: run %s not found", run_id)
        return {'sent': 0, 'failed': 0, 'skipped': 0}

    qs = run.payslips.select_related('employee', 'organisation')
    if employee_ids:
        qs = qs.filter(employee_id__in=employee_ids)

    org_name = run.organisation.name
    period = f"{run.period_year}-{run.period_month:02d}"
    sent, failed, skipped = 0, 0, 0

    for payslip in qs:
        employee = payslip.employee
        recipient = (employee.email or '').strip()
        if not recipient:
            PayslipDelivery.objects.create(
                organisation=run.organisation, payslip=payslip,
                channel=PayslipDelivery.EMAIL, recipient='',
                status=PayslipDelivery.SKIPPED, error='No email address on file',
            )
            skipped += 1
            continue
        try:
            pdf_bytes = build_payslip_pdf(payslip)

            from apps.connectors.services import maybe_save_pdf_to_drive
            maybe_save_pdf_to_drive(
                run.organisation, f"Payslip-{employee.employee_id}-{period}.pdf", pdf_bytes,
            )

            subject = f"Payslip for {period} — {org_name}"
            body = (
                f"Dear {employee.first_name},\n\nYour payslip for {period} is attached.\n\n"
                f"Net pay: {payslip.net_salary}\n\n{org_name}"
            )
            msg = EmailMultiAlternatives(subject, body, to=[recipient])
            part = MIMEBase('application', 'pdf')
            part.set_payload(pdf_bytes)
            encoders.encode_base64(part)
            part.add_header(
                'Content-Disposition', 'attachment',
                filename=f"Payslip-{employee.employee_id}-{period}.pdf",
            )
            msg.attach(part)
            msg.send(fail_silently=False)
            PayslipDelivery.objects.create(
                organisation=run.organisation, payslip=payslip,
                channel=PayslipDelivery.EMAIL, recipient=recipient,
                status=PayslipDelivery.SENT,
            )
            sent += 1
        except Exception as exc:
            PayslipDelivery.objects.create(
                organisation=run.organisation, payslip=payslip,
                channel=PayslipDelivery.EMAIL, recipient=recipient,
                status=PayslipDelivery.FAILED, error=str(exc)[:500],
            )
            failed += 1
            logger.warning("send_payslips_async: failed for payslip %s: %s", payslip.id, exc)

    logger.info(
        "send_payslips_async run=%s sent=%d failed=%d skipped=%d", run_id, sent, failed, skipped,
    )
    return {'sent': sent, 'failed': failed, 'skipped': skipped}


@shared_task(name="payroll.carry_forward_leave")
def carry_forward_leave():
    """
    Year-end leave carry-forward. Runs on 1 Jan and, for every org, recomputes
    and SETS (never increments — safe to re-run) each employee's
    LeaveBalance.carried_forward for the new year to
    min(prior_year_available_days, leave_type.carry_forward_max).

    Wrapped per-org so one organisation's failure does not stop the batch —
    the same pattern as accrue_monthly_leave above.
    """
    from .services import LeaveService

    today = date.today()
    new_year = today.year
    prior_year = new_year - 1

    # Per-org RLS context (NEW-7) — the helper already isolates per-org
    # failures, which is the behaviour this task's docstring describes.
    result = for_each_organisation(
        lambda org: LeaveService.carry_forward_year_end(org, prior_year, new_year),
        task_name="payroll.carry_forward_leave",
    )
    total_updated = result["processed"]
    logger.info("Leave carry-forward %s→%s: %d balances updated", prior_year, new_year, total_updated)
    return total_updated


@shared_task(name="payroll.flag_expiring_documents")
def flag_expiring_documents():
    """
    Weekly job: find EmployeeDocuments expiring within 60/30/7 days and log +
    email HR (reusing the EmailMultiAlternatives pattern from send_payslips).

    Range-safe, not exact-date: for each threshold we scan every document
    whose expiry falls in (today, today + threshold] — a "catch-up" window —
    rather than matching exactly ``today + threshold``. An exact-match query
    permanently skips a document if the weekly job misses the one day a
    threshold lands on (worker downtime, missed run, org created after that
    date already passed). To keep this idempotent under a widened window,
    each EmployeeDocument tracks which thresholds have already fired in
    ``expiry_alert_thresholds_sent`` (mirrors the
    PayrollSettings.public_holidays_seeded_years "seeded markers" pattern) —
    a document is only ever alerted once per threshold, no matter how many
    times the range re-scans it.
    """
    from django.core.mail import EmailMultiAlternatives
    from django.utils import timezone

    from .models import EmployeeDocument

    today = timezone.localdate()
    thresholds = [60, 30, 7]

    # Per-org RLS context (NEW-7): payroll_employeedocument is RLS-protected,
    # so under the SENTINEL this scanned zero documents every week.
    def _flag(org):
        rows = []
        docs_to_update = []
        for threshold in thresholds:
            target = today + timedelta(days=threshold)
            # Catch-up range: anything expiring between today and the
            # threshold horizon (inclusive) that hasn't already been
            # alerted AT THIS THRESHOLD.
            docs = list(
                EmployeeDocument.objects.filter(
                    organisation=org,
                    expiry_date__gte=today,
                    expiry_date__lte=target,
                ).select_related('employee')
            )
            for d in docs:
                sent = d.expiry_alert_thresholds_sent or []
                if threshold in sent:
                    continue
                rows.append((threshold, d))
                sent.append(threshold)
                d.expiry_alert_thresholds_sent = sent
                docs_to_update.append(d)
        if not rows:
            return 0
        logger.warning(
            "%d employee document(s) expiring soon for org %s", len(rows), org.id,
        )
        hr_emails = list(
            org.memberships.filter(
                is_active=True, role__in=['owner', 'admin'],
            ).values_list('user__email', flat=True)
        )
        hr_emails = [e for e in hr_emails if e]
        if hr_emails:
            lines = [
                f"- {d.employee.full_name}: {d.get_document_type_display()} "
                f"'{d.name}' expires {d.expiry_date} (in {threshold} days)"
                for threshold, d in rows
            ]
            body = "The following employee documents are expiring soon:\n\n" + "\n".join(lines)
            try:
                msg = EmailMultiAlternatives(
                    subject=f"Employee documents expiring soon — {org.name}",
                    body=body, to=hr_emails,
                )
                msg.send(fail_silently=True)
            except Exception:
                pass
        # Mark thresholds as sent regardless of whether an email address
        # was on file — the alert was raised (logged) either way, and we
        # must not re-log the same document/threshold every week.
        if docs_to_update:
            EmployeeDocument.objects.bulk_update(
                docs_to_update, ['expiry_alert_thresholds_sent'],
            )
        return len(rows)

    return for_each_organisation(
        _flag, task_name="payroll.flag_expiring_documents",
    )["processed"]


@shared_task(name="payroll.post_leave_accrual_true_up")
def post_leave_accrual_true_up_task():
    """Monthly: post the delta between current leave liability and the last-posted figure."""
    from apps.tenancy.models import Organisation

    from apps.accounting.services import AccountingService

    today = date.today()

    # Per-org RLS context (NEW-7). This task posts to accounting_journalentry,
    # which is RLS-protected: under the SENTINEL the INSERT is refused by the
    # policy's WITH CHECK, so the leave liability never reached the balance
    # sheet at all — the exact failure this task's docstring warns about.
    result = for_each_organisation(
        lambda org: 1 if AccountingService.post_leave_accrual_true_up(org, today) else 0,
        task_name="payroll.post_leave_accrual_true_up",
    )
    posted = result["processed"]
    logger.info("Leave accrual true-up: %d org(s) posted", posted)
    return posted


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

    # Swept per organisation because the PayrollRun lookup below reads
    # payroll_payrollrun, which IS RLS-protected: under the SENTINEL it always
    # returned False, so `run_done` never fired and no stale advance was ever
    # cancelled. AdvanceRequest itself is not RLS-protected, which is why the
    # outer query looked healthy while the decision it fed was always wrong
    # (NEW-7).
    def _expire(org):
        cancelled = 0
        stale = AdvanceRequest.objects.filter(
            organisation=org, status=AdvanceRequest.PENDING,
        )
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
        return cancelled

    cancelled = for_each_organisation(
        _expire, task_name="payroll.expire_stale_advances",
    )["processed"]
    if cancelled:
        logger.info("Auto-cancelled %d stale salary advance request(s)", cancelled)
    return cancelled

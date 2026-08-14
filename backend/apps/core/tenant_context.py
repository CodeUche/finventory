"""
Tenant context for code that runs OUTSIDE the HTTP request cycle.

Why this exists
---------------
``RLSMiddleware`` sets ``app.current_org_id`` on the PostgreSQL connection for
every HTTP request, which is what makes the Row Level Security policies in
``apps/core/migrations/0002_enable_rls.py`` resolve to the caller's tenant.

Celery workers never run that middleware.  A task therefore inherits the
SENTINEL org id (``00000000-...-0000``), which matches no row, so **every query
against an RLS-protected table silently returns zero rows** and every INSERT is
refused by the policy's WITH CHECK clause.  The task still logs success and
returns normally — the failure is completely silent.

That is not hypothetical: before this module existed, all 20 scheduled tasks
(overdue invoices, recurring invoices, depreciation, leave accrual, tax
obligations…) were no-ops in production for exactly this reason.

Use ``for_each_organisation`` for cross-tenant sweeps, and
``organisation_context`` when a task already knows which tenant it acts on.

    @shared_task(name="sales.mark_overdue_invoices")
    def mark_overdue_invoices():
        def _run(org):
            return Invoice.objects.filter(...).update(...)
        return for_each_organisation(_run, task_name="sales.mark_overdue_invoices")

Both helpers restore the SENTINEL afterwards.  Celery reuses connections across
tasks, so leaving a real org id behind would leak that tenant's context into
whatever task ran next on the same worker — a cross-tenant data bug far worse
than the one this module fixes.
"""

import logging
from contextlib import contextmanager

from apps.core.middleware import SENTINEL, _set_org

logger = logging.getLogger(__name__)


@contextmanager
def organisation_context(organisation_id):
    """
    Bind the connection to ``organisation_id`` for the duration of the block.

    Restores the SENTINEL on exit, including when the body raises, so a failing
    task can never hand a live tenant context to the next task on this worker.

    No-ops safely on non-PostgreSQL backends (``_set_org`` guards on vendor),
    so it is inert under the SQLite test settings rather than raising.
    """
    _set_org(str(organisation_id))
    try:
        yield
    finally:
        _set_org(SENTINEL)


def for_each_organisation(fn, *, task_name="", queryset=None):
    """
    Run ``fn(organisation)`` once per active organisation, each inside that
    organisation's RLS context.  ``fn`` receives the ``Organisation`` instance,
    so call sites that need the object do not have to re-query for it.

    ``fn`` may return a count (or any value); returned ints are summed into the
    aggregate ``processed`` figure so converted tasks keep reporting a
    meaningful total.

    Failures are isolated per organisation: one tenant raising does not abort
    the sweep for the others.  This matters for a shared scheduler — a single
    malformed tenant record must not stop every other tenant's payroll accrual.

    ``tenancy_organisation`` deliberately has RLS disabled (see migrations 0007
    and 0008, the bootstrap tables), which is what makes enumerating tenants
    from a task possible at all.  If RLS is ever enabled on it, this function
    is the thing that breaks first and every sweep silently processes nothing —
    the test suite asserts the enumeration is non-empty for that reason.

    Returns ``{"organisations": int, "processed": int, "failed": int}``.
    """
    from apps.tenancy.models import Organisation

    if queryset is None:
        queryset = Organisation.objects.filter(is_active=True)

    # Materialise before the sweep: the queryset is evaluated with whatever org
    # context is current, and we are about to change that repeatedly.
    organisations = list(queryset)

    processed = 0
    failed = 0

    for org in organisations:
        try:
            with organisation_context(org.id):
                result = fn(org)
            if isinstance(result, int):
                processed += result
        except Exception as exc:
            failed += 1
            # Log and continue — one tenant's bad data must not stop the sweep.
            logger.exception(
                "%s failed for organisation %s: %s",
                task_name or fn.__name__, org.id, exc,
            )

    logger.info(
        "%s: swept %d organisation(s), processed=%d, failed=%d",
        task_name or fn.__name__, len(organisations), processed, failed,
    )
    return {"organisations": len(organisations), "processed": processed, "failed": failed}

"""
Fan-out: turning one thing that happened into the right people being told.

Two decisions live here.

WHO gets told. For leave that is the employee's line manager plus anyone who
can view leave requests — so cover exists when the manager is away, which is
exactly when a leave request is most likely to sit unanswered. "Can view leave
requests" is read from the permission at send time, not hardcoded, so if the
leave tick is later split into finer privileges this inherits the split for
free.

HOW they are told. In-app always: that is the record of what happened, not a
channel to opt out of. Email only if the person asked for it, and sent through
the organisation's OWN connected mailbox so a leave decision arrives from
hr@theircompany.com rather than a generic Audity address.
"""

import logging

from django.db import transaction
from django.utils import timezone

from apps.tenancy.models import Membership, ModulePermission

from .models import Notification, NotificationPreference

logger = logging.getLogger(__name__)

# Anything at or above "view" can see the area, so anything at or above "view"
# is a candidate to be told about it. "none", or no record at all, is not.
_CAN_SEE = ("view", "write", "edit")


def recipients_for_module(organisation, module: str, include_users=()):
    """
    Everyone who should hear about `module`, plus specific people named by the
    caller (a line manager, a requester) whether or not they hold the tick.

    Owners and admins are included because they bypass the ticks by design —
    if they can see the area, they can be told about it.

    Returns User objects, de-duplicated, and never includes an inactive
    membership.
    """
    memberships = (
        Membership.objects
        .filter(organisation=organisation, is_active=True)
        .select_related("user")
    )

    allowed_ids = set()
    tick_by_membership = {
        p.membership_id: p.access_level
        for p in ModulePermission.objects.filter(
            membership__in=memberships, module=module,
        )
    }

    for m in memberships:
        if m.role in ("owner", "admin"):
            allowed_ids.add(m.user_id)
            continue
        if tick_by_membership.get(m.id) in _CAN_SEE:
            allowed_ids.add(m.user_id)

    users = {m.user_id: m.user for m in memberships}
    for user in include_users:
        # A named recipient is told regardless of ticks — the person whose
        # leave it is must hear the decision even though they almost certainly
        # do not hold the leave permission.
        if user is not None:
            users.setdefault(user.id, user)
            allowed_ids.add(user.id)

    return [users[uid] for uid in allowed_ids if uid in users]


def notify(
    organisation, recipients, *, category, title,
    body="", link="", event=None, exclude=None,
):
    """
    Record the notification for each recipient, and email those who asked.

    Never raises. A failure to tell someone must not roll back the thing that
    happened — approving leave that then fails to send an email has still
    approved the leave, and throwing here would undo it.

    Returns the Notification objects created.
    """
    excluded_id = getattr(exclude, "id", None)
    created = []

    for user in recipients:
        if user is None or user.id == excluded_id:
            # The person who performed the action does not need telling that
            # they performed it.
            continue
        try:
            notification = Notification.objects.create(
                organisation=organisation, recipient=user, event=event,
                category=category, title=title, body=body, link=link,
            )
            created.append(notification)
        except Exception as exc:
            logger.exception(
                "could not record notification for user %s: %s", user.id, exc,
            )

    for notification in created:
        _maybe_email(organisation, notification)

    return created


def _wants_email(organisation, user, category) -> bool:
    membership = user.memberships.filter(
        organisation=organisation, is_active=True,
    ).first()
    if not membership:
        return False
    pref = NotificationPreference.objects.filter(
        membership=membership, category=category,
    ).first()
    # Absent means off: nobody is emailed without asking.
    return bool(pref and pref.email_enabled)


def _maybe_email(organisation, notification):
    """
    Send through the organisation's connected mailbox, if they have one and
    the recipient opted in.

    Sent inline rather than queued, deliberately: no Celery worker runs in
    production today (NEW-9), so a queued email would never leave. Leave
    decisions are a handful a day, not a hot path. Every failure is swallowed
    and recorded on the notification rather than surfaced, because the
    business action has already happened and must not be undone by a mail
    problem. Move this to the worker once one exists — the status field is
    already shaped for it.
    """
    recipient = notification.recipient
    if not (recipient.email or "").strip():
        return
    if not _wants_email(organisation, recipient, notification.category):
        return

    try:
        from apps.connectors.models import Connector, ConnectorConnection
        from apps.connectors.gmail import GmailService

        connection = ConnectorConnection.objects.filter(
            organisation=organisation, connector_key=Connector.GMAIL,
            status=ConnectorConnection.Status.ACTIVE,
        ).first()
        if not connection:
            notification.email_status = Notification.EmailStatus.NO_CONNECTOR
            notification.save(update_fields=["email_status", "updated_at"])
            return

        ok, _status, error = GmailService.send_email(
            connection,
            to_email=recipient.email,
            subject=notification.title,
            body_text=notification.body or notification.title,
        )
        notification.email_status = (
            Notification.EmailStatus.SENT if ok else Notification.EmailStatus.FAILED
        )
        notification.email_error = "" if ok else (error or "")[:500]
        notification.emailed_at = timezone.now() if ok else None
        notification.save(update_fields=[
            "email_status", "email_error", "emailed_at", "updated_at",
        ])
    except Exception as exc:
        logger.warning(
            "email delivery failed for notification %s: %s", notification.id, exc,
        )
        try:
            notification.email_status = Notification.EmailStatus.FAILED
            notification.email_error = str(exc)[:500]
            notification.save(update_fields=[
                "email_status", "email_error", "updated_at",
            ])
        except Exception:
            pass


def notify_after_commit(*args, **kwargs):
    """
    Fan out once the surrounding transaction has actually committed.

    Approving leave writes several rows; if that rolls back, nobody should
    have been told it happened. on_commit is a no-op outside a transaction, so
    this is safe to call either way.
    """
    transaction.on_commit(lambda: notify(*args, **kwargs))

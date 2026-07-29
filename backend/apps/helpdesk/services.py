"""Help-desk notifications.

Every ticket a customer raises — and every reply on the thread — is emailed to
the platform support inbox (SUPPORT_TICKET_EMAIL, default
support@auditytechnologies.com). When support replies from the platform inbox,
the ticket's creator is emailed back so the loop closes.

All sends are best-effort: a mail failure is logged, never raised, so it can
never break ticket creation or commenting.
"""
import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.utils.html import escape

logger = logging.getLogger(__name__)


def _user_label(user) -> str:
    full = f"{user.first_name} {user.last_name}".strip()
    return full or user.email


def _from_email() -> str:
    return getattr(settings, "DEFAULT_FROM_EMAIL", None) or "noreply@audity.app"


def _support_email() -> str:
    return getattr(settings, "SUPPORT_TICKET_EMAIL", None) or "support@auditytechnologies.com"


def _send(subject: str, plain: str, html: str, to: list[str], reply_to: list[str] | None = None) -> None:
    try:
        recipients = [addr for addr in to if addr]
        if not recipients:
            return
        msg = EmailMultiAlternatives(
            subject=subject,
            body=plain,
            from_email=_from_email(),
            to=recipients,
            reply_to=[addr for addr in (reply_to or []) if addr] or None,
        )
        msg.attach_alternative(html, "text/html")
        msg.send(fail_silently=True)
    except Exception as exc:  # pragma: no cover — defensive; mail must never break the request
        logger.warning("Help-desk email (%s) could not be sent: %s", subject, exc)


def _ticket_meta_rows(ticket) -> str:
    org = escape(ticket.organisation.name)
    creator = escape(_user_label(ticket.created_by))
    creator_email = escape(getattr(ticket.created_by, "email", "") or "")
    priority = escape(ticket.get_priority_display())
    category = escape(ticket.category or "—")
    return (
        f"<tr><td style='color:#64748b;padding:2px 12px 2px 0'>Organisation</td><td><strong>{org}</strong></td></tr>"
        f"<tr><td style='color:#64748b;padding:2px 12px 2px 0'>Raised by</td><td>{creator} &lt;{creator_email}&gt;</td></tr>"
        f"<tr><td style='color:#64748b;padding:2px 12px 2px 0'>Priority</td><td>{priority}</td></tr>"
        f"<tr><td style='color:#64748b;padding:2px 12px 2px 0'>Category</td><td>{category}</td></tr>"
    )


def notify_new_ticket(ticket) -> None:
    """Email the support inbox that a new ticket was raised."""
    subject = f"[Ticket {ticket.ticket_number}] {ticket.subject}"
    plain = (
        f"New support ticket {ticket.ticket_number}\n\n"
        f"Organisation: {ticket.organisation.name}\n"
        f"Raised by: {_user_label(ticket.created_by)} <{getattr(ticket.created_by, 'email', '')}>\n"
        f"Priority: {ticket.get_priority_display()}\n"
        f"Category: {ticket.category or '—'}\n\n"
        f"Subject: {ticket.subject}\n\n"
        f"{ticket.description or '(no description)'}\n"
    )
    html = f"""<!DOCTYPE html>
<html><body style="font-family:sans-serif;background:#f1f5f9;padding:24px;">
  <div style="max-width:560px;margin:auto;background:#fff;border-radius:12px;padding:28px;">
    <p style="color:#f97316;font-weight:700;letter-spacing:.05em;text-transform:uppercase;font-size:12px;margin:0 0 6px;">New support ticket</p>
    <h2 style="margin:0 0 4px;color:#0f172a;">{escape(ticket.subject)}</h2>
    <p style="color:#94a3b8;font-size:13px;margin:0 0 18px;">{escape(ticket.ticket_number)}</p>
    <table style="font-size:14px;color:#0f172a;border-collapse:collapse;margin-bottom:18px;">{_ticket_meta_rows(ticket)}</table>
    <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:14px;white-space:pre-wrap;color:#334155;font-size:14px;">{escape(ticket.description or '(no description)')}</div>
    <p style="color:#94a3b8;font-size:12px;margin-top:18px;">Reply to this email to respond to the customer, or open the Support inbox in Platform Admin.</p>
  </div>
</body></html>"""
    _send(subject, plain, html, [_support_email()], reply_to=[getattr(ticket.created_by, "email", "")])


def notify_new_comment(comment) -> None:
    """A customer added a comment — forward it to the support inbox."""
    ticket = comment.ticket
    subject = f"[Ticket {ticket.ticket_number}] New reply — {ticket.subject}"
    author = _user_label(comment.author)
    plain = (
        f"New reply on ticket {ticket.ticket_number} ({ticket.organisation.name})\n\n"
        f"From: {author}\n\n{comment.body}\n"
    )
    html = f"""<!DOCTYPE html>
<html><body style="font-family:sans-serif;background:#f1f5f9;padding:24px;">
  <div style="max-width:560px;margin:auto;background:#fff;border-radius:12px;padding:28px;">
    <p style="color:#94a3b8;font-size:13px;margin:0 0 4px;">{escape(ticket.ticket_number)} · {escape(ticket.organisation.name)}</p>
    <h2 style="margin:0 0 14px;color:#0f172a;font-size:17px;">New reply from {escape(author)}</h2>
    <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:14px;white-space:pre-wrap;color:#334155;font-size:14px;">{escape(comment.body)}</div>
  </div>
</body></html>"""
    _send(subject, plain, html, [_support_email()], reply_to=[getattr(comment.author, "email", "")])


def notify_creator_reply(comment) -> None:
    """Support replied from the platform inbox — notify the ticket creator."""
    ticket = comment.ticket
    creator_email = getattr(ticket.created_by, "email", "")
    if not creator_email:
        return
    subject = f"[Ticket {ticket.ticket_number}] Support replied — {ticket.subject}"
    plain = (
        f"Audity Support replied to your ticket {ticket.ticket_number}.\n\n"
        f"{comment.body}\n\n"
        f"Open Audity → Tickets to continue the conversation.\n"
    )
    html = f"""<!DOCTYPE html>
<html><body style="font-family:sans-serif;background:#f1f5f9;padding:24px;">
  <div style="max-width:560px;margin:auto;background:#fff;border-radius:12px;padding:28px;">
    <p style="color:#f97316;font-weight:700;letter-spacing:.05em;text-transform:uppercase;font-size:12px;margin:0 0 6px;">Audity Support replied</p>
    <p style="color:#94a3b8;font-size:13px;margin:0 0 14px;">{escape(ticket.ticket_number)} · {escape(ticket.subject)}</p>
    <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:14px;white-space:pre-wrap;color:#334155;font-size:14px;">{escape(comment.body)}</div>
    <p style="color:#94a3b8;font-size:12px;margin-top:18px;">Open Audity → Tickets to reply.</p>
  </div>
</body></html>"""
    _send(subject, plain, html, [creator_email], reply_to=[_support_email()])

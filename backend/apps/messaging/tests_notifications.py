"""
Tests for the messaging -> notifications hook (Gap 3a).

A message reaches someone who isn't on the Messages page — or has the app
closed entirely — the same way every other business event does: an in-app
Notification, emailed only if the recipient opted in for the 'messages'
category. No WebSockets, no new delivery mechanism — this just wires
create_message() into the existing apps.notifications fan-out.

_notify_new_message defers the actual Notification row creation to
transaction.on_commit() (via notify_after_commit), so every test that
expects to see one wraps the triggering call in
self.captureOnCommitCallbacks(execute=True) — the same pattern already used
in apps/notifications/test_leave_flow.py for the identical reason.
"""

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.authentication.models import User
from apps.messaging import services
from apps.messaging.models import ConversationParticipant
from apps.notifications.models import Notification, NotificationPreference
from apps.tenancy.models import Membership
from apps.tenancy.services import OrganisationService


def _make_user(email):
    return User.objects.create_user(
        email=email, password="TestPass123!",
        first_name="Test", last_name="User", is_verified=True,
    )


def _make_org(user, name="Messaging Org"):
    return OrganisationService.create_organisation(
        name=name, owner=user, extra={"currency": "NGN", "country": "NG"},
    )


def _add_member(org, user, role=Membership.Role.STAFF):
    return Membership.objects.create(user=user, organisation=org, role=role, is_active=True)


def _auth_client(user, org):
    client = APIClient()
    refresh = RefreshToken.for_user(user)
    client.credentials(
        HTTP_AUTHORIZATION=f"Bearer {str(refresh.access_token)}",
        HTTP_X_ORGANISATION_ID=str(org.id),
    )
    return client


class MessageNotificationHookTests(TestCase):
    def setUp(self):
        self.sender = _make_user("sender@example.com")
        self.org = _make_org(self.sender)
        self.recipient = _make_user("recipient@example.com")
        _add_member(self.org, self.recipient, Membership.Role.STAFF)
        self.conversation, _ = services.get_or_create_direct_conversation(
            organisation=self.org, user=self.sender, other_user=self.recipient,
        )

    def _send(self, **kwargs):
        with self.captureOnCommitCallbacks(execute=True):
            return services.create_message(conversation=self.conversation, sender=self.sender, **kwargs)

    def test_recipient_gets_an_in_app_notification(self):
        self._send(body="Hello there")
        notif = Notification.objects.filter(
            organisation=self.org, recipient=self.recipient, category="messages",
        ).first()
        self.assertIsNotNone(notif, "recipient should be notified of the new message")
        self.assertIn("Test User", notif.title)  # sender's display name
        self.assertEqual(notif.body, "Hello there")
        self.assertEqual(notif.link, "/messages")

    def test_sender_does_not_notify_themselves(self):
        self._send(body="Hi")
        self.assertFalse(
            Notification.objects.filter(
                organisation=self.org, recipient=self.sender, category="messages",
            ).exists(),
            "the sender must not be told they sent their own message",
        )

    def test_idempotent_resend_does_not_double_notify(self):
        """Same client_nonce twice must not raise two notifications."""
        self._send(body="Once", client_nonce="dup-1")
        self._send(body="Once", client_nonce="dup-1")
        count = Notification.objects.filter(
            organisation=self.org, recipient=self.recipient, category="messages",
        ).count()
        self.assertEqual(count, 1)

    def test_email_is_not_sent_unless_the_recipient_opted_in(self):
        """Default is off — matches every other category (nobody is emailed
        without asking)."""
        self._send(body="Quiet one")
        notif = Notification.objects.get(
            organisation=self.org, recipient=self.recipient, category="messages",
        )
        self.assertEqual(notif.email_status, Notification.EmailStatus.NOT_REQUESTED)

    def test_email_is_attempted_once_the_recipient_opts_in(self):
        """Opted in but no mailbox connected -> recorded as NO_CONNECTOR, not
        silently skipped — same behaviour as every other category."""
        recipient_membership = Membership.objects.get(organisation=self.org, user=self.recipient)
        NotificationPreference.objects.create(
            organisation=self.org, membership=recipient_membership,
            category="messages", email_enabled=True,
        )
        self._send(body="Hey")
        notif = Notification.objects.get(
            organisation=self.org, recipient=self.recipient, category="messages",
        )
        self.assertEqual(notif.email_status, Notification.EmailStatus.NO_CONNECTOR)

    def test_messages_is_a_selectable_category_on_the_preferences_endpoint(self):
        client = _auth_client(self.recipient, self.org)
        res = client.get("/api/v1/notifications/preferences/mine/")
        self.assertEqual(res.status_code, 200)
        self.assertIn("messages", res.data)
        self.assertFalse(res.data["messages"], "default must be off, like every other category")

        res = client.put(
            "/api/v1/notifications/preferences/mine/", {"messages": True}, format="json",
        )
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.data["messages"])

    def test_a_participant_who_left_is_not_notified(self):
        participant = ConversationParticipant.objects.get(
            conversation=self.conversation, user=self.recipient,
        )
        participant.left_at = timezone.now()
        participant.save(update_fields=["left_at"])

        self._send(body="Are you there?")
        self.assertFalse(
            Notification.objects.filter(
                organisation=self.org, recipient=self.recipient, category="messages",
            ).exists(),
        )

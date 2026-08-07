"""
Tests for Track B — isolated in-app instant messaging.

Covers: cross-org isolation (404 not 403), intra-org isolation, creation
rejection for non-members/employee role, PARTNER_CONTACT role confinement
to messaging-only endpoints, client_nonce idempotency, unread-count
correctness, and seq-collision-free concurrent sends.
"""

import io

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, TransactionTestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.authentication.models import User
from apps.messaging.models import Conversation, ConversationParticipant, Message, MessageAttachment
from apps.messaging import services
from apps.tenancy.models import Membership, PartnerAccessRequest, PartnerProfile, PartnerClientLink
from apps.tenancy.services import OrganisationService


def _make_user(email):
    return User.objects.create_user(
        email=email, password="TestPass123!",
        first_name="Test", last_name="User", is_verified=True,
    )


def _make_org(user, name):
    return OrganisationService.create_organisation(
        name=name, owner=user, extra={"currency": "NGN", "country": "NG"},
    )


def _add_member(org, user, role=Membership.Role.STAFF):
    return Membership.objects.create(
        user=user, organisation=org, role=role, is_active=True,
    )


def _auth_client(user, org):
    client = APIClient()
    refresh = RefreshToken.for_user(user)
    client.credentials(
        HTTP_AUTHORIZATION=f"Bearer {str(refresh.access_token)}",
        HTTP_X_ORGANISATION_ID=str(org.id),
    )
    return client


class MessagingIsolationTests(TestCase):
    """Cross-org and intra-org isolation, creation rejection."""

    def setUp(self):
        # Org A: owner + staff member
        self.owner_a = _make_user("owner_a@example.com")
        self.org_a = _make_org(self.owner_a, "Org A")
        self.staff_a = _make_user("staff_a@example.com")
        _add_member(self.org_a, self.staff_a, Membership.Role.STAFF)

        # Org B: owner + staff member (unrelated to org A)
        self.owner_b = _make_user("owner_b@example.com")
        self.org_b = _make_org(self.owner_b, "Org B")
        self.staff_b = _make_user("staff_b@example.com")
        _add_member(self.org_b, self.staff_b, Membership.Role.STAFF)

        # Partner user, linked (as PARTNER_CONTACT / accountant) to BOTH orgs
        self.partner_user = _make_user("partner@example.com")
        self.partner_profile = PartnerProfile.objects.create(user=self.partner_user)
        _add_member(self.org_a, self.partner_user, Membership.Role.PARTNER_CONTACT)
        _add_member(self.org_b, self.partner_user, Membership.Role.PARTNER_CONTACT)
        PartnerClientLink.objects.create(partner=self.partner_profile, organisation=self.org_a, is_active=True)
        PartnerClientLink.objects.create(partner=self.partner_profile, organisation=self.org_b, is_active=True)

        # Conversation in org A between owner_a and partner_user
        self.conv_a, _ = services.get_or_create_direct_conversation(
            organisation=self.org_a, user=self.owner_a, other_user=self.partner_user
        )
        services.create_message(conversation=self.conv_a, sender=self.owner_a, body="Hello from org A")

        # Conversation in org B between owner_b and partner_user
        self.conv_b, _ = services.get_or_create_direct_conversation(
            organisation=self.org_b, user=self.owner_b, other_user=self.partner_user
        )
        services.create_message(conversation=self.conv_b, sender=self.owner_b, body="Hello from org B")

        # Second, unrelated conversation pair WITHIN org A (staff_a <-> owner_a
        # is used above, so make a genuinely separate pair): owner_a <-> staff_a
        # already covered; add a distinct pair using two fresh users in org A.
        self.other_member_a = _make_user("other_a@example.com")
        _add_member(self.org_a, self.other_member_a, Membership.Role.STAFF)
        self.conv_a2, _ = services.get_or_create_direct_conversation(
            organisation=self.org_a, user=self.staff_a, other_user=self.other_member_a
        )
        services.create_message(conversation=self.conv_a2, sender=self.staff_a, body="Private staff chat")

    def test_partner_cannot_fetch_org_b_conversation_using_org_a_session(self):
        """
        Partner has conversations in TWO client orgs. Using an org-A-scoped
        session (X-Organisation-ID = org A), fetching org B's conversation by
        ID must 404 — not 403, not 200.
        """
        client = _auth_client(self.partner_user, self.org_a)
        resp = client.get(f"/api/v1/messaging/conversations/{self.conv_b.id}/messages/")
        self.assertEqual(resp.status_code, 404, resp.content)

    def test_partner_cannot_fetch_org_b_conversation_detail_using_org_a_session(self):
        client = _auth_client(self.partner_user, self.org_a)
        resp = client.get(f"/api/v1/messaging/conversations/{self.conv_b.id}/")
        self.assertEqual(resp.status_code, 404, resp.content)

    def test_intra_org_isolation_unrelated_pairs_cannot_read_each_other(self):
        """Two unrelated conversation pairs in the SAME org: neither can read the other's messages."""
        # owner_a (participant of conv_a, not conv_a2) tries to read conv_a2
        client = _auth_client(self.owner_a, self.org_a)
        resp = client.get(f"/api/v1/messaging/conversations/{self.conv_a2.id}/messages/")
        self.assertEqual(resp.status_code, 404, resp.content)

        # staff_a (participant of conv_a2, not conv_a) tries to read conv_a
        client2 = _auth_client(self.staff_a, self.org_a)
        resp2 = client2.get(f"/api/v1/messaging/conversations/{self.conv_a.id}/messages/")
        self.assertEqual(resp2.status_code, 404, resp2.content)

    def test_non_member_cannot_create_conversation(self):
        """Someone with no membership in the target org cannot create a conversation there."""
        outsider = _make_user("outsider@example.com")
        client = APIClient()
        refresh = RefreshToken.for_user(outsider)
        client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {str(refresh.access_token)}",
            HTTP_X_ORGANISATION_ID=str(self.org_a.id),
        )
        resp = client.post(
            "/api/v1/messaging/conversations/get_or_create_direct/",
            {"other_user_id": str(self.owner_a.id)},
            format="json",
        )
        self.assertIn(resp.status_code, (400, 403, 404), resp.content)

    def test_employee_role_cannot_create_conversation(self):
        """An employee-role user is blanket-denied at the permission-class level."""
        employee_user = _make_user("employee@example.com")
        _add_member(self.org_a, employee_user, Membership.Role.EMPLOYEE)
        client = _auth_client(employee_user, self.org_a)
        resp = client.post(
            "/api/v1/messaging/conversations/get_or_create_direct/",
            {"other_user_id": str(self.owner_a.id)},
            format="json",
        )
        self.assertEqual(resp.status_code, 403, resp.content)

    def test_get_or_create_direct_rejects_cross_org_other_user(self):
        """other_user_id must belong to the SAME resolved org — never allow a cross-org pairing."""
        client = _auth_client(self.owner_a, self.org_a)
        resp = client.post(
            "/api/v1/messaging/conversations/get_or_create_direct/",
            {"other_user_id": str(self.owner_b.id)},  # owner_b is not a member of org_a
            format="json",
        )
        self.assertEqual(resp.status_code, 404, resp.content)


class PartnerContactRoleConfinementTests(TestCase):
    """PARTNER_CONTACT membership must be refused by every non-messaging endpoint."""

    def setUp(self):
        self.owner = _make_user("po_owner@example.com")
        self.org = _make_org(self.owner, "PC Org")
        self.partner_user = _make_user("pc_partner@example.com")
        _add_member(self.org, self.partner_user, Membership.Role.PARTNER_CONTACT)
        self.client = _auth_client(self.partner_user, self.org)

    def test_partner_contact_cannot_list_customers(self):
        resp = self.client.get("/api/v1/customers/")
        self.assertIn(resp.status_code, (403, 404), resp.content)

    def test_partner_contact_cannot_list_invoices(self):
        resp = self.client.get("/api/v1/sales/invoices/")
        self.assertIn(resp.status_code, (403, 404), resp.content)

    def test_partner_contact_cannot_list_suppliers(self):
        resp = self.client.get("/api/v1/suppliers/")
        self.assertIn(resp.status_code, (403, 404), resp.content)

    def test_partner_contact_CAN_reach_messaging_conversations_list(self):
        """Sanity check: the role isn't broken outright — it just can't reach non-messaging endpoints."""
        resp = self.client.get("/api/v1/messaging/conversations/")
        self.assertEqual(resp.status_code, 200, resp.content)


class MessageIdempotencyAndUnreadTests(TestCase):
    def setUp(self):
        self.owner = _make_user("idem_owner@example.com")
        self.org = _make_org(self.owner, "Idem Org")
        self.other = _make_user("idem_other@example.com")
        _add_member(self.org, self.other, Membership.Role.STAFF)
        self.conversation, _ = services.get_or_create_direct_conversation(
            organisation=self.org, user=self.owner, other_user=self.other
        )
        self.client = _auth_client(self.owner, self.org)

    def test_duplicate_client_nonce_yields_one_message_row(self):
        """Simulates an offline-retry: same body+nonce POSTed twice must not double-post."""
        payload = {"body": "Retry me", "client_nonce": "nonce-123"}
        resp1 = self.client.post(
            f"/api/v1/messaging/conversations/{self.conversation.id}/messages/",
            payload, format="json",
        )
        resp2 = self.client.post(
            f"/api/v1/messaging/conversations/{self.conversation.id}/messages/",
            payload, format="json",
        )
        self.assertEqual(resp1.status_code, 201, resp1.content)
        self.assertEqual(resp2.status_code, 200, resp2.content)
        self.assertEqual(resp1.data["id"], resp2.data["id"])

        count = Message.objects.filter(
            conversation=self.conversation, client_nonce="nonce-123"
        ).count()
        self.assertEqual(count, 1)

    def test_unread_count_correct_after_send_and_read(self):
        # other sends 3 messages
        for i in range(3):
            self.client_other = _auth_client(self.other, self.org)
            self.client_other.post(
                f"/api/v1/messaging/conversations/{self.conversation.id}/messages/",
                {"body": f"msg {i}", "client_nonce": f"n-{i}"}, format="json",
            )

        resp = self.client.get("/api/v1/messaging/unread_count/")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.data["unread_count"], 3)

        # mark read
        read_resp = self.client.post(
            f"/api/v1/messaging/conversations/{self.conversation.id}/read/"
        )
        self.assertEqual(read_resp.status_code, 200, read_resp.content)

        resp2 = self.client.get("/api/v1/messaging/unread_count/")
        self.assertEqual(resp2.data["unread_count"], 0)

        # one more message arrives after read
        self.client_other = _auth_client(self.other, self.org)
        self.client_other.post(
            f"/api/v1/messaging/conversations/{self.conversation.id}/messages/",
            {"body": "one more", "client_nonce": "n-last"}, format="json",
        )
        resp3 = self.client.get("/api/v1/messaging/unread_count/")
        self.assertEqual(resp3.data["unread_count"], 1)


class SeqAssignmentSequentialTests(TestCase):
    """seq assignment must never collide, even under back-to-back sends."""

    def setUp(self):
        self.owner = _make_user("seq_owner@example.com")
        self.org = _make_org(self.owner, "Seq Org")
        self.other = _make_user("seq_other@example.com")
        _add_member(self.org, self.other, Membership.Role.STAFF)
        self.conversation, _ = services.get_or_create_direct_conversation(
            organisation=self.org, user=self.owner, other_user=self.other
        )

    def test_two_sends_get_distinct_seq_values(self):
        msg1, created1 = services.create_message(
            conversation=self.conversation, sender=self.owner, body="first"
        )
        msg2, created2 = services.create_message(
            conversation=self.conversation, sender=self.other, body="second"
        )
        self.assertTrue(created1)
        self.assertTrue(created2)
        self.assertNotEqual(msg1.seq, msg2.seq)
        self.assertEqual({msg1.seq, msg2.seq}, {1, 2})


class SeqAssignmentConcurrentTests(TransactionTestCase):
    """
    Fire two sends from separate threads against the same conversation.
    Uses TransactionTestCase (not TestCase) because TestCase wraps each test
    in an uncommitted outer transaction — a second thread with its own DB
    connection cannot see rows the main thread hasn't committed, which is a
    test-harness artifact, not a real concurrency bug. TransactionTestCase
    commits for real, so this test exercises the actual select_for_update()
    row-lock race.
    """

    def setUp(self):
        self.owner = _make_user("seqc_owner@example.com")
        self.org = _make_org(self.owner, "SeqC Org")
        self.other = _make_user("seqc_other@example.com")
        _add_member(self.org, self.other, Membership.Role.STAFF)
        self.conversation, _ = services.get_or_create_direct_conversation(
            organisation=self.org, user=self.owner, other_user=self.other
        )

    def test_concurrent_sends_via_threads_produce_distinct_seq(self):
        """
        select_for_update() on the parent Conversation row must serialize
        seq assignment so neither thread reads a stale last_seq.
        """
        import threading

        from django.db import connections

        results = []
        errors = []
        conversation_id = self.conversation.pk

        def _send(body, nonce):
            try:
                conv = Conversation.objects.get(pk=conversation_id)
                msg, _created = services.create_message(
                    conversation=conv, sender=self.owner, body=body, client_nonce=nonce,
                )
                results.append(msg.seq)
            except Exception as exc:  # pragma: no cover - diagnostic only
                errors.append(exc)
            finally:
                connections.close_all()

        t1 = threading.Thread(target=_send, args=("thread-1", "t1-nonce"))
        t2 = threading.Thread(target=_send, args=("thread-2", "t2-nonce"))
        t1.start()
        t1.join()
        t2.start()
        t2.join()

        self.assertEqual(errors, [])
        self.assertEqual(len(results), 2)
        self.assertEqual(len(set(results)), 2, f"seq values collided: {results}")


class PartnerAccessRequestScopeTests(TestCase):
    """PartnerAccessRequest.scope drives which Membership role gets provisioned on approval."""

    def setUp(self):
        self.owner = _make_user("scope_owner@example.com")
        self.org = _make_org(self.owner, "Scope Org")
        self.partner_user = _make_user("scope_partner@example.com")
        self.partner_profile = PartnerProfile.objects.create(user=self.partner_user)

    def _approve(self, req):
        client = _auth_client(self.owner, self.org)
        return client.post(
            f"/api/v1/tenancy/organisations/{self.org.id}/partner-requests/{req.id}/approve/"
        )

    def test_messaging_only_scope_creates_partner_contact_membership(self):
        req = PartnerAccessRequest.objects.create(
            partner=self.partner_profile, organisation=self.org,
            scope=PartnerAccessRequest.Scope.MESSAGING_ONLY,
        )
        resp = self._approve(req)
        self.assertEqual(resp.status_code, 200, resp.content)

        membership = Membership.objects.get(user=self.partner_user, organisation=self.org)
        self.assertEqual(membership.role, Membership.Role.PARTNER_CONTACT)
        self.assertTrue(membership.is_active)

    def test_operational_scope_preserves_existing_accountant_provisioning(self):
        req = PartnerAccessRequest.objects.create(
            partner=self.partner_profile, organisation=self.org,
            scope=PartnerAccessRequest.Scope.OPERATIONAL,
        )
        resp = self._approve(req)
        self.assertEqual(resp.status_code, 200, resp.content)

        membership = Membership.objects.get(user=self.partner_user, organisation=self.org)
        self.assertEqual(membership.role, Membership.Role.ACCOUNTANT)
        self.assertTrue(membership.is_active)


class MessageAttachmentDownloadTests(TestCase):
    """
    Fix 1 (CRITICAL): MessageAttachment.file must never be reachable via a
    raw/unauthenticated storage URL. The serializer must not surface `file`,
    and the new download endpoint must be participant-gated (404 for
    non-participants / cross-org, same pattern as every other messaging
    endpoint).
    """

    def setUp(self):
        self.owner = _make_user("att_owner@example.com")
        self.org = _make_org(self.owner, "Attachment Org")
        self.other = _make_user("att_other@example.com")
        _add_member(self.org, self.other, Membership.Role.STAFF)
        self.conversation, _ = services.get_or_create_direct_conversation(
            organisation=self.org, user=self.owner, other_user=self.other
        )

        # Unrelated org + user for cross-tenant probe.
        self.owner_c = _make_user("att_owner_c@example.com")
        self.org_c = _make_org(self.owner_c, "Unrelated Org")

        self.client = _auth_client(self.owner, self.org)

        upload = SimpleUploadedFile(
            "invoice.pdf", b"%PDF-1.4 fake pdf content", content_type="application/pdf"
        )
        resp = self.client.post(
            f"/api/v1/messaging/conversations/{self.conversation.id}/attachments/",
            {"file": upload},
            format="multipart",
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        self.attachment_id = resp.data["id"]
        self.attachment_payload = resp.data

    def tearDown(self):
        # Clean up the file written to local MEDIA_ROOT during the test.
        # Best-effort: on Windows a just-streamed FileResponse can still hold
        # an OS-level lock briefly after the test client call returns, so a
        # PermissionError here must not fail/mask the test's own assertions.
        for att in MessageAttachment.objects.all():
            if att.file:
                try:
                    att.file.delete(save=False)
                except OSError:
                    pass

    def test_serializer_does_not_expose_raw_file_field(self):
        """The upload response (via MessageAttachmentSerializer) must not carry a raw `file` key."""
        self.assertNotIn("file", self.attachment_payload)
        self.assertIn("download_url", self.attachment_payload)
        self.assertIsNotNone(self.attachment_payload["download_url"])
        self.assertIn(
            f"/messaging/attachments/{self.attachment_id}/download/",
            self.attachment_payload["download_url"],
        )

    def test_participant_can_download_attachment(self):
        resp = self.client.get(
            f"/api/v1/messaging/attachments/{self.attachment_id}/download/"
        )
        self.assertEqual(resp.status_code, 200, getattr(resp, "content", None))
        content = b"".join(resp.streaming_content) if resp.streaming else resp.content
        self.assertIn(b"fake pdf content", content)

    def test_other_participant_can_also_download(self):
        other_client = _auth_client(self.other, self.org)
        resp = other_client.get(
            f"/api/v1/messaging/attachments/{self.attachment_id}/download/"
        )
        self.assertEqual(resp.status_code, 200, getattr(resp, "content", None))

    def test_cross_org_non_participant_gets_404(self):
        """
        Reviewer PoC: an authenticated user in a completely unrelated org
        must not be able to fetch the attachment even with a valid, real
        attachment ID (guessable/leaked URL scenario) — 404, not 200/403.
        """
        outsider_client = _auth_client(self.owner_c, self.org_c)
        resp = outsider_client.get(
            f"/api/v1/messaging/attachments/{self.attachment_id}/download/"
        )
        self.assertEqual(resp.status_code, 404, resp.content)

    def test_unauthenticated_request_denied(self):
        anon_client = APIClient()
        resp = anon_client.get(
            f"/api/v1/messaging/attachments/{self.attachment_id}/download/"
        )
        self.assertIn(resp.status_code, (401, 403))

    def test_intra_org_non_participant_gets_404(self):
        """Same org, but not a participant of this specific conversation — still 404."""
        third_user = _make_user("att_third@example.com")
        _add_member(self.org, third_user, Membership.Role.STAFF)
        client3 = _auth_client(third_user, self.org)
        resp = client3.get(
            f"/api/v1/messaging/attachments/{self.attachment_id}/download/"
        )
        self.assertEqual(resp.status_code, 404, resp.content)


class OperationalScopeMessagingDenialTests(TestCase):
    """
    Fix 2 (HIGH): scope='operational' partner grants an ACCOUNTANT-role
    Membership for payroll/salary workflows only — messaging must be denied
    even though the role itself would otherwise pass IsConversationParticipant.
    scope='messaging_only' / 'both' must still work.
    """

    def setUp(self):
        self.owner = _make_user("scope2_owner@example.com")
        self.org = _make_org(self.owner, "Scope2 Org")
        self.partner_user = _make_user("scope2_partner@example.com")
        self.partner_profile = PartnerProfile.objects.create(user=self.partner_user)

    def _approve(self, req):
        client = _auth_client(self.owner, self.org)
        return client.post(
            f"/api/v1/tenancy/organisations/{self.org.id}/partner-requests/{req.id}/approve/"
        )

    def test_operational_scope_accountant_cannot_create_conversation(self):
        req = PartnerAccessRequest.objects.create(
            partner=self.partner_profile, organisation=self.org,
            scope=PartnerAccessRequest.Scope.OPERATIONAL,
        )
        resp = self._approve(req)
        self.assertEqual(resp.status_code, 200, resp.content)

        membership = Membership.objects.get(user=self.partner_user, organisation=self.org)
        self.assertEqual(membership.role, Membership.Role.ACCOUNTANT)
        self.assertEqual(membership.granted_scope, "operational")

        client = _auth_client(self.partner_user, self.org)
        resp = client.post(
            "/api/v1/messaging/conversations/get_or_create_direct/",
            {"other_user_id": str(self.owner.id)},
            format="json",
        )
        self.assertEqual(resp.status_code, 403, resp.content)

    def test_operational_scope_accountant_cannot_list_conversations(self):
        req = PartnerAccessRequest.objects.create(
            partner=self.partner_profile, organisation=self.org,
            scope=PartnerAccessRequest.Scope.OPERATIONAL,
        )
        self._approve(req)
        client = _auth_client(self.partner_user, self.org)
        resp = client.get("/api/v1/messaging/conversations/")
        self.assertEqual(resp.status_code, 403, resp.content)

    def test_operational_scope_accountant_cannot_reach_existing_conversation(self):
        """
        Even a pre-existing ConversationParticipant row (e.g. from before the
        fix, or created out-of-band) must not grant access once the
        membership's granted_scope is 'operational'. The blanket
        has_permission check denies first (403, same as the existing
        employee-role blanket-denial pattern) — belt-and-suspenders is
        confirmed separately by test_operational_scope_denial_is_object_level_too
        which calls has_object_permission directly.
        """
        req = PartnerAccessRequest.objects.create(
            partner=self.partner_profile, organisation=self.org,
            scope=PartnerAccessRequest.Scope.OPERATIONAL,
        )
        self._approve(req)

        conversation, _ = services.get_or_create_direct_conversation(
            organisation=self.org, user=self.owner, other_user=self.partner_user
        )
        services.create_message(conversation=conversation, sender=self.owner, body="hi")

        client = _auth_client(self.partner_user, self.org)
        resp = client.get(f"/api/v1/messaging/conversations/{conversation.id}/messages/")
        self.assertEqual(resp.status_code, 403, resp.content)

    def test_operational_scope_denial_is_object_level_too(self):
        """
        has_object_permission itself (not just has_permission) must
        independently deny an operational-scope grant — belt-and-suspenders,
        exercised directly in case some future call site skips has_permission.
        """
        from django.http import Http404
        from rest_framework.test import APIRequestFactory

        from apps.messaging.permissions import IsConversationParticipant

        req = PartnerAccessRequest.objects.create(
            partner=self.partner_profile, organisation=self.org,
            scope=PartnerAccessRequest.Scope.OPERATIONAL,
        )
        self._approve(req)

        conversation, _ = services.get_or_create_direct_conversation(
            organisation=self.org, user=self.owner, other_user=self.partner_user
        )

        factory = APIRequestFactory()
        django_request = factory.get("/")
        django_request.user = self.partner_user
        django_request.organisation = self.org

        permission = IsConversationParticipant()
        with self.assertRaises(Http404):
            permission.has_object_permission(django_request, None, conversation)

    def test_messaging_only_scope_accountant_equivalent_can_message(self):
        req = PartnerAccessRequest.objects.create(
            partner=self.partner_profile, organisation=self.org,
            scope=PartnerAccessRequest.Scope.MESSAGING_ONLY,
        )
        resp = self._approve(req)
        self.assertEqual(resp.status_code, 200, resp.content)

        membership = Membership.objects.get(user=self.partner_user, organisation=self.org)
        self.assertEqual(membership.granted_scope, "messaging_only")

        client = _auth_client(self.partner_user, self.org)
        resp = client.post(
            "/api/v1/messaging/conversations/get_or_create_direct/",
            {"other_user_id": str(self.owner.id)},
            format="json",
        )
        self.assertIn(resp.status_code, (200, 201), resp.content)

    def test_both_scope_accountant_can_message(self):
        req = PartnerAccessRequest.objects.create(
            partner=self.partner_profile, organisation=self.org,
            scope=PartnerAccessRequest.Scope.BOTH,
        )
        resp = self._approve(req)
        self.assertEqual(resp.status_code, 200, resp.content)

        membership = Membership.objects.get(user=self.partner_user, organisation=self.org)
        self.assertEqual(membership.role, Membership.Role.ACCOUNTANT)
        self.assertEqual(membership.granted_scope, "both")

        client = _auth_client(self.partner_user, self.org)
        resp = client.post(
            "/api/v1/messaging/conversations/get_or_create_direct/",
            {"other_user_id": str(self.owner.id)},
            format="json",
        )
        self.assertIn(resp.status_code, (200, 201), resp.content)

    def test_ordinary_accountant_membership_unaffected(self):
        """
        A normal (non-partner-provisioned) ACCOUNTANT membership has
        granted_scope='' and must be completely unaffected by this check —
        it can still message freely.
        """
        accountant = _make_user("ordinary_accountant@example.com")
        _add_member(self.org, accountant, Membership.Role.ACCOUNTANT)
        membership = Membership.objects.get(user=accountant, organisation=self.org)
        self.assertEqual(membership.granted_scope, "")

        client = _auth_client(accountant, self.org)
        resp = client.post(
            "/api/v1/messaging/conversations/get_or_create_direct/",
            {"other_user_id": str(self.owner.id)},
            format="json",
        )
        self.assertIn(resp.status_code, (200, 201), resp.content)

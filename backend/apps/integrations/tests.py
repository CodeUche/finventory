"""
Tests for Track C — paid integrations marketplace.

Covers:
    - Outbox pattern: DomainEvent written in the SAME transaction as its
      trigger (a rolled-back mutation leaves no DomainEvent row).
    - HMAC signature correctness (sending side, verifiable by recomputing).
    - SSRF defenses reject loopback/link-local/private targets BEFORE any
      HTTP request is attempted.
    - Delivery gating: lapsed subscription -> stays pending, not failed;
      revoked entitlement -> permanently failed, not delivered.
    - API key auth resolves org from the key, ignoring a spoofed
      X-Organisation-ID header.
    - Secret/key-hash/plaintext key never returned after creation.
    - Entitlement gating on webhook-subscription creation.
"""

import socket
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.db import transaction
from django.test import TestCase, TransactionTestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken
from urllib3.connection import HTTPSConnection

from apps.authentication.models import User
from apps.subscriptions.models import IntegrationProduct, OrganisationIntegrationEntitlement, Plan, Subscription
from apps.tenancy.models import Membership
from apps.tenancy.services import OrganisationService

from .models import DomainEvent, OrganisationAPIKey, WebhookDelivery, WebhookSubscription
from .services import (
    IntegrationEventService,
    deliver_event_to_subscription,
    sign_payload,
    _validate_target,
    SSRFValidationError,
)


def _make_user(email):
    return User.objects.create_user(
        email=email, password="TestPass123!",
        first_name="Test", last_name="User", is_verified=True,
    )


def _make_org(user, name="Test Org"):
    return OrganisationService.create_organisation(
        name=name, owner=user, extra={"currency": "NGN", "country": "NG"},
    )


def _add_member(org, user, role=Membership.Role.STAFF):
    """
    get_or_create, not create: OrganisationService.create_organisation already
    grants the owner an OWNER Membership row internally, so calling this with
    the same (org, user) pair (as every test here does, to be explicit about
    the role under test) must not collide with that pre-existing row.
    """
    membership, _ = Membership.objects.update_or_create(
        user=user, organisation=org, defaults={"role": role, "is_active": True},
    )
    return membership


def _auth_client(user, org):
    client = APIClient()
    refresh = RefreshToken.for_user(user)
    client.credentials(
        HTTP_AUTHORIZATION=f"Bearer {str(refresh.access_token)}",
        HTTP_X_ORGANISATION_ID=str(org.id),
    )
    return client


def _make_integration_product(key="webhooks", price="15000.00"):
    return IntegrationProduct.objects.get_or_create(
        key=key, defaults={"name": key.title(), "price": Decimal(price), "is_active": True},
    )[0]


def _grant_entitlement(org, product, status=OrganisationIntegrationEntitlement.Status.ACTIVE):
    return OrganisationIntegrationEntitlement.objects.create(
        organisation=org, product=product, status=status,
    )


class OutboxTransactionTests(TransactionTestCase):
    """
    Proves the outbox guarantee: DomainEvent is written in the SAME
    transaction as its trigger. Uses TransactionTestCase (not TestCase) so a
    real ROLLBACK actually happens rather than being masked by the outer
    test-wrapping transaction TestCase normally uses.

    serialized_rollback=True: TransactionTestCase truncates every table
    (including data-migration-seeded rows like IntegrationProduct) on
    teardown and does NOT re-run data migrations afterward — without this
    flag, any TestCase that runs later in the same session and depends on
    that seed data (e.g. apps.subscriptions.test_payment_engine, which
    get_or_create's against the "zapier" IntegrationProduct row) would find
    it silently gone. serialized_rollback restores the pre-test DB state
    (including seeded rows) after this TransactionTestCase tears down.
    """

    serialized_rollback = True

    def setUp(self):
        self.user = _make_user("owner@example.com")
        self.org = _make_org(self.user)

    def test_rolled_back_transaction_leaves_no_domain_event(self):
        self.assertEqual(DomainEvent.objects.filter(organisation=self.org).count(), 0)

        class _Boom(Exception):
            pass

        with self.assertRaises(_Boom):
            with transaction.atomic():
                IntegrationEventService.emit(self.org, "invoice.created", {"x": 1})
                raise _Boom("simulated failure after emit, inside the same transaction")

        self.assertEqual(
            DomainEvent.objects.filter(organisation=self.org).count(), 0,
            "DomainEvent row survived a rolled-back transaction — outbox guarantee broken.",
        )

    def test_committed_transaction_persists_domain_event(self):
        with transaction.atomic():
            IntegrationEventService.emit(self.org, "invoice.created", {"x": 1})
        self.assertEqual(DomainEvent.objects.filter(organisation=self.org).count(), 1)


class HMACSignatureTests(TestCase):
    def test_signature_is_verifiable_with_known_secret(self):
        secret = "supersecret"
        body = b'{"hello":"world"}'
        signature = sign_payload(secret, body)

        # Recompute independently, mirroring how a receiver would verify.
        import hashlib
        import hmac as hmac_mod

        expected = hmac_mod.new(secret.encode(), msg=body, digestmod=hashlib.sha256).hexdigest()
        self.assertEqual(signature, expected)

    def test_signature_changes_with_different_secret(self):
        body = b'{"a":1}'
        self.assertNotEqual(sign_payload("secret1", body), sign_payload("secret2", body))


class SSRFDefenseTests(TestCase):
    """
    Assert delivery to loopback/link-local/private targets is rejected
    BEFORE any HTTP request is attempted — mock requests.post and assert it
    is never called for these targets.
    """

    def setUp(self):
        self.user = _make_user("owner@example.com")
        self.org = _make_org(self.user)
        self.product = _make_integration_product()
        _grant_entitlement(self.org, self.product)

    def _make_subscription(self, target_url):
        return WebhookSubscription.objects.create(
            organisation=self.org,
            target_url=target_url,
            event_types=["invoice.created"],
            integration_product=self.product,
        )

    def _make_event(self):
        return IntegrationEventService.emit(self.org, "invoice.created", {"x": 1})

    @patch("apps.integrations.services.requests.Session.post")
    def test_localhost_rejected(self, mock_post):
        sub = self._make_subscription("http://localhost/hook")
        event = self._make_event()
        delivery = deliver_event_to_subscription(sub, event)
        mock_post.assert_not_called()
        self.assertIn(delivery.status, (WebhookDelivery.Status.PENDING, WebhookDelivery.Status.FAILED))
        self.assertIn("Rejected target", delivery.last_error)

    @patch("apps.integrations.services.requests.Session.post")
    def test_loopback_ip_rejected(self, mock_post):
        sub = self._make_subscription("http://127.0.0.1/hook")
        event = self._make_event()
        deliver_event_to_subscription(sub, event)
        mock_post.assert_not_called()

    @patch("apps.integrations.services.requests.Session.post")
    def test_link_local_cloud_metadata_rejected(self, mock_post):
        sub = self._make_subscription("http://169.254.169.254/latest/meta-data/")
        event = self._make_event()
        deliver_event_to_subscription(sub, event)
        mock_post.assert_not_called()

    @patch("apps.integrations.services.requests.Session.post")
    def test_private_range_rejected(self, mock_post):
        sub = self._make_subscription("http://10.0.0.5/hook")
        event = self._make_event()
        deliver_event_to_subscription(sub, event)
        mock_post.assert_not_called()

    def test_validate_target_rejects_non_http_scheme(self):
        with self.assertRaises(SSRFValidationError):
            _validate_target("ftp://example.com/hook")

    @patch("apps.integrations.services.requests.Session.post")
    def test_public_target_is_attempted(self, mock_post):
        """A legitimate public-looking hostname (mocked resolution) DOES call requests.post."""
        mock_response = MagicMock(status_code=200)
        mock_post.return_value = mock_response

        with patch("apps.integrations.services.socket.getaddrinfo") as mock_resolve:
            mock_resolve.return_value = [(2, 1, 6, "", ("93.184.216.34", 0))]  # public IP
            sub = self._make_subscription("https://example.com/hook")
            event = self._make_event()
            delivery = deliver_event_to_subscription(sub, event)

        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args.kwargs
        self.assertEqual(call_kwargs.get("allow_redirects"), False)
        self.assertIn("X-Audity-Signature", call_kwargs["headers"])
        self.assertEqual(delivery.status, WebhookDelivery.Status.DELIVERED)


class DeliveryGatingTests(TestCase):
    def setUp(self):
        self.user = _make_user("owner@example.com")
        self.org = _make_org(self.user)
        self.product = _make_integration_product()

    def _make_subscription(self, entitlement_status=OrganisationIntegrationEntitlement.Status.ACTIVE):
        _grant_entitlement(self.org, self.product, status=entitlement_status)
        return WebhookSubscription.objects.create(
            organisation=self.org,
            target_url="https://example.com/hook",
            event_types=["invoice.created"],
            integration_product=self.product,
        )

    @patch("apps.integrations.services.requests.Session.post")
    def test_lapsed_subscription_stays_pending_not_failed(self, mock_post):
        sub = self._make_subscription()
        # Force the org's Subscription into a lapsed state.
        subscription_row = self.org.subscription
        subscription_row.status = Subscription.Status.CANCELED
        subscription_row.save(update_fields=["status"])

        event = IntegrationEventService.emit(self.org, "invoice.created", {"x": 1})
        delivery = deliver_event_to_subscription(sub, event)

        mock_post.assert_not_called()
        self.assertEqual(delivery.status, WebhookDelivery.Status.PENDING)

    @patch("apps.integrations.services.requests.Session.post")
    def test_revoked_entitlement_never_delivers_even_with_active_subscription(self, mock_post):
        sub = self._make_subscription(entitlement_status=OrganisationIntegrationEntitlement.Status.REVOKED)
        # Org subscription itself is active (default from create_organisation's free plan).
        self.assertTrue(self.org.subscription.is_active)

        event = IntegrationEventService.emit(self.org, "invoice.created", {"x": 1})
        delivery = deliver_event_to_subscription(sub, event)

        mock_post.assert_not_called()
        self.assertEqual(delivery.status, WebhookDelivery.Status.FAILED)

    @patch("apps.integrations.services.requests.Session.post")
    def test_never_purchased_entitlement_never_delivers(self, mock_post):
        # No entitlement row at all for this product.
        sub = WebhookSubscription.objects.create(
            organisation=self.org,
            target_url="https://example.com/hook",
            event_types=["invoice.created"],
            integration_product=self.product,
        )
        event = IntegrationEventService.emit(self.org, "invoice.created", {"x": 1})
        delivery = deliver_event_to_subscription(sub, event)

        mock_post.assert_not_called()
        self.assertEqual(delivery.status, WebhookDelivery.Status.FAILED)


class APIKeyAuthTests(TestCase):
    def setUp(self):
        self.user_a = _make_user("owner_a@example.com")
        self.org_a = _make_org(self.user_a, "Org A")
        self.user_b = _make_user("owner_b@example.com")
        self.org_b = _make_org(self.user_b, "Org B")

        plaintext, prefix, key_hash = OrganisationAPIKey.generate_key()
        self.plaintext_key_a = plaintext
        self.api_key_a = OrganisationAPIKey.objects.create(
            organisation=self.org_a, name="Zapier", key_prefix=prefix, key_hash=key_hash,
        )

    def test_org_resolved_from_key_ignores_spoofed_header(self):
        """
        Send a request with the API key for Org A but an X-Organisation-ID
        header claiming Org B — must resolve to Org A, proving the header is
        ignored on this auth path.
        """
        client = APIClient()
        client.credentials(
            HTTP_X_API_KEY=self.plaintext_key_a,
            HTTP_X_ORGANISATION_ID=str(self.org_b.id),  # spoofed
        )
        # Seed one DomainEvent for each org so we can tell which org resolved.
        IntegrationEventService.emit(self.org_a, "invoice.created", {"marker": "org_a"})
        IntegrationEventService.emit(self.org_b, "invoice.created", {"marker": "org_b"})

        response = client.get("/api/v1/integrations/zapier/triggers/invoice.created/")
        self.assertEqual(response.status_code, 200)
        markers = [row["payload"]["marker"] for row in response.json()]
        self.assertEqual(markers, ["org_a"])

    def test_invalid_key_rejected(self):
        client = APIClient()
        client.credentials(HTTP_X_API_KEY="audk_totally_bogus_key")
        response = client.get("/api/v1/integrations/zapier/triggers/invoice.created/")
        self.assertEqual(response.status_code, 401)

    def test_last_used_at_updated_on_successful_auth(self):
        self.assertIsNone(self.api_key_a.last_used_at)
        client = APIClient()
        client.credentials(HTTP_X_API_KEY=self.plaintext_key_a)
        client.get("/api/v1/integrations/zapier/triggers/invoice.created/")
        self.api_key_a.refresh_from_db()
        self.assertIsNotNone(self.api_key_a.last_used_at)


class SecretNeverReturnedTests(TestCase):
    def setUp(self):
        self.user = _make_user("owner@example.com")
        self.org = _make_org(self.user)
        self.product = _make_integration_product()
        _grant_entitlement(self.org, self.product)
        self.client = _auth_client(self.user, self.org)

    def test_webhook_secret_returned_once_on_create_never_on_list(self):
        create_resp = self.client.post(
            "/api/v1/integrations/webhooks/",
            {
                "target_url": "https://example.com/hook",
                "event_types": ["invoice.created"],
                "integration_product": str(self.product.id),
            },
            format="json",
        )
        self.assertEqual(create_resp.status_code, 201, create_resp.content)
        self.assertIn("secret", create_resp.json())
        secret_value = create_resp.json()["secret"]
        self.assertTrue(secret_value)

        list_resp = self.client.get("/api/v1/integrations/webhooks/")
        self.assertEqual(list_resp.status_code, 200)
        body_str = str(list_resp.json())
        self.assertNotIn(secret_value, body_str)
        for row in list_resp.json():
            self.assertNotIn("secret", row)

    def test_api_key_plaintext_returned_once_on_create_never_on_list(self):
        zapier_product = _make_integration_product(key="zapier", price="20000.00")
        _grant_entitlement(self.org, zapier_product)

        create_resp = self.client.post(
            "/api/v1/integrations/api-keys/", {"name": "Zapier"}, format="json",
        )
        self.assertEqual(create_resp.status_code, 201, create_resp.content)
        self.assertIn("key", create_resp.json())
        plaintext_key = create_resp.json()["key"]
        self.assertTrue(plaintext_key.startswith("audk_"))

        list_resp = self.client.get("/api/v1/integrations/api-keys/")
        self.assertEqual(list_resp.status_code, 200)
        body_str = str(list_resp.json())
        self.assertNotIn(plaintext_key, body_str)
        for row in list_resp.json():
            self.assertNotIn("key", row)
            self.assertNotIn("key_hash", row)


class EntitlementGatingTests(TestCase):
    def setUp(self):
        self.user = _make_user("owner@example.com")
        self.org = _make_org(self.user)
        self.product = _make_integration_product()
        self.client = _auth_client(self.user, self.org)

    def test_creating_webhook_for_unpurchased_product_is_rejected(self):
        response = self.client.post(
            "/api/v1/integrations/webhooks/",
            {
                "target_url": "https://example.com/hook",
                "event_types": ["invoice.created"],
                "integration_product": str(self.product.id),
            },
            format="json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertIn("purchase", response.json()["error"].lower())
        self.assertEqual(WebhookSubscription.objects.filter(organisation=self.org).count(), 0)

    def test_creating_webhook_without_integration_product_is_allowed(self):
        """A webhook not tied to a specific paid product (integration_product omitted) is not gated."""
        response = self.client.post(
            "/api/v1/integrations/webhooks/",
            {
                "target_url": "https://example.com/hook",
                "event_types": ["invoice.created"],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.content)

    def test_creating_webhook_with_active_entitlement_succeeds(self):
        _grant_entitlement(self.org, self.product)
        response = self.client.post(
            "/api/v1/integrations/webhooks/",
            {
                "target_url": "https://example.com/hook",
                "event_types": ["invoice.created"],
                "integration_product": str(self.product.id),
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.content)


class WebhookCreationTimeSSRFValidationTests(TestCase):
    """
    SSRF validation must reject unsafe target_url values at CREATION time
    (WebhookSubscriptionSerializer.validate_target_url), not only at
    delivery time. Before this, a private/loopback/metadata target_url was
    accepted with 201 + secret revealed, and the subscription showed
    "Active" — the SSRF rejection only ever surfaced later, if/when someone
    clicked "Send test event". Delivery-time validation
    (deliver_event_to_subscription / _validate_target) is unchanged and
    still runs again on every delivery — this only closes the gap that
    creation itself did no such check.
    """

    def setUp(self):
        self.user = _make_user("owner@example.com")
        self.org = _make_org(self.user)
        self.client = _auth_client(self.user, self.org)

    @staticmethod
    def _scoped_resolver(hostname_to_intercept, fake_result):
        """
        patch("apps.integrations.services.socket.getaddrinfo") replaces
        getaddrinfo on the shared `socket` module object itself (services.py
        does `import socket`, so `services.socket is socket` — modules are
        singletons), which means a blanket mock here leaks process-wide for
        the duration of the `with` block. That's harmless for the existing
        _validate_target-only tests, but these tests go through the full DRF
        view/permission stack, which includes DRF throttling's cache lookup
        — django_redis resolves `localhost` via this SAME socket.getaddrinfo
        to reach Redis. A blanket mock breaks that unrelated DNS lookup and
        surfaces as a flaky 500 with no relation to SSRF validation at all.
        Only intercept the exact hostname under test; delegate everything
        else (redis's `localhost`, etc.) to the real resolver.
        """
        real_getaddrinfo = socket.getaddrinfo

        def _resolver(host, *args, **kwargs):
            if host == hostname_to_intercept:
                return fake_result
            return real_getaddrinfo(host, *args, **kwargs)

        return _resolver

    def test_creating_webhook_with_metadata_target_is_rejected(self):
        resolver = self._scoped_resolver("169.254.169.254", [(2, 1, 6, "", ("169.254.169.254", 0))])
        with patch("apps.integrations.services.socket.getaddrinfo", side_effect=resolver):
            response = self.client.post(
                "/api/v1/integrations/webhooks/",
                {"target_url": "http://169.254.169.254/", "event_types": ["invoice.created"]},
                format="json",
            )
        self.assertEqual(response.status_code, 400, response.content)
        body = response.json()
        message = body["error"]["message"] if isinstance(body.get("error"), dict) else body.get("error")
        self.assertIsInstance(message, str)
        self.assertIn("cannot be used as a webhook target", message)
        self.assertEqual(WebhookSubscription.objects.filter(organisation=self.org).count(), 0)

    def test_creating_webhook_with_loopback_target_is_rejected(self):
        resolver = self._scoped_resolver("localhost", [(2, 1, 6, "", ("127.0.0.1", 0))])
        with patch("apps.integrations.services.socket.getaddrinfo", side_effect=resolver):
            response = self.client.post(
                "/api/v1/integrations/webhooks/",
                {"target_url": "http://localhost/hook", "event_types": ["invoice.created"]},
                format="json",
            )
        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(WebhookSubscription.objects.filter(organisation=self.org).count(), 0)

    def test_creating_webhook_with_private_target_is_rejected(self):
        resolver = self._scoped_resolver("internal.example", [(2, 1, 6, "", ("10.0.0.5", 0))])
        with patch("apps.integrations.services.socket.getaddrinfo", side_effect=resolver):
            response = self.client.post(
                "/api/v1/integrations/webhooks/",
                {"target_url": "http://internal.example/hook", "event_types": ["invoice.created"]},
                format="json",
            )
        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(WebhookSubscription.objects.filter(organisation=self.org).count(), 0)

    def test_creating_webhook_with_public_target_still_succeeds(self):
        resolver = self._scoped_resolver("example.com", [(2, 1, 6, "", ("93.184.216.34", 0))])
        with patch("apps.integrations.services.socket.getaddrinfo", side_effect=resolver):
            response = self.client.post(
                "/api/v1/integrations/webhooks/",
                {"target_url": "https://example.com/hook", "event_types": ["invoice.created"]},
                format="json",
            )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(WebhookSubscription.objects.filter(organisation=self.org).count(), 1)

    def test_zapier_subscribe_with_metadata_target_is_rejected(self):
        """Same creation-time gap in the Zapier REST-Hooks path (ZapierHooksSubscribeView), which
        builds a WebhookSubscription directly rather than through the serializer."""
        plaintext, prefix, key_hash = OrganisationAPIKey.generate_key()
        OrganisationAPIKey.objects.create(
            organisation=self.org, name="Zapier", key_prefix=prefix, key_hash=key_hash,
        )
        api_client = APIClient()
        api_client.credentials(HTTP_X_API_KEY=plaintext)

        resolver = self._scoped_resolver("169.254.169.254", [(2, 1, 6, "", ("169.254.169.254", 0))])
        with patch("apps.integrations.services.socket.getaddrinfo", side_effect=resolver):
            response = api_client.post(
                "/api/v1/integrations/zapier/hooks/subscribe/",
                {"target_url": "http://169.254.169.254/", "event": "invoice.created"},
                format="json",
            )
        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(WebhookSubscription.objects.filter(organisation=self.org).count(), 0)


class WebhookSubscriptionCrossTenantTests(TestCase):
    """Basic tenant-isolation sanity check for the CRUD viewset."""

    def setUp(self):
        self.user_a = _make_user("owner_a@example.com")
        self.org_a = _make_org(self.user_a, "Org A")

        self.user_b = _make_user("owner_b@example.com")
        self.org_b = _make_org(self.user_b, "Org B")

        self.sub_a = WebhookSubscription.objects.create(
            organisation=self.org_a, target_url="https://example.com/a", event_types=["invoice.created"],
        )

    def test_org_b_cannot_see_org_a_webhook(self):
        client_b = _auth_client(self.user_b, self.org_b)
        response = client_b.get("/api/v1/integrations/webhooks/")
        self.assertEqual(response.status_code, 200)
        ids = [row["id"] for row in response.json()["results"]] if isinstance(response.json(), dict) and "results" in response.json() else [row["id"] for row in response.json()]
        self.assertNotIn(str(self.sub_a.id), ids)


class DNSRebindingDefenseTests(TestCase):
    """
    Finding 1 (CRITICAL) proof: _validate_target validates one IP, but
    requests/urllib3 independently re-resolves DNS at TCP-connect time. If
    that second resolution is allowed to influence the actual socket target,
    an attacker can pass validation with a safe public IP on the first
    lookup and rebind to 127.0.0.1 / 169.254.169.254 on the very next one
    (used by the real connect). This test proves the fix: it makes
    socket.getaddrinfo return a DIFFERENT (unsafe) IP on every call after
    the first, then asserts the actual outbound TCP connection
    (urllib3.util.connection.create_connection — the exact call
    HTTPConnection._new_conn makes to open the raw socket, i.e. the real
    connect primitive, not a higher-level requests seam) targets the FIRST
    (validated, safe) IP — never the rebound one — proving the connection is
    pinned rather than DNS being trusted twice.
    """

    def setUp(self):
        self.user = _make_user("owner@example.com")
        self.org = _make_org(self.user)
        self.product = _make_integration_product()
        _grant_entitlement(self.org, self.product)
        self.sub = WebhookSubscription.objects.create(
            organisation=self.org,
            target_url="https://rebinding-attacker.example/hook",
            event_types=["invoice.created"],
            integration_product=self.product,
        )

    def test_tcp_connection_pinned_to_first_validated_ip_not_rebound_ip(self):
        SAFE_IP = "93.184.216.34"  # what validation sees (public, passes all checks)
        REBOUND_IP = "127.0.0.1"  # what a second DNS lookup would return (attacker rebinds here)

        call_count = {"n": 0}

        def rebinding_getaddrinfo(host, *args, **kwargs):
            call_count["n"] += 1
            ip = SAFE_IP if call_count["n"] == 1 else REBOUND_IP
            return [(2, 1, 6, "", (ip, 0))]

        connect_targets = []

        def recording_create_connection(address, *args, **kwargs):
            host, port = address[0], address[1]
            connect_targets.append(host)
            # Refuse to actually dial anywhere — this is a unit test. Raising
            # here is fine: deliver_event_to_subscription catches
            # requests.RequestException and records it as a failed delivery,
            # which does not affect what we're proving (the DIALED address).
            raise OSError("blocked outbound connection in test")

        with patch(
            "apps.integrations.services.socket.getaddrinfo", side_effect=rebinding_getaddrinfo
        ), patch("urllib3.util.connection.create_connection", side_effect=recording_create_connection):
            event = IntegrationEventService.emit(self.org, "invoice.created", {"x": 1})
            deliver_event_to_subscription(self.sub, event)

        self.assertTrue(
            len(connect_targets) >= 1,
            "No TCP connection attempt was recorded — the delivery path never reached the network layer.",
        )
        # Every actual TCP connect attempt must target the IP validated on
        # the FIRST getaddrinfo call, never the rebound IP the (attacker-
        # controlled) second+ lookup would return. This is the crux of the
        # fix: urllib3's own internal DNS re-resolution never gets a chance
        # to run for the connect, because the connection is pinned to the
        # IP handed to it explicitly by _PinnedIPHTTPConnection/_PinnedIPHTTPSConnection.
        for target in connect_targets:
            self.assertEqual(
                target, SAFE_IP,
                f"TCP connection dialed {target!r} instead of the validated IP {SAFE_IP!r} — "
                f"DNS-rebinding SSRF bypass is NOT closed.",
            )
            self.assertNotEqual(
                target, REBOUND_IP,
                "TCP connection dialed the rebound (attacker) IP — DNS-rebinding bypass succeeded.",
            )

    def test_validate_target_returns_pinned_ip_alongside_url(self):
        with patch("apps.integrations.services.socket.getaddrinfo") as mock_resolve:
            mock_resolve.return_value = [(2, 1, 6, "", ("93.184.216.34", 0))]
            url, pinned_ip = _validate_target("https://example.com/hook")
        self.assertEqual(url, "https://example.com/hook")
        self.assertEqual(pinned_ip, "93.184.216.34")

    def test_https_hostname_still_used_for_tls_sni_and_host_header(self):
        """
        The pinned adapter must not break TLS verification/SNI or the Host
        header — those must still be the original hostname, not the pinned
        IP, else legitimate vhost-routed/cert-verified targets would break.
        This proves the connection object's `.host` is restored to the
        original hostname immediately after the socket connect step (which
        is when urllib3 reads self.host for both server_hostname/SNI and the
        Host header), by asserting on the (pinned) connection object state
        directly rather than only inferring it from the socket target.
        """
        from apps.integrations.services import _PinnedIPHTTPSConnection

        conn = _PinnedIPHTTPSConnection(host="example.com", port=443)
        conn._pinned_ip = "93.184.216.34"

        seen_during_connect = {}

        def fake_new_conn(self):
            # Called from inside our overridden _new_conn while self.host is
            # swapped to the pinned IP — capture it to prove the swap
            # actually happened during the connect step.
            seen_during_connect["host_during_connect"] = self.host
            raise OSError("blocked outbound connection in test")

        with patch.object(HTTPSConnection, "_new_conn", fake_new_conn):
            with self.assertRaises(OSError):
                conn._new_conn()

        self.assertEqual(seen_during_connect["host_during_connect"], "93.184.216.34")
        # After _new_conn returns (or raises), host must be restored to the
        # original hostname for TLS SNI / cert verification / Host header.
        self.assertEqual(conn.host, "example.com")


class CGNATRangeRejectionTests(TestCase):
    """Finding 2: 100.64.0.0/10 (RFC 6598 CGNAT) must be rejected same as RFC1918/loopback/link-local."""

    def setUp(self):
        self.user = _make_user("owner@example.com")
        self.org = _make_org(self.user)
        self.product = _make_integration_product()
        _grant_entitlement(self.org, self.product)

    def test_validate_target_rejects_cgnat_address(self):
        with patch("apps.integrations.services.socket.getaddrinfo") as mock_resolve:
            mock_resolve.return_value = [(2, 1, 6, "", ("100.64.0.1", 0))]
            with self.assertRaises(SSRFValidationError):
                _validate_target("https://cgnat-target.example/hook")

    def test_validate_target_rejects_cgnat_upper_bound(self):
        # 100.127.255.255 is the last address in 100.64.0.0/10.
        with patch("apps.integrations.services.socket.getaddrinfo") as mock_resolve:
            mock_resolve.return_value = [(2, 1, 6, "", ("100.127.255.255", 0))]
            with self.assertRaises(SSRFValidationError):
                _validate_target("https://cgnat-target.example/hook")

    def test_validate_target_allows_address_just_outside_cgnat_range(self):
        # 100.128.0.0 is just past the CGNAT block and is a normal public IP.
        with patch("apps.integrations.services.socket.getaddrinfo") as mock_resolve:
            mock_resolve.return_value = [(2, 1, 6, "", ("100.128.0.1", 0))]
            url, pinned_ip = _validate_target("https://just-outside-cgnat.example/hook")
        self.assertEqual(pinned_ip, "100.128.0.1")

    @patch("apps.integrations.services.requests.Session.post")
    def test_delivery_to_cgnat_target_is_rejected_before_any_request(self, mock_post):
        sub = WebhookSubscription.objects.create(
            organisation=self.org,
            target_url="https://cgnat-target.example/hook",
            event_types=["invoice.created"],
            integration_product=self.product,
        )
        event = IntegrationEventService.emit(self.org, "invoice.created", {"x": 1})
        with patch("apps.integrations.services.socket.getaddrinfo") as mock_resolve:
            mock_resolve.return_value = [(2, 1, 6, "", ("100.64.5.5", 0))]
            delivery = deliver_event_to_subscription(sub, event)
        mock_post.assert_not_called()
        self.assertIn("Rejected target", delivery.last_error)


class APIKeyCreationFailsClosedTests(TestCase):
    """Finding 3: missing/inactive 'zapier' IntegrationProduct catalog row must fail CLOSED, not open."""

    def setUp(self):
        self.user = _make_user("owner@example.com")
        self.org = _make_org(self.user)
        self.client = _auth_client(self.user, self.org)

    def test_api_key_creation_rejected_when_zapier_catalog_row_missing(self):
        # The seed migration (0002_seed_integration_products) normally creates
        # this row; simulate it being gone (reverse migration ran, manual
        # deletion, or a fresh env before the migration applies).
        IntegrationProduct.objects.filter(key="zapier").delete()
        self.assertFalse(IntegrationProduct.objects.filter(key="zapier").exists())

        response = self.client.post("/api/v1/integrations/api-keys/", {"name": "Zapier"}, format="json")

        self.assertEqual(response.status_code, 500, response.content)
        self.assertEqual(OrganisationAPIKey.objects.filter(organisation=self.org).count(), 0)

    def test_api_key_creation_rejected_when_zapier_catalog_row_inactive(self):
        IntegrationProduct.objects.filter(key="zapier").update(is_active=False)
        response = self.client.post("/api/v1/integrations/api-keys/", {"name": "Zapier"}, format="json")
        self.assertEqual(response.status_code, 500, response.content)
        self.assertEqual(OrganisationAPIKey.objects.filter(organisation=self.org).count(), 0)

    def test_api_key_creation_succeeds_when_catalog_row_present_and_entitled(self):
        zapier_product = _make_integration_product(key="zapier", price="20000.00")
        _grant_entitlement(self.org, zapier_product)
        response = self.client.post("/api/v1/integrations/api-keys/", {"name": "Zapier"}, format="json")
        self.assertEqual(response.status_code, 201, response.content)

    def test_api_key_creation_rejected_when_catalog_row_present_but_not_entitled(self):
        _make_integration_product(key="zapier", price="20000.00")
        response = self.client.post("/api/v1/integrations/api-keys/", {"name": "Zapier"}, format="json")
        self.assertEqual(response.status_code, 403, response.content)
        self.assertEqual(OrganisationAPIKey.objects.filter(organisation=self.org).count(), 0)


class ZapierHooksSubscribeEntitlementTests(TestCase):
    """
    Finding 4: ZapierHooksSubscribeView must enforce the same per-subscription
    entitlement gating as the dashboard WebhookSubscriptionViewSet.create path
    — both by tagging created subscriptions with integration_product, and by
    rejecting creation outright when the org lacks an ACTIVE Zapier entitlement.
    """

    def setUp(self):
        self.user = _make_user("owner@example.com")
        self.org = _make_org(self.user)
        self.zapier_product = _make_integration_product(key="zapier", price="20000.00")

        plaintext, prefix, key_hash = OrganisationAPIKey.generate_key()
        self.plaintext_key = plaintext
        self.api_key = OrganisationAPIKey.objects.create(
            organisation=self.org, name="Zapier", key_prefix=prefix, key_hash=key_hash,
        )

    def _client(self):
        client = APIClient()
        client.credentials(HTTP_X_API_KEY=self.plaintext_key)
        return client

    def test_subscribe_rejected_without_active_entitlement(self):
        # API key exists (as it could via direct DB seeding/legacy data) but
        # there is no ACTIVE entitlement for zapier on this org.
        response = self._client().post(
            "/api/v1/integrations/zapier/hooks/subscribe/",
            {"target_url": "https://example.com/hook", "event": "invoice.created"},
            format="json",
        )
        self.assertEqual(response.status_code, 403, response.content)
        self.assertEqual(WebhookSubscription.objects.filter(organisation=self.org).count(), 0)

    def test_subscribe_tags_subscription_with_integration_product_when_entitled(self):
        _grant_entitlement(self.org, self.zapier_product)
        response = self._client().post(
            "/api/v1/integrations/zapier/hooks/subscribe/",
            {"target_url": "https://example.com/hook", "event": "invoice.created"},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        sub_id = response.json()["id"]
        sub = WebhookSubscription.objects.get(id=sub_id)
        self.assertEqual(sub.integration_product_id, self.zapier_product.id)

    @patch("apps.integrations.services.requests.Session.post")
    def test_delivery_to_subscribe_created_subscription_blocked_when_entitlement_later_revoked(self, mock_post):
        entitlement = _grant_entitlement(self.org, self.zapier_product)
        response = self._client().post(
            "/api/v1/integrations/zapier/hooks/subscribe/",
            {"target_url": "https://example.com/hook", "event": "invoice.created"},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        sub = WebhookSubscription.objects.get(id=response.json()["id"])

        # Revoke after the fact — same permanent-gate semantics a
        # dashboard-created subscription already gets in deliver_event_to_subscription.
        entitlement.status = OrganisationIntegrationEntitlement.Status.REVOKED
        entitlement.save(update_fields=["status"])

        event = IntegrationEventService.emit(self.org, "invoice.created", {"x": 1})
        delivery = deliver_event_to_subscription(sub, event)

        mock_post.assert_not_called()
        self.assertEqual(delivery.status, WebhookDelivery.Status.FAILED)
        self.assertIn("entitlement", delivery.last_error.lower())

    def test_subscribe_rejected_when_zapier_catalog_row_missing(self):
        # Delete the seeded 'zapier' product entirely to simulate the
        # migration-reversal / fresh-environment scenario from Finding 3.
        IntegrationProduct.objects.filter(key="zapier").delete()
        response = self._client().post(
            "/api/v1/integrations/zapier/hooks/subscribe/",
            {"target_url": "https://example.com/hook", "event": "invoice.created"},
            format="json",
        )
        self.assertEqual(response.status_code, 500, response.content)
        self.assertEqual(WebhookSubscription.objects.filter(organisation=self.org).count(), 0)

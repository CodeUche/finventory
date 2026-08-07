"""
Service layer for the integrations marketplace.

Two responsibilities live here:
    1. IntegrationEventService.emit — the outbox write. Trivial by design: a
       single DomainEvent.objects.create() call, safe to call from inside any
       already-open transaction elsewhere in the codebase.
    2. Webhook delivery — SSRF-validated, HMAC-signed outbound POST, shared by
       both the Celery beat task (apps.integrations.tasks) and the synchronous
       "send test event" API action, so there is exactly one delivery code
       path to keep safe rather than two that can drift apart.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import logging
import socket
from urllib.parse import urlparse

import requests
from django.utils import timezone
from requests.adapters import HTTPAdapter
from urllib3.connection import HTTPConnection, HTTPSConnection
from urllib3.connectionpool import HTTPConnectionPool, HTTPSConnectionPool

from apps.subscriptions.models import OrganisationIntegrationEntitlement
from apps.subscriptions.payment_engine import org_can_receive_integration_delivery

from .models import DomainEvent, WebhookDelivery, WebhookSubscription

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = (5, 5)  # (connect, read) seconds
SIGNATURE_HEADER = "X-Audity-Signature"

# Carrier-Grade NAT / Shared Address Space (RFC 6598). NOT covered by
# ipaddress.IPv4Address.is_private (verify: ipaddress.ip_address("100.64.0.1").is_private
# is False) but used by some cloud providers for internal VPC routing, so it
# can front internal-only services same as RFC1918 space. Checked explicitly
# alongside the built-in private/loopback/link-local/multicast/reserved checks.
_CGNAT_RANGE = ipaddress.ip_network("100.64.0.0/10")


class IntegrationEventService:
    """The outbox write. No side effects beyond the DB row."""

    @staticmethod
    def emit(organisation, event_type: str, payload: dict) -> DomainEvent:
        return DomainEvent.objects.create(
            organisation=organisation,
            event_type=event_type,
            payload=payload,
        )


class SSRFValidationError(Exception):
    """Raised when a webhook target URL resolves to a disallowed address."""


def sign_payload(secret: str, raw_body: bytes) -> str:
    """
    Mirror image of the verification side already established in this
    codebase — apps.payments.providers.paystack.verify_signature and
    apps.payments.views._verify_platform_signature both compute
    hmac.new(secret, raw_body, sha).hexdigest() and hmac.compare_digest it
    against a received header. This is the SENDING side of that same
    convention (sha256, since we control both ends and don't need to match
    Paystack's sha512 choice).
    """
    return hmac.new(secret.encode(), msg=raw_body, digestmod=hashlib.sha256).hexdigest()


def _is_disallowed_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or (ip.version == 4 and ip in _CGNAT_RANGE)
    )


def _validate_target(target_url: str) -> tuple[str, str]:
    """
    SSRF defenses. Resolves the target hostname to its IP(s) BEFORE any
    request is made and rejects private/loopback/link-local/multicast/
    reserved/CGNAT (100.64.0.0/10) ranges, and non-http(s) schemes. ALL
    resolved addresses must be safe, not just the first one, else the
    hostname is rejected outright.

    Returns (original_url, pinned_ip) on success; raises SSRFValidationError
    otherwise. `pinned_ip` is the first address from the validated addrinfo
    list — since every address in that list was just confirmed safe, picking
    any one of them is sound.

    Why a pinned IP is returned at all (DNS-rebinding defense): resolving and
    validating a hostname here is not enough on its own, because `requests`/
    urllib3 performs its OWN independent DNS resolution at TCP-connect time.
    An attacker who controls DNS for their own target hostname can return a
    safe public IP on this lookup (passing validation) and a different,
    unsafe IP (e.g. 127.0.0.1 or the 169.254.169.254 cloud metadata address)
    on the very next lookup, milliseconds later, which is exactly the one
    `requests` would use to connect — defeating the filter entirely.

    The caller (deliver_event_to_subscription) closes this gap by pinning the
    actual TCP connection to `pinned_ip` via a custom HTTPAdapter/urllib3
    connection pool (see _PinnedIPHTTPAdapter below) instead of letting
    urllib3 re-resolve the hostname. The original hostname is still sent as
    the `Host` header and used for TLS SNI/certificate verification, so
    vhost routing and cert validation both still work against the real
    hostname — only the DNS lookup itself is bypassed for the actual
    connection, using the IP already validated above.
    """
    parsed = urlparse(target_url)
    if parsed.scheme not in ("http", "https"):
        raise SSRFValidationError(f"Scheme '{parsed.scheme}' is not allowed.")
    hostname = parsed.hostname
    if not hostname:
        raise SSRFValidationError("Target URL has no hostname.")

    try:
        addrinfo = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise SSRFValidationError(f"Could not resolve hostname: {exc}") from exc

    if not addrinfo:
        raise SSRFValidationError("Could not resolve hostname.")

    validated_ips = []
    for family, _type, _proto, _canon, sockaddr in addrinfo:
        ip_str = sockaddr[0]
        ip = ipaddress.ip_address(ip_str)
        if _is_disallowed_ip(ip):
            raise SSRFValidationError(f"Target resolves to a disallowed address: {ip_str}")
        validated_ips.append(ip_str)

    return target_url, validated_ips[0]


class _PinnedIPHTTPConnection(HTTPConnection):
    """HTTPConnection that connects to a fixed IP regardless of self.host."""

    _pinned_ip: str

    def _new_conn(self):
        original_host = self.host
        try:
            self.host = self._pinned_ip
            return super()._new_conn()
        finally:
            self.host = original_host


class _PinnedIPHTTPSConnection(HTTPSConnection):
    """
    HTTPSConnection that connects (TCP) to a fixed IP but still performs TLS
    SNI/certificate verification against the original hostname. `self.host`
    is what urllib3 uses for the TCP connect target AND (absent an explicit
    server_hostname) for SNI/cert verification, so it's swapped only around
    the raw socket connect and restored immediately after — SNI/verification
    happen later in the TLS handshake using the restored `self.host`.
    """

    _pinned_ip: str

    def _new_conn(self):
        original_host = self.host
        try:
            self.host = self._pinned_ip
            return super()._new_conn()
        finally:
            self.host = original_host


class _PinnedIPHTTPConnectionPool(HTTPConnectionPool):
    ConnectionCls = _PinnedIPHTTPConnection
    # Set post-construction by _PinnedIPHTTPAdapter, NOT passed as an
    # __init__ kwarg — urllib3's PoolManager builds a PoolKey(**request_context)
    # from connection_pool_kw before ever calling the pool constructor, and
    # PoolKey has a fixed set of fields, so a `pinned_ip` kwarg threaded
    # through connection_pool_kw breaks pool-key construction with a
    # TypeError. Attribute assignment sidesteps that entirely.
    _pinned_ip: str | None = None

    def _new_conn(self):
        conn = super()._new_conn()
        conn._pinned_ip = self._pinned_ip
        return conn


class _PinnedIPHTTPSConnectionPool(HTTPSConnectionPool):
    ConnectionCls = _PinnedIPHTTPSConnection
    _pinned_ip: str | None = None

    def _new_conn(self):
        conn = super()._new_conn()
        conn._pinned_ip = self._pinned_ip
        return conn


class _PinnedIPHTTPAdapter(HTTPAdapter):
    """
    requests.adapters.HTTPAdapter subclass that forces the TCP connection for
    a single request to a pre-validated IP address, instead of letting
    urllib3 re-resolve the target hostname via DNS at connect time. This is
    the mechanism that closes the DNS-rebinding gap: no matter what DNS
    answers on a second lookup, the socket this adapter opens is not driven
    by a lookup at all — `host` is monkeypatched on the connection object
    itself, only for the raw socket connect, and restored immediately after
    so TLS SNI / hostname verification (which read `self.host` later in the
    handshake) still see and validate against the real hostname.

    One adapter instance is scoped to exactly one pinned IP and mounted for
    exactly one request (see deliver_event_to_subscription) — it is not
    reused across requests/targets, so there is no risk of an IP pinned for
    one delivery leaking into another.

    Implementation note: `pinned_ip` is deliberately NOT threaded through
    urllib3's connection_pool_kw/PoolKey machinery (see the pool classes
    above) — instead this adapter registers its own pool classes for the
    poolmanager and stamps `_pinned_ip` onto each pool right after urllib3
    creates/returns it, in get_connection_with_tls_context below.
    """

    def __init__(self, pinned_ip: str, *args, **kwargs):
        self._pinned_ip = pinned_ip
        super().__init__(*args, **kwargs)

    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        super().init_poolmanager(connections, maxsize, block=block, **pool_kwargs)
        # Registering these pool classes for their schemes makes urllib3's
        # PoolManager instantiate OUR pinned-IP pools instead of the stock
        # HTTPConnectionPool/HTTPSConnectionPool for this adapter's requests.
        self.poolmanager.pool_classes_by_scheme = {
            "http": _PinnedIPHTTPConnectionPool,
            "https": _PinnedIPHTTPSConnectionPool,
        }

    def get_connection_with_tls_context(self, request, verify, proxies=None, cert=None):
        # cert_verify (inherited, unmodified) still validates certs against
        # the pool's `host` (the original hostname) since only the raw
        # socket connect step is IP-swapped, never `self.host` itself.
        pool = super().get_connection_with_tls_context(request, verify, proxies=proxies, cert=cert)
        pool._pinned_ip = self._pinned_ip
        return pool


def _build_pinned_session(pinned_ip: str) -> requests.Session:
    """
    A fresh, single-use requests.Session with the pinned-IP adapter mounted
    for both schemes. Not shared/pooled across deliveries: each delivery's
    session is scoped to that one delivery's validated IP so an IP pinned
    for one target can never leak into a request for a different target.
    Factored out (rather than inlined) so tests can patch this one seam to
    prove which IP a delivery actually attempted to connect to.
    """
    session = requests.Session()
    adapter = _PinnedIPHTTPAdapter(pinned_ip)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def deliver_event_to_subscription(subscription: WebhookSubscription, event: DomainEvent) -> WebhookDelivery:
    """
    Deliver one event to one subscription, synchronously. Used by both the
    Celery task (deliver_pending_webhooks) and the synchronous "send test
    event" API action — the SAME SSRF-validated path either way.

    Gates checked here (in addition to whatever the caller already checked):
        - org_can_receive_integration_delivery(organisation): a lapsed
          subscription pauses delivery without failing/losing the event —
          the WebhookDelivery row is left/created as 'pending'.
        - subscription.integration_product's entitlement must be ACTIVE if
          one is set; a revoked/never-purchased entitlement never delivers.
    """
    delivery, _ = WebhookDelivery.objects.get_or_create(
        organisation=subscription.organisation,
        subscription=subscription,
        event=event,
    )

    if delivery.status == WebhookDelivery.Status.DELIVERED:
        return delivery

    if not org_can_receive_integration_delivery(subscription.organisation):
        # Subscription lapsed — pause delivery, do NOT mark failed.
        return delivery

    if subscription.integration_product_id is not None:
        is_entitled = OrganisationIntegrationEntitlement.objects.filter(
            organisation=subscription.organisation,
            product_id=subscription.integration_product_id,
            status=OrganisationIntegrationEntitlement.Status.ACTIVE,
        ).exists()
        if not is_entitled:
            # Revoked/never-purchased entitlement — never deliver. This is a
            # permanent gate (not a transient "pending" state) so mark failed
            # rather than retry forever against a webhook that can never fire.
            delivery.status = WebhookDelivery.Status.FAILED
            delivery.last_error = "Integration entitlement is not active."
            delivery.last_attempted_at = timezone.now()
            delivery.save(update_fields=["status", "last_error", "last_attempted_at", "updated_at"])
            return delivery

    if not subscription.is_active:
        return delivery

    body = json.dumps(
        {
            "id": str(event.id),
            "event_type": event.event_type,
            "occurred_at": event.occurred_at.isoformat(),
            "payload": event.payload,
        },
        default=str,
    ).encode("utf-8")

    delivery.attempt_count += 1
    delivery.last_attempted_at = timezone.now()

    try:
        validated_url, pinned_ip = _validate_target(subscription.target_url)
        signature = sign_payload(subscription.secret, body)
        # Pin the TCP connection to the IP that was just validated above —
        # requests/urllib3 would otherwise re-resolve the hostname's DNS
        # independently at connect time, which is the DNS-rebinding gap this
        # adapter closes (see _PinnedIPHTTPAdapter's docstring).
        session = _build_pinned_session(pinned_ip)
        response = session.post(
            validated_url,
            data=body,
            headers={
                "Content-Type": "application/json",
                SIGNATURE_HEADER: signature,
            },
            timeout=REQUEST_TIMEOUT,
            allow_redirects=False,  # never chase redirects — DNS-rebinding SSRF vector
        )
        delivery.last_response_code = response.status_code
        if 200 <= response.status_code < 300:
            delivery.status = WebhookDelivery.Status.DELIVERED
            delivery.last_error = ""
        else:
            delivery.last_error = f"Non-2xx response: {response.status_code}"[:2000]
            if response.status_code < 400 and response.status_code >= 300:
                delivery.last_error = f"Redirect response ({response.status_code}) not followed."[:2000]
    except SSRFValidationError as exc:
        delivery.last_error = f"Rejected target: {exc}"[:2000]
        delivery.last_response_code = None
    except requests.RequestException as exc:
        delivery.last_error = str(exc)[:2000]
        delivery.last_response_code = None

    if delivery.status != WebhookDelivery.Status.DELIVERED:
        if delivery.attempt_count >= WebhookDelivery.MAX_ATTEMPTS:
            delivery.status = WebhookDelivery.Status.FAILED
        else:
            delivery.status = WebhookDelivery.Status.PENDING

    delivery.save(
        update_fields=[
            "status", "attempt_count", "last_attempted_at",
            "last_response_code", "last_error", "updated_at",
        ]
    )
    return delivery

"""
API-level idempotency for financial write endpoints.

Usage in a DRF ViewSet action:

    class InvoiceViewSet(IdempotencyMixin, ...):
        def create(self, request, *args, **kwargs):
            cached, idem_key = self.check_idempotency(request, 'invoice:create')
            if cached is not None:
                return cached
            # ... normal create logic ...
            response = Response(data, status=201)
            self.save_idempotency(idem_key, request.user.id, response)
            return response

The client sends:
    Idempotency-Key: <client-generated UUID or random string, max 128 chars>

On the first call the server processes normally and caches the response.
On a retry with the same key, the cached response is returned immediately.
Keys expire after 24 hours. If no header is sent, idempotency is skipped.
"""

import json
import logging
from datetime import timedelta

from django.utils import timezone
from rest_framework.response import Response

logger = logging.getLogger(__name__)

_TTL_HOURS = 24
_MAX_KEY_LEN = 128


class IdempotencyMixin:
    """
    Mixin for DRF ViewSets that adds Idempotency-Key support.

    Provides check_idempotency() and save_idempotency() helpers.
    The action string (e.g. 'invoice:create') namespaces keys so the same
    client key can safely be used for different operations.
    """

    def check_idempotency(self, request, action: str):
        """
        Returns (cached_response, scoped_key).

        If a valid cached response exists for this key, cached_response is
        a Response object and scoped_key is None (caller should return immediately).

        If no cache hit, cached_response is None and scoped_key is the namespaced
        key string to pass to save_idempotency() after generating the response.

        If no Idempotency-Key header was sent, both are None (idempotency skipped).
        """
        raw_key = request.headers.get("Idempotency-Key", "").strip()
        if not raw_key:
            return None, None

        if len(raw_key) > _MAX_KEY_LEN:
            return None, None

        scoped_key = f"{action}:{raw_key}"
        now = timezone.now()

        try:
            from apps.core.models import IdempotencyRecord
            record = IdempotencyRecord.objects.get(
                user_id=request.user.id,
                key=scoped_key,
                expires_at__gt=now,
            )
            data = json.loads(record.response_body)
            logger.debug(
                "Idempotency hit: user=%s action=%s key=%s status=%s",
                request.user.id, action, raw_key[:20], record.response_status,
            )
            return Response(data, status=record.response_status), None
        except Exception:
            return None, scoped_key

    def save_idempotency(self, scoped_key, user_id, response: Response):
        """
        Persist the response for this idempotency key.

        Silently ignores errors so a cache failure never breaks the main flow.
        scoped_key is what check_idempotency() returned; if None, this is a no-op.
        """
        if not scoped_key:
            return
        try:
            from apps.core.models import IdempotencyRecord
            expires_at = timezone.now() + timedelta(hours=_TTL_HOURS)
            body = json.dumps(response.data)
            IdempotencyRecord.objects.update_or_create(
                user_id=user_id,
                key=scoped_key,
                defaults={
                    "response_body": body,
                    "response_status": response.status_code,
                    "expires_at": expires_at,
                },
            )
        except Exception:
            logger.debug("Failed to save idempotency record for key=%s", scoped_key, exc_info=True)

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

import hashlib
import json
import logging
from datetime import timedelta

from django.core.serializers.json import DjangoJSONEncoder
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.response import Response

logger = logging.getLogger(__name__)

_TTL_HOURS = 24
_CLAIM_SECONDS = 300         # how long an unfinished request holds its key (released on completion/failure)
_MAX_KEY_LEN = 128


def scoped_key(action: str, org_id, raw_key: str) -> str:
    """The stored key: namespaced by action AND organisation, so one user working
    in two businesses can never get one business's response replayed in the other."""
    return f"{action}:{org_id}:{raw_key}"


def _body_hash(request) -> str:
    try:
        payload = json.dumps(request.data, sort_keys=True, default=str)
    except Exception:
        payload = ""
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _conflict(message):
    return Response({"error": message}, status=409)


class IdempotencyMixin:
    """
    Mixin for DRF ViewSets that adds Idempotency-Key support.

    check_idempotency(request, action, claim=False) returns (cached_response, key).
      * a finished request with the same key and the same body: its response is
        replayed;
      * the same key with a DIFFERENT body: 409 (a key is for one request only);
      * with claim=True the key is reserved before any work starts, so a second
        copy arriving while the first is still running gets 409 instead of
        making a second sale. The reservation lasts 5 minutes; the view calls
        release_idempotency() when the attempt fails so a corrected retry with the
        same key can go through, and save_idempotency() stores the result on success.

    The key is scoped to user + action + organisation. No header = skipped.
    """

    def check_idempotency(self, request, action: str, claim: bool = False):
        raw_key = request.headers.get("Idempotency-Key", "").strip()
        if not raw_key or len(raw_key) > _MAX_KEY_LEN:
            return None, None

        org = getattr(request, "organisation", None)
        key = scoped_key(action, getattr(org, "id", ""), raw_key)
        body_hash = _body_hash(request)
        self._idem_body_hash = body_hash
        now = timezone.now()

        try:
            from apps.core.models import IdempotencyRecord
            record = IdempotencyRecord.objects.filter(user_id=request.user.id, key=key).first()
            if record is not None and record.expires_at <= now:
                record.delete()
                record = None
            if record is not None:
                if record.response_status == 0:
                    return _conflict("This request is already being processed. Wait a moment before retrying."), None
                payload = json.loads(record.response_body)
                if isinstance(payload, dict) and payload.get("__idem__"):
                    if payload.get("hash") != body_hash:
                        return _conflict("This Idempotency-Key was already used for a different request."), None
                    data = payload.get("data")
                else:                       # a record saved before keys carried a body hash
                    data = payload
                return Response(data, status=record.response_status), None
            if claim:
                try:
                    with transaction.atomic():
                        IdempotencyRecord.objects.create(
                            user_id=request.user.id, key=key, response_body="", response_status=0,
                            expires_at=now + timedelta(seconds=_CLAIM_SECONDS),
                        )
                except IntegrityError:
                    return _conflict("This request is already being processed. Wait a moment before retrying."), None
        except Exception:
            logger.debug("Idempotency lookup failed for key=%s", key, exc_info=True)
        return None, key

    def release_idempotency(self, key, user_id):
        """Free a reserved key after a failed attempt (finished records are kept)."""
        if not key:
            return
        try:
            from apps.core.models import IdempotencyRecord
            IdempotencyRecord.objects.filter(user_id=user_id, key=key, response_status=0).delete()
        except Exception:
            logger.debug("Could not release idempotency key=%s", key, exc_info=True)

    def save_idempotency(self, scoped_key_value, user_id, response: Response):
        """Persist the response for this key (replaces the reservation, if any)."""
        if not scoped_key_value:
            return
        try:
            from apps.core.models import IdempotencyRecord
            body = json.dumps(
                {"__idem__": True, "hash": getattr(self, "_idem_body_hash", ""), "data": response.data},
                cls=DjangoJSONEncoder,
            )
            IdempotencyRecord.objects.update_or_create(
                user_id=user_id,
                key=scoped_key_value,
                defaults={
                    "response_body": body,
                    "response_status": response.status_code,
                    "expires_at": timezone.now() + timedelta(hours=_TTL_HOURS),
                },
            )
        except Exception:
            logger.debug("Failed to save idempotency record for key=%s", scoped_key_value, exc_info=True)

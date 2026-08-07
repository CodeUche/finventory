from rest_framework import serializers

from apps.subscriptions.models import IntegrationProduct

from .models import DomainEvent, OrganisationAPIKey, WebhookDelivery, WebhookSubscription
from .services import SSRFValidationError, _validate_target


class IntegrationProductSerializer(serializers.ModelSerializer):
    """
    Read-only catalog listing for the frontend marketplace page. Adds
    `entitlement_status` (annotated by the view per-request — see
    views.IntegrationProductListView) so the UI can show "Purchased" /
    "Purchase" without a second round trip.
    """

    entitlement_status = serializers.SerializerMethodField()

    class Meta:
        model = IntegrationProduct
        fields = ["id", "key", "name", "description", "price", "is_active", "entitlement_status"]
        read_only_fields = fields

    def get_entitlement_status(self, obj):
        # Populated by the view via a dict passed in context — avoids an N+1
        # entitlement lookup per product row.
        statuses = self.context.get("entitlement_statuses", {})
        return statuses.get(obj.id)


class WebhookSubscriptionSerializer(serializers.ModelSerializer):
    """List/retrieve serializer — deliberately excludes `secret`. Never returned again after creation."""

    class Meta:
        model = WebhookSubscription
        fields = [
            "id", "target_url", "event_types", "is_active",
            "integration_product", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_event_types(self, value):
        if not isinstance(value, list) or not value:
            raise serializers.ValidationError("event_types must be a non-empty list.")
        valid = {choice[0] for choice in DomainEvent.EVENT_TYPES}
        invalid = [v for v in value if v not in valid]
        if invalid:
            raise serializers.ValidationError(f"Unknown event_type(s): {invalid}")
        return value

    def validate_target_url(self, value):
        """
        Reject SSRF-unsafe targets (private/loopback/link-local/multicast/
        reserved/CGNAT ranges, unresolvable hosts, non-http(s) schemes) at
        creation time, not just at delivery time. Reuses the exact same
        _validate_target resolve-and-check logic that
        deliver_event_to_subscription already applies (see services.py) — no
        duplicated disallowed-IP logic here.

        This is a genuine live DNS resolution inside request validation
        (same cost the delivery path already pays), which is the deliberate
        tradeoff: catching the SSRF payload at the moment it's submitted,
        with a clear 400 the user actually sees, instead of only ever
        surfacing on a later "send test event" click. It does NOT return the
        pinned IP anywhere the caller can observe — only the URL passes
        through, and delivery-time validation (which owns the DNS-rebinding
        pinned-IP defense) is unchanged and still runs again on every
        delivery attempt.
        """
        try:
            _validate_target(value)
        except SSRFValidationError as exc:
            raise serializers.ValidationError(
                f"This URL cannot be used as a webhook target: {exc}"
            ) from exc
        return value


class WebhookSubscriptionCreateResponseSerializer(WebhookSubscriptionSerializer):
    """Create-only response — includes `secret` exactly once."""

    class Meta(WebhookSubscriptionSerializer.Meta):
        fields = WebhookSubscriptionSerializer.Meta.fields + ["secret"]


class WebhookDeliverySerializer(serializers.ModelSerializer):
    event_type = serializers.CharField(source="event.event_type", read_only=True)

    class Meta:
        model = WebhookDelivery
        fields = [
            "id", "subscription", "event", "event_type", "status", "attempt_count",
            "last_attempted_at", "last_response_code", "last_error", "created_at",
        ]
        read_only_fields = fields


class DomainEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = DomainEvent
        fields = ["id", "event_type", "payload", "occurred_at"]
        read_only_fields = fields


class OrganisationAPIKeySerializer(serializers.ModelSerializer):
    """List/retrieve serializer — never includes key_hash or plaintext key."""

    class Meta:
        model = OrganisationAPIKey
        fields = ["id", "name", "key_prefix", "is_active", "created_at", "last_used_at"]
        read_only_fields = fields


class OrganisationAPIKeyCreateResponseSerializer(OrganisationAPIKeySerializer):
    """Create-only response — includes the plaintext key exactly once."""

    key = serializers.CharField(read_only=True)

    class Meta(OrganisationAPIKeySerializer.Meta):
        fields = OrganisationAPIKeySerializer.Meta.fields + ["key"]

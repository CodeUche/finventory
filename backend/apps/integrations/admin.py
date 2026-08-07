from django.contrib import admin

from .models import DomainEvent, OrganisationAPIKey, WebhookDelivery, WebhookSubscription


@admin.register(DomainEvent)
class DomainEventAdmin(admin.ModelAdmin):
    list_display = ("event_type", "organisation", "occurred_at")
    list_filter = ("event_type",)
    search_fields = ("organisation__name",)
    readonly_fields = [f.name for f in DomainEvent._meta.fields]


@admin.register(WebhookSubscription)
class WebhookSubscriptionAdmin(admin.ModelAdmin):
    list_display = ("target_url", "organisation", "is_active", "integration_product", "created_at")
    list_filter = ("is_active",)
    search_fields = ("target_url", "organisation__name")
    exclude = ("secret",)


@admin.register(WebhookDelivery)
class WebhookDeliveryAdmin(admin.ModelAdmin):
    list_display = ("subscription", "event", "status", "attempt_count", "last_attempted_at")
    list_filter = ("status",)


@admin.register(OrganisationAPIKey)
class OrganisationAPIKeyAdmin(admin.ModelAdmin):
    list_display = ("name", "key_prefix", "organisation", "is_active", "last_used_at")
    exclude = ("key_hash",)

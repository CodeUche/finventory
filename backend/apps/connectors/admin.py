from django.contrib import admin

from .models import ConnectorAddonSubscription, ConnectorConnection, ConnectorEventDelivery


@admin.register(ConnectorConnection)
class ConnectorConnectionAdmin(admin.ModelAdmin):
    list_display = ("connector_key", "organisation", "status", "billing_mode", "external_account_label", "connected_at")
    list_filter = ("connector_key", "status", "billing_mode")
    search_fields = ("organisation__name", "external_account_label", "nango_connection_id")
    readonly_fields = ("nango_connection_id", "pending_session_token")


@admin.register(ConnectorAddonSubscription)
class ConnectorAddonSubscriptionAdmin(admin.ModelAdmin):
    list_display = ("connector_key", "organisation", "status", "interval", "amount", "current_period_end")
    list_filter = ("connector_key", "status", "interval")
    search_fields = ("organisation__name",)


@admin.register(ConnectorEventDelivery)
class ConnectorEventDeliveryAdmin(admin.ModelAdmin):
    list_display = ("connection", "event", "status", "attempt_count", "last_attempted_at")
    list_filter = ("status",)

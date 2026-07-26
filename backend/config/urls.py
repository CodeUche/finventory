"""
Root URL configuration for Finventory.

All API routes are versioned under /api/v1/.
OpenAPI schema is served at /api/schema/ (admin only — IsAdminUser enforced).
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)
from rest_framework.permissions import IsAdminUser

from apps.core.views import HealthCheckView

api_v1_urlpatterns = [
    # Health check (no auth required - used by load balancers)
    path("health/", HealthCheckView.as_view(), name="health-check"),
    # Authentication
    path("auth/", include("apps.authentication.urls")),
    # Tenancy / Organisations
    path("tenancy/", include("apps.tenancy.urls")),
    # Subscriptions
    path("subscriptions/", include("apps.subscriptions.urls")),
    # Inventory
    path("inventory/", include("apps.inventory.urls")),
    # Suppliers
    path("suppliers/", include("apps.suppliers.urls")),
    # Purchase Orders
    path("purchases/", include("apps.purchases.urls")),
    # Sales
    path("sales/", include("apps.sales.urls")),
    # Customers
    path("customers/", include("apps.customers.urls")),
    # Credit Management
    path("credits/", include("apps.credits.urls")),
    # Expenses & Income
    path("expenses/", include("apps.expenses.urls")),
    # Tax Engine
    path("tax/", include("apps.tax.urls")),
    # Reports & Analytics
    path("reports/", include("apps.reports.urls")),
    # Quotes
    path("quotes/", include("apps.quotes.urls")),
    # Bills (Supplier Bills / AP)
    path("bills/", include("apps.bills.urls")),
    # Accounting (Chart of Accounts, Journal Entries, Fixed Assets)
    path("accounting/", include("apps.accounting.urls")),
    # Payroll
    path("payroll/", include("apps.payroll.urls")),
    # Payment Gateways
    path("payments/", include("apps.payments.urls")),
    # Budgets
    path("budgets/", include("apps.budgets.urls")),
    # AI Financial Assistant
    path("ai/", include("apps.ai.urls")),
    # FIRS E-Invoicing (DigiTax) — config, submission log, webhook receiver
    path("einvoicing/", include("apps.einvoicing.urls")),
    path("helpdesk/", include("apps.helpdesk.urls")),
    path("pos/", include("apps.pos.urls")),
]

_admin_only = [IsAdminUser]

urlpatterns = []

# Only include Prometheus metrics if the package is installed
try:
    import django_prometheus  # noqa: F401
    from django.urls import path as _path, include as _include
    urlpatterns += [_path("", _include("django_prometheus.urls"))]
except ImportError:
    pass

urlpatterns += [
    # Prometheus metrics endpoint (/metrics) — scraped by Prometheus for Grafana.
    # SECURITY: this is unauthenticated by design (Prometheus needs raw access).
    # In production, restrict it at the network/proxy layer (allow only the
    # Prometheus host) or behind a private network — do not expose it publicly.
    # Obfuscated admin path — set ADMIN_URL env var in production
    path(settings.ADMIN_URL, admin.site.urls),
    path("api/v1/", include(api_v1_urlpatterns)),
    # OpenAPI documentation — restricted to Django admin/staff users only
    path("api/schema/", SpectacularAPIView.as_view(permission_classes=_admin_only), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema", permission_classes=_admin_only), name="swagger-ui"),
    path("api/redoc/", SpectacularRedocView.as_view(url_name="schema", permission_classes=_admin_only), name="redoc"),
]

if settings.DEBUG:
    try:
        import debug_toolbar
        urlpatterns = [path("__debug__/", include(debug_toolbar.urls))] + urlpatterns
    except ImportError:
        pass

# Serve user-uploaded media files in all environments.
# In production this is handled by Django directly; configure S3/R2 via USE_S3=True
# for persistent storage (Railway filesystem is ephemeral and wiped on redeploy).
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

# Platform admin API (superusers only) + Audit log (owner/admin/superuser)
from apps.core.admin_views import AuditLogView, PlatformStatsView, PlatformUsersView, PlatformUserDetailView
from apps.core.import_views import ImportProductsView, ImportCustomersView, ImportAccountsView, ImportTemplateView, SuggestColumnMappingView
urlpatterns += [
    path('api/v1/audit-log/', AuditLogView.as_view(), name='audit-log'),
    path('api/v1/platform/stats/', PlatformStatsView.as_view(), name='platform-stats'),
    path('api/v1/platform/users/', PlatformUsersView.as_view(), name='platform-users'),
    path('api/v1/platform/users/<uuid:pk>/', PlatformUserDetailView.as_view(), name='platform-user-detail'),
    # CSV bulk import
    path('api/v1/import/products/', ImportProductsView.as_view(), name='import-products'),
    path('api/v1/import/customers/', ImportCustomersView.as_view(), name='import-customers'),
    path('api/v1/import/accounts/', ImportAccountsView.as_view(), name='import-accounts'),
    path('api/v1/import/template/<str:entity>/', ImportTemplateView.as_view(), name='import-template'),
    path('api/v1/import/suggest-mapping/', SuggestColumnMappingView.as_view(), name='import-suggest-mapping'),
]

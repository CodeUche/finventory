from django.urls import include, path
from rest_framework.routers import DefaultRouter
from .views import InvoiceViewSet, RecurringInvoiceViewSet

router = DefaultRouter()
router.register("invoices", InvoiceViewSet, basename="invoice")
router.register("recurring", RecurringInvoiceViewSet, basename="recurring-invoice")
urlpatterns = [path("", include(router.urls))]

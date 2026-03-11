from django.urls import include, path
from rest_framework.routers import DefaultRouter
from .views import InvoiceFolderViewSet, InvoiceViewSet, RecurringInvoiceViewSet, SaleReturnViewSet

router = DefaultRouter()
router.register("folders", InvoiceFolderViewSet, basename="invoice-folder")
router.register("invoices", InvoiceViewSet, basename="invoice")
router.register("recurring", RecurringInvoiceViewSet, basename="recurring-invoice")
router.register("returns", SaleReturnViewSet, basename="sale-return")
urlpatterns = [path("", include(router.urls))]

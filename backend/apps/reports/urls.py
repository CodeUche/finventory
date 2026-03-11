from django.urls import path
from .views import (
    ARAgingView,
    CashFlowView,
    ExpenseBreakdownView,
    InventoryValuationView,
    ProfitAndLossView,
    SalesSummaryView,
    TopCustomersView,
    TopProductsView,
    VATSummaryView,
)

urlpatterns = [
    path("sales/", SalesSummaryView.as_view(), name="report-sales"),
    path("top-products/", TopProductsView.as_view(), name="report-top-products"),
    path("top-customers/", TopCustomersView.as_view(), name="report-top-customers"),
    path("pnl/", ProfitAndLossView.as_view(), name="report-pnl"),
    path("expenses/", ExpenseBreakdownView.as_view(), name="report-expenses"),
    path("inventory/", InventoryValuationView.as_view(), name="report-inventory"),
    path("cash-flow/", CashFlowView.as_view(), name="report-cash-flow"),
    path("ar-aging/", ARAgingView.as_view(), name="report-ar-aging"),
    path("vat-summary/", VATSummaryView.as_view(), name="report-vat-summary"),
]

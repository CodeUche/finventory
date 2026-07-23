from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    AccountViewSet, AccountSubTypeViewSet, JournalEntryViewSet, FixedAssetViewSet, FinancialPeriodViewSet,
    BankReconciliationViewSet, AccountMappingView, AccountMappingSuggestionsView,
    GLHealthView, GLHealthRetryView, GLHealthBulkRetryView,
)

router = DefaultRouter()
router.register('accounts', AccountViewSet, basename='account')
router.register('account-sub-types', AccountSubTypeViewSet, basename='account-sub-type')
router.register('journal', JournalEntryViewSet, basename='journal')
router.register('assets', FixedAssetViewSet, basename='asset')
router.register('periods', FinancialPeriodViewSet, basename='period')
router.register('reconciliations', BankReconciliationViewSet, basename='reconciliation')

urlpatterns = [
    path('', include(router.urls)),
    path('account-mapping/', AccountMappingView.as_view(), name='account-mapping'),
    path('account-mapping/suggestions/', AccountMappingSuggestionsView.as_view(), name='account-mapping-suggestions'),
    path('gl-health/', GLHealthView.as_view(), name='gl-health'),
    path('gl-health/retry-all/', GLHealthBulkRetryView.as_view(), name='gl-health-retry-all'),
    path('gl-health/<str:model_type>/<str:object_id>/retry/', GLHealthRetryView.as_view(), name='gl-health-retry'),
]

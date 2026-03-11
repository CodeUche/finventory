from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import AccountViewSet, JournalEntryViewSet, FixedAssetViewSet, FinancialPeriodViewSet, BankReconciliationViewSet

router = DefaultRouter()
router.register('accounts', AccountViewSet, basename='account')
router.register('journal', JournalEntryViewSet, basename='journal')
router.register('assets', FixedAssetViewSet, basename='asset')
router.register('periods', FinancialPeriodViewSet, basename='period')
router.register('reconciliations', BankReconciliationViewSet, basename='reconciliation')

urlpatterns = [path('', include(router.urls))]

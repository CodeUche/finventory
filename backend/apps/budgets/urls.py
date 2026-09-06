from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import BudgetViewSet, BudgetPeriodViewSet, BudgetAllocationViewSet

router = DefaultRouter()
# `periods` and `allocations` MUST be registered before the empty-prefix ''
# Budget registration — DefaultRouter walks its registry in registration
# order when resolving a URL, and an empty-prefix ModelViewSet's detail
# route (^(?P<pk>[^/.]+)/$) would otherwise greedily match /budgets/periods/
# as /budgets/{pk="periods"}/ before the more specific /budgets/periods/
# registration ever gets a chance.
router.register('periods', BudgetPeriodViewSet, basename='budget-period')
router.register('allocations', BudgetAllocationViewSet, basename='budget-allocation')
router.register('', BudgetViewSet, basename='budget')
urlpatterns = [path('', include(router.urls))]

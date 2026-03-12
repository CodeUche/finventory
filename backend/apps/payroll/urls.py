from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import EmployeeViewSet, EmployeeDocumentViewSet, EmployeePenaltyViewSet, EmployeeLoanViewSet, PayrollRunViewSet

router = DefaultRouter()
router.register('employees', EmployeeViewSet, basename='employee')
router.register('documents', EmployeeDocumentViewSet, basename='employee-document')
router.register('penalties', EmployeePenaltyViewSet, basename='employee-penalty')
router.register('loans', EmployeeLoanViewSet, basename='employee-loan')
router.register('runs', PayrollRunViewSet, basename='payroll-run')
urlpatterns = [path('', include(router.urls))]

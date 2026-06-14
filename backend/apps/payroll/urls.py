from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    AttendanceViewSet, BonusViewSet, EmployeeDocumentViewSet,
    EmployeeLoanViewSet, EmployeePenaltyViewSet, EmployeeTaxProfileViewSet,
    EmployeeViewSet, PAYERemittanceViewSet, PayrollRunViewSet,
)

router = DefaultRouter()
router.register('employees', EmployeeViewSet, basename='employee')
router.register('documents', EmployeeDocumentViewSet, basename='employee-document')
router.register('penalties', EmployeePenaltyViewSet, basename='employee-penalty')
router.register('loans', EmployeeLoanViewSet, basename='employee-loan')
router.register('runs', PayrollRunViewSet, basename='payroll-run')
router.register('bonuses', BonusViewSet, basename='employee-bonus')
router.register('attendance', AttendanceViewSet, basename='employee-attendance')
router.register('tax-profiles', EmployeeTaxProfileViewSet, basename='employee-tax-profile')
router.register('paye-remittances', PAYERemittanceViewSet, basename='paye-remittance')

urlpatterns = [path('', include(router.urls))]

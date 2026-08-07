from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .ess_views import (
    MeAdvanceViewSet, MeAttendanceView, MeBenefitView, MeDocumentViewSet,
    MeLeaveBalanceView, MeLeaveRequestViewSet, MeLeaveTypeView, MeLoanView,
    MePayslipViewSet, MeProfileView, MeSummaryView,
)
from .views import (
    AdvancePolicyViewSet, AdvanceRequestViewSet, AttendanceViewSet, BenefitPlanViewSet,
    BonusViewSet, CompensationRecordViewSet, EmployeeBenefitViewSet,
    EmployeeDocumentViewSet, EmployeeLoanViewSet, EmployeePenaltyViewSet,
    EmployeeTaxProfileViewSet, EmployeeViewSet, HRAnalyticsViewSet,
    LeaveBalanceViewSet, LeaveCarryForwardViewSet, LeaveRequestViewSet,
    LeaveTypeViewSet, OffboardingCaseViewSet, OffboardingChecklistTemplateViewSet,
    PayrollAdjustmentViewSet, PayrollRunViewSet, PayrollSettingsViewSet,
    PublicHolidayViewSet, StatutoryRemittanceViewSet, TaxAuthorityViewSet,
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
# HR module
router.register('tax-authorities', TaxAuthorityViewSet, basename='tax-authority')
router.register('remittances', StatutoryRemittanceViewSet, basename='statutory-remittance')
router.register('compensation', CompensationRecordViewSet, basename='compensation-record')
router.register('adjustments', PayrollAdjustmentViewSet, basename='payroll-adjustment')
router.register('settings', PayrollSettingsViewSet, basename='payroll-settings')
router.register('leave-types', LeaveTypeViewSet, basename='leave-type')
router.register('leave-balances', LeaveBalanceViewSet, basename='leave-balance')
router.register('leave-requests', LeaveRequestViewSet, basename='leave-request')
router.register('leave-carry-forward', LeaveCarryForwardViewSet, basename='leave-carry-forward')
router.register('public-holidays', PublicHolidayViewSet, basename='public-holiday')
router.register('benefit-plans', BenefitPlanViewSet, basename='benefit-plan')
router.register('employee-benefits', EmployeeBenefitViewSet, basename='employee-benefit')
router.register('advances', AdvanceRequestViewSet, basename='advance-request')
router.register('advance-policy', AdvancePolicyViewSet, basename='advance-policy')
# Offboarding (A.3)
router.register('offboarding-cases', OffboardingCaseViewSet, basename='offboarding-case')
router.register('offboarding-checklist-templates', OffboardingChecklistTemplateViewSet, basename='offboarding-checklist-template')
# HR Analytics (A.6)
router.register('hr-analytics', HRAnalyticsViewSet, basename='hr-analytics')

# Employee self-service portal — mounted separately at /api/v1/me/
ess_router = DefaultRouter()
ess_router.register('payslips', MePayslipViewSet, basename='me-payslip')
ess_router.register('leave-requests', MeLeaveRequestViewSet, basename='me-leave-request')
ess_router.register('documents', MeDocumentViewSet, basename='me-document')
ess_router.register('advances', MeAdvanceViewSet, basename='me-advance')

ess_urlpatterns = [
    path('summary/', MeSummaryView.as_view(), name='me-summary'),
    path('profile/', MeProfileView.as_view(), name='me-profile'),
    path('leave-balances/', MeLeaveBalanceView.as_view(), name='me-leave-balances'),
    path('leave-types/', MeLeaveTypeView.as_view(), name='me-leave-types'),
    path('loans/', MeLoanView.as_view(), name='me-loans'),
    path('benefits/', MeBenefitView.as_view(), name='me-benefits'),
    path('attendance/', MeAttendanceView.as_view(), name='me-attendance'),
    path('', include(ess_router.urls)),
]

urlpatterns = [path('', include(router.urls))]

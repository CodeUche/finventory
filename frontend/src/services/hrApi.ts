/**
 * Track A HR API client — new endpoints only.
 *
 * Deliberately kept out of services/api.ts (which is off-limits for this
 * build) and imports the shared axios instance from there instead. Follows
 * the same call shape as payrollApi/essApi in api.ts.
 */
import { api } from './api'

/**
 * payrollApi.uploadDocument() in api.ts is typed to a fixed field set
 * (employee, name, document_type) and that file is off-limits for edits, so
 * document-expiry uploads go through this local multipart helper instead —
 * it posts to the same /payroll/documents/ endpoint EmployeeDocumentViewSet
 * already exposes, just with the extra expiry_date field.
 */
async function uploadDocumentWithExpiry(
  file: File,
  fields: { employee: string; name: string; document_type: string; expiry_date?: string },
) {
  const form = new FormData()
  form.append('file', file)
  form.append('employee', fields.employee)
  form.append('name', fields.name)
  form.append('document_type', fields.document_type)
  if (fields.expiry_date) form.append('expiry_date', fields.expiry_date)
  return api.post('/payroll/documents/', form, { headers: { 'Content-Type': 'multipart/form-data' } })
}

export const hrApi = {
  uploadDocumentWithExpiry,

  // ── Public holidays (A.1) ────────────────────────────────────────────────
  publicHolidays: (year?: number) => api.get('/payroll/public-holidays/', { params: { year } }),
  createPublicHoliday: (data: object) => api.post('/payroll/public-holidays/', data),
  updatePublicHoliday: (id: string, data: object) => api.patch(`/payroll/public-holidays/${id}/`, data),
  deletePublicHoliday: (id: string) => api.delete(`/payroll/public-holidays/${id}/`),
  seedPublicHolidays: (year: number) => api.post('/payroll/public-holidays/seed/', { year }),

  // ── Leave carry-forward (A.1) ────────────────────────────────────────────
  carryForwardPreview: (year: number) =>
    api.get('/payroll/leave-carry-forward/preview/', { params: { year } }),
  carryForwardApply: (priorYear: number, newYear: number) =>
    api.post('/payroll/leave-carry-forward/apply/', { prior_year: priorYear, new_year: newYear }),

  // ── Team coverage (A.1) ──────────────────────────────────────────────────
  teamCoverage: (employeeId: string, startDate: string, endDate: string) =>
    api.get('/payroll/leave-requests/team_coverage/', {
      params: { employee: employeeId, start_date: startDate, end_date: endDate },
    }),

  // ── Leave encashment (A.1) ───────────────────────────────────────────────
  requestEncashment: (data: { employee: string; leave_type: string; days: string | number; reason?: string }) =>
    api.post('/payroll/adjustments/request_encashment/', data),

  // ── Document expiry + lifecycle alerts (A.2) ─────────────────────────────
  expiringDocuments: (withinDays = 30) =>
    api.get('/payroll/documents/expiring/', { params: { within_days: withinDays } }),
  lifecycleAlerts: (withinDays = 30) =>
    api.get('/payroll/employees/lifecycle_alerts/', { params: { within_days: withinDays } }),

  // ── Offboarding (A.3) ─────────────────────────────────────────────────────
  offboardingCases: (params?: object) => api.get('/payroll/offboarding-cases/', { params }),
  offboardingCase: (id: string) => api.get(`/payroll/offboarding-cases/${id}/`),
  createOffboardingCase: (data: {
    employee: string; reason: string; last_working_day: string;
    notice_period_days?: number; notes?: string;
  }) => api.post('/payroll/offboarding-cases/', data),
  clearChecklistItem: (caseId: string, itemId: string) =>
    api.post(`/payroll/offboarding-cases/${caseId}/clear-item/${itemId}/`),
  runFinalSettlement: (caseId: string) =>
    api.post(`/payroll/offboarding-cases/${caseId}/run_final_settlement/`),
  completeOffboarding: (caseId: string) =>
    api.post(`/payroll/offboarding-cases/${caseId}/complete/`),
  saveExitInterview: (caseId: string, data: object) =>
    api.patch(`/payroll/offboarding-cases/${caseId}/exit_interview/`, data),
  offboardingChecklistTemplates: () => api.get('/payroll/offboarding-checklist-templates/'),

  // ── Payroll settings additions (gratuity, 13th-month basis) ──────────────
  settings: () => api.get('/payroll/settings/current/'),
  saveSettings: (data: object) => api.patch('/payroll/settings/current/', data),

  // ── Payroll register + annual PAYE reconciliation (A.4) ──────────────────
  payrollRegister: (year: number) => api.get('/payroll/runs/register/', { params: { year } }),
  annualPayeReconciliation: (year: number) =>
    api.get('/payroll/runs/annual_paye_reconciliation/', { params: { year } }),

  // ── Server-rendered payslip PDF + async email (A.5) ───────────────────────
  downloadPayslipPdf: (runId: string, employeeId: string) =>
    api.get(`/payroll/runs/${runId}/payslip-pdf/${employeeId}/`, { responseType: 'blob' }),
  sendPayslipsServerRendered: (runId: string, employeeIds?: string[]) =>
    api.post(`/payroll/runs/${runId}/send_payslips_server_rendered/`, { employee_ids: employeeIds }),

  // ── HR Analytics (A.6) ────────────────────────────────────────────────────
  headcountTurnover: (year: number) =>
    api.get('/payroll/hr-analytics/headcount_turnover/', { params: { year } }),
  costByDepartment: (year?: number, month?: number) =>
    api.get('/payroll/hr-analytics/cost_by_department/', { params: { year, month } }),
  absenceSummary: (year?: number, month?: number) =>
    api.get('/payroll/hr-analytics/absence_summary/', { params: { year, month } }),
  tenureDemographics: () => api.get('/payroll/hr-analytics/tenure_demographics/'),
}

/**
 * ESS portal additions — payslip PDF download + document upload.
 * Mirrors essApi's convention of resolving the caller's own Employee record
 * server-side; no employee id is ever sent from the client.
 */
export const hrEssApi = {
  downloadPayslipPdf: (payslipId: string) =>
    api.get(`/me/payslips/${payslipId}/pdf/`, { responseType: 'blob' }),
  uploadDocument: (file: File, fields: { document_type: string; name?: string; expiry_date?: string }) => {
    const form = new FormData()
    form.append('file', file)
    form.append('document_type', fields.document_type)
    if (fields.name) form.append('name', fields.name)
    if (fields.expiry_date) form.append('expiry_date', fields.expiry_date)
    return api.post('/me/documents/', form, { headers: { 'Content-Type': 'multipart/form-data' } })
  },
}

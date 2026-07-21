import { useEffect, useState, useCallback } from 'react'
import { confirmDialog } from '@/lib/dialog'
import { useDataRefresh } from '@/hooks/useDataRefresh'
import {
  ChevronDown, ChevronUp, Banknote, Loader2, ExternalLink, Send, CheckCircle,
  XCircle, AlertTriangle, Building2, CreditCard, RotateCcw, Download, Clock,
  Users, TrendingUp, RefreshCw, Plus, Trash2, Calendar, Gift, X, Shield,
} from 'lucide-react'
import toast from 'react-hot-toast'
import { openExternal } from '@/lib/openExternal'
import { payrollApi, bypassNextGets } from '@/services/api'
import { formatCurrency, formatDate } from '@/lib/utils'
import AmountInput from '@/components/AmountInput'
import { saveBlobFile } from '@/lib/saveBlobFile'
import type { PayrollRun, PAYERemittance, EmployeeTaxProfile } from '@/types'
import DateInput from '@/components/DateInput'
import YearFilter from '@/components/YearFilter'
import ExportButton from '@/components/ExportButton'
import { useAuthStore } from '@/store/authStore'

// ─── Types ────────────────────────────────────────────────────────────────────

interface TransferResult {
  employee: string
  name: string
  status: 'queued' | 'initiated' | 'skipped' | 'failed'
  account?: string
  bank?: string
  amount?: number
  reason?: string
  transfer_code?: string
  reference?: string
}

interface Employee {
  id: string
  employee_id: string
  first_name: string
  last_name: string
  department: string
  gross_salary: string
  is_active: boolean
}

interface AttendanceRecord {
  id: string
  employee: string
  employee_name: string
  date: string
  status: string
  clock_in: string | null
  clock_out: string | null
  overtime_hours: string
  notes: string
}

interface Bonus {
  id: string
  employee: string
  employee_name: string
  amount: string
  bonus_type: string
  reason: string
  period_year: number
  period_month: number
  status: string
}

type PageTab = 'runs' | 'attendance' | 'bonuses' | 'paye'

// ─── Constants ────────────────────────────────────────────────────────────────

const MONTHS = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
]

const STATUS_BADGE: Record<string, string> = {
  draft: 'badge-slate', processing: 'badge-yellow', approved: 'badge-blue', paid: 'badge-green',
}

const TRANSFER_STATUS_ICON = {
  initiated: <CheckCircle size={11} className="text-emerald-400" />,
  success: <CheckCircle size={11} className="text-emerald-400" />,
  failed: <XCircle size={11} className="text-red-400" />,
  skipped: <XCircle size={11} className="text-amber-400" />,
  pending: <Clock size={11} className="text-slate-400" />,
}

const ATTENDANCE_STATUSES = [
  { value: 'present', label: 'Present', color: 'text-emerald-400' },
  { value: 'absent', label: 'Absent', color: 'text-red-400' },
  { value: 'half_day', label: 'Half Day', color: 'text-amber-400' },
  { value: 'leave', label: 'Leave', color: 'text-blue-400' },
  { value: 'holiday', label: 'Holiday', color: 'text-purple-400' },
]

const BONUS_TYPES = [
  { value: 'performance', label: 'Performance' },
  { value: 'signing', label: 'Signing' },
  { value: 'annual', label: 'Annual' },
  { value: 'referral', label: 'Referral' },
  { value: 'other', label: 'Other' },
]

// ─── PFAs ─────────────────────────────────────────────────────────────────────

const PFAS = [
  { name: 'ARM Pension Managers', portal: 'https://www.armpension.com' },
  { name: 'Crusader Sterling Pensions', portal: 'https://www.crusadersterling.com' },
  { name: 'FCMB Pensions', portal: 'https://www.fcmbpensions.com' },
  { name: 'Fidelity Pension Managers', portal: 'https://www.fidelitypension.com.ng' },
  { name: 'Leadway Pensure', portal: 'https://www.leadwaypensure.com' },
  { name: 'Meristem Pensions', portal: 'https://www.meristempensions.com' },
  { name: 'NLPC Pension Fund Administrators', portal: 'https://www.nlpcpfa.com' },
  { name: 'PAL Pensions', portal: 'https://www.palpensions.com' },
  { name: 'Premium Pension', portal: 'https://www.premiumpension.com' },
  { name: 'Radix Pension Managers', portal: 'https://www.radixpension.com' },
  { name: 'Sigma Pensions', portal: 'https://www.sigmapensions.com' },
  { name: 'Stanbic IBTC Pension Managers', portal: 'https://www.stanbicibtcpension.com' },
  { name: 'Veritas Glanvills Pensions', portal: 'https://www.vgpensions.com' },
  { name: 'AXA Mansard Pensions', portal: 'https://www.axamansard.com' },
  { name: 'NUPEMCO', portal: 'https://www.nupemco.com' },
  { name: 'First Guarantee Pension', portal: 'https://www.firstguaranteepension.com' },
  { name: 'OAK Pensions', portal: 'https://www.oakpensions.com' },
  { name: 'Trustfund Pensions', portal: 'https://www.trustfundpensions.com' },
]

const openLink = (url: string) => openExternal(url)

const STATUTORY_ITEMS = (pensionProvider: string, run: PayrollRun) => {
  const pfa = PFAS.find((p) => p.name === pensionProvider) ?? null
  return [
    {
      key: 'paye', label: 'FIRS PAYE Tax', amount: run.total_paye,
      color: 'text-red-400',
      portal: 'https://taxpromax.firs.gov.ng/', portalLabel: 'TaxPro MAX',
      deadline: 'Remit by the 10th of the following month',
      bankDetails: {
        bank: 'Any commercial bank (FIRS Collect)',
        account: 'Generate payment reference via TaxPro MAX portal',
        instruction: 'Log in to TaxPro MAX → File PAYE returns → Generate payment reference → Pay at any bank or online',
      },
    },
    {
      key: 'pension_emp', label: 'Pension (Employee 8%)', amount: run.total_pension_employee,
      color: 'text-orange-400',
      portal: pfa?.portal ?? 'https://www.pencom.gov.ng', portalLabel: pfa?.name ?? 'PENCOM',
      deadline: 'Remit within 7 days of salary payment',
      bankDetails: {
        bank: pfa?.name ?? 'Select your PFA below',
        account: pfa ? `Contact ${pfa.name} for employer remittance schedule` : 'Set your PFA from the dropdown',
        instruction: pfa ? `Log in to ${pfa.name} employer portal to generate remittance schedule` : 'Select your PFA from the dropdown to see payment details',
      },
    },
    {
      key: 'pension_er', label: 'Pension (Employer 10%)', amount: run.total_pension_employer,
      color: 'text-yellow-400',
      portal: pfa?.portal ?? 'https://www.pencom.gov.ng', portalLabel: pfa?.name ?? 'PENCOM',
      deadline: 'Remit alongside employee contribution within 7 days',
      bankDetails: {
        bank: pfa?.name ?? 'Select your PFA below',
        account: pfa ? `Same PFA as employee — ${pfa.name}` : 'Set your PFA from the dropdown',
        instruction: pfa ? `Employer contribution remitted to same PFA — ${pfa.name}` : 'Select PFA first',
      },
    },
    {
      key: 'nhf', label: 'NHF (2.5%)', amount: run.total_nhf,
      color: 'text-blue-400',
      portal: 'https://eportal.fmbn.gov.ng/', portalLabel: 'FMBN e-Portal',
      deadline: 'Remit by the 10th of the following month',
      bankDetails: {
        bank: 'Federal Mortgage Bank of Nigeria (FMBN)',
        account: 'Use FMBN e-Portal to generate NHF remittance schedule',
        instruction: 'Log in to eportal.fmbn.gov.ng → Employer → NHF Remittance → Generate schedule → Pay via bank',
      },
    },
    {
      key: 'nsitf', label: 'NSITF (1%)', amount: run.total_nsitf,
      color: 'text-purple-400',
      portal: 'https://portal.nsitf.gov.ng/', portalLabel: 'NSITF Portal',
      deadline: 'Remit monthly — penalty applies for late payment',
      bankDetails: {
        bank: 'Nigeria Social Insurance Trust Fund (NSITF)',
        account: 'Register on NSITF portal and generate monthly contribution',
        instruction: 'Log in to portal.nsitf.gov.ng → Employer → Monthly Contribution → Pay online or via bank',
      },
    },
  ]
}

// ─── Main Component ───────────────────────────────────────────────────────────

export default function PayrollPage() {
  const { user, organisation } = useAuthStore()
  const isOwnerOrAdmin = user?.is_superuser || ['owner', 'admin'].includes((user as any)?.role ?? '')

  const now = new Date()
  const [pageTab, setPageTab] = useState<PageTab>('runs')
  const [selectedYear, setSelectedYear] = useState(now.getFullYear())
  const [selectedMonth, setSelectedMonth] = useState(now.getMonth() + 1)

  // ── Runs state ──────────────────────────────────────────────────────────────
  const [runs, setRuns] = useState<PayrollRun[]>([])
  const [loadingRuns, setLoadingRuns] = useState(true)
  const [expandedRun, setExpandedRun] = useState<string | null>(null)
  const [running, setRunning] = useState(false)
  const [submittingId, setSubmittingId] = useState<string | null>(null)
  const [approvingId, setApprovingId] = useState<string | null>(null)
  // Approver picker modal
  const [approverPickerId, setApproverPickerId] = useState<string | null>(null)
  const [approvers, setApprovers] = useState<{ id: string; name: string; email: string; role: string }[]>([])
  const [selectedApproverId, setSelectedApproverId] = useState<string>('')
  const [loadingApprovers, setLoadingApprovers] = useState(false)
  const [markPayId, setMarkPayId] = useState<string | null>(null)
  const [paymentDate, setPaymentDate] = useState(now.toISOString().split('T')[0])
  const [initiatingTransfer, setInitiatingTransfer] = useState(false)
  const [retrying, setRetrying] = useState(false)
  const [transferResults, setTransferResults] = useState<TransferResult[] | null>(null)
  const [archiveYear, setArchiveYear] = useState<number | null>(null)
  const [pensionProvider, setPensionProvider] = useState(organisation?.pension_provider ?? '')
  const [activePaymentKey, setActivePaymentKey] = useState<string | null>(null)
  const [exportingBankFile, setExportingBankFile] = useState<string | null>(null)

  // ── PAYE Remittance state ────────────────────────────────────────────────────
  const [payeRemittances, setPayeRemittances] = useState<PAYERemittance[]>([])
  const [loadingPaye, setLoadingPaye] = useState(false)
  const [showPayeRemitModal, setShowPayeRemitModal] = useState(false)
  const [remittingPayeId, setRemittingPayeId] = useState<string | null>(null)
  const [payeRemitForm, setPayeRemitForm] = useState({ reference: '', amount_paid: '', notes: '' })
  const [savingPayeRemit, setSavingPayeRemit] = useState(false)

  // ── Employee Tax Profile state ────────────────────────────────────────────────
  const [showTaxProfileModal, setShowTaxProfileModal] = useState(false)
  const [taxProfileEmployee, setTaxProfileEmployee] = useState<Employee | null>(null)
  const [taxProfile, setTaxProfile] = useState<EmployeeTaxProfile | null>(null)
  const [taxProfileForm, setTaxProfileForm] = useState({ nhf_enrolled: true, voluntary_pension: '0', life_assurance_premium: '0', paye_exempt: false, notes: '' })
  const [loadingTaxProfile, setLoadingTaxProfile] = useState(false)
  const [savingTaxProfile, setSavingTaxProfile] = useState(false)

  // ── Employees ───────────────────────────────────────────────────────────────
  const [employees, setEmployees] = useState<Employee[]>([])

  // ── Attendance state ────────────────────────────────────────────────────────
  const [attendanceRecords, setAttendanceRecords] = useState<AttendanceRecord[]>([])
  const [loadingAtt, setLoadingAtt] = useState(false)
  const [showAttModal, setShowAttModal] = useState(false)
  const [attForm, setAttForm] = useState({
    employee: '', date: now.toISOString().split('T')[0],
    status: 'present', clock_in: '', clock_out: '', overtime_hours: '0', notes: '',
  })
  const [savingAtt, setSavingAtt] = useState(false)
  const [showBulkAttModal, setShowBulkAttModal] = useState(false)
  const [bulkAttStatus, setBulkAttStatus] = useState('present')
  const [bulkAttDate, setBulkAttDate] = useState(now.toISOString().split('T')[0])
  const [bulkAttOvertime, setBulkAttOvertime] = useState('0')
  const [savingBulk, setSavingBulk] = useState(false)

  // ── Bonus state ─────────────────────────────────────────────────────────────
  const [bonuses, setBonuses] = useState<Bonus[]>([])
  const [loadingBonuses, setLoadingBonuses] = useState(false)
  const [selectedPayslip, setSelectedPayslip] = useState<import('@/types').PayslipLine | null>(null)
  const [showBonusModal, setShowBonusModal] = useState(false)
  const [bonusForm, setBonusForm] = useState({
    employee: '', amount: '', bonus_type: 'performance', reason: '',
    period_year: now.getFullYear(), period_month: now.getMonth() + 1,
  })
  const [savingBonus, setSavingBonus] = useState(false)

  // ── Data loaders ────────────────────────────────────────────────────────────

  const loadRuns = useCallback(async () => {
    setLoadingRuns(true)
    try {
      const { data } = await payrollApi.runs()
      setRuns(data.results ?? data)
    } catch { toast.error('Failed to load payroll runs') }
    finally { setLoadingRuns(false) }
  }, [])

  const loadEmployees = useCallback(async () => {
    if (employees.length > 0) return
    try {
      const { data } = await payrollApi.employees({ is_active: true, page_size: 200 })
      setEmployees(data.results ?? data)
    } catch { /* non-critical */ }
  }, [employees.length])

  const loadAttendance = useCallback(async () => {
    setLoadingAtt(true)
    try {
      const { data } = await payrollApi.attendance({ year: selectedYear, month: selectedMonth, page_size: 500 })
      setAttendanceRecords(data.results ?? data)
    } catch { toast.error('Failed to load attendance') }
    finally { setLoadingAtt(false) }
  }, [selectedYear, selectedMonth])

  const loadBonuses = useCallback(async () => {
    setLoadingBonuses(true)
    try {
      const { data } = await payrollApi.bonuses({ period_year: selectedYear, period_month: selectedMonth, page_size: 200 })
      setBonuses(data.results ?? data)
    } catch { toast.error('Failed to load bonuses') }
    finally { setLoadingBonuses(false) }
  }, [selectedYear, selectedMonth])

  useEffect(() => { loadRuns() }, [loadRuns])
  useDataRefresh(loadRuns)

  const loadPayeRemittances = async () => {
    setLoadingPaye(true)
    try { const { data } = await payrollApi.payeRemittances(); setPayeRemittances(data.results ?? data) }
    catch { toast.error('Failed to load PAYE remittances') }
    finally { setLoadingPaye(false) }
  }

  const openTaxProfile = async (emp: Employee) => {
    setTaxProfileEmployee(emp)
    setLoadingTaxProfile(true)
    setShowTaxProfileModal(true)
    try {
      const { data } = await payrollApi.taxProfile(emp.id)
      setTaxProfile(data)
      setTaxProfileForm({ nhf_enrolled: data.nhf_enrolled, voluntary_pension: data.voluntary_pension, life_assurance_premium: data.life_assurance_premium, paye_exempt: data.paye_exempt, notes: data.notes })
    } catch {
      setTaxProfile(null)
      setTaxProfileForm({ nhf_enrolled: true, voluntary_pension: '0', life_assurance_premium: '0', paye_exempt: false, notes: '' })
    }
    finally { setLoadingTaxProfile(false) }
  }

  const handleSaveTaxProfile = async () => {
    if (!taxProfileEmployee) return
    setSavingTaxProfile(true)
    try {
      await payrollApi.saveTaxProfile(taxProfileEmployee.id, {
        nhf_enrolled: taxProfileForm.nhf_enrolled,
        voluntary_pension: parseFloat(taxProfileForm.voluntary_pension) || 0,
        life_assurance_premium: parseFloat(taxProfileForm.life_assurance_premium) || 0,
        paye_exempt: taxProfileForm.paye_exempt,
        notes: taxProfileForm.notes,
      })
      toast.success('Tax profile saved')
      setShowTaxProfileModal(false)
    } catch { toast.error('Failed to save tax profile') }
    finally { setSavingTaxProfile(false) }
  }

  useEffect(() => {
    if (pageTab === 'attendance') { loadEmployees(); loadAttendance() }
    if (pageTab === 'bonuses') { loadEmployees(); loadBonuses() }
    if (pageTab === 'paye') { loadPayeRemittances(); loadEmployees() }
  }, [pageTab, selectedYear, selectedMonth, loadEmployees, loadAttendance, loadBonuses])

  // ── Runs handlers ────────────────────────────────────────────────────────────

  const handleRunPayroll = async () => {
    if (!(await confirmDialog(`Run payroll for ${MONTHS[selectedMonth - 1]} ${selectedYear}?\n\nThis will compute salaries, bonuses, attendance deductions and statutory deductions for all active employees.`))) return
    setRunning(true)
    try {
      await payrollApi.runPayroll({ period_year: selectedYear, period_month: selectedMonth })
      toast.success('Payroll computed — review and submit for approval')
      loadRuns()
    } catch (err: any) {
      const msg = err?.response?.data?.error ?? 'Failed to run payroll'
      toast.error(typeof msg === 'string' ? msg : 'Failed to run payroll')
    } finally { setRunning(false) }
  }

  const openApproverPicker = async (id: string) => {
    setApproverPickerId(id)
    setSelectedApproverId('')
    setLoadingApprovers(true)
    try {
      const { data } = await payrollApi.eligibleApprovers()
      setApprovers(data)
    } catch { setApprovers([]) }
    finally { setLoadingApprovers(false) }
  }

  const handleSubmitForApproval = async () => {
    if (!approverPickerId) return
    setSubmittingId(approverPickerId)
    setApproverPickerId(null)
    try {
      await payrollApi.submitForApproval(approverPickerId, selectedApproverId ? { approver_id: selectedApproverId } : {})
      const approver = approvers.find((a) => a.id === selectedApproverId)
      toast.success(approver ? `Submitted to ${approver.name} for approval` : 'Submitted for approval')
      loadRuns()
    } catch { toast.error('Failed to submit for approval') }
    finally { setSubmittingId(null) }
  }

  const handleApprove = async (id: string) => {
    if (!(await confirmDialog('Approve and finalise this payroll run?'))) return
    setApprovingId(id)
    try {
      await payrollApi.approvePayroll(id)
      toast.success('Payroll approved — GL journal posted')
      loadRuns()
    } catch (err: any) {
      const msg = err?.response?.data?.error ?? 'Failed to approve'
      toast.error(typeof msg === 'string' ? msg : 'Failed to approve')
    } finally { setApprovingId(null) }
  }

  const handleMarkPaid = async () => {
    if (!markPayId) return
    try {
      await payrollApi.markPaid(markPayId, { payment_date: paymentDate })
      toast.success('Payroll marked as paid')
      setMarkPayId(null); setTransferResults(null)
      loadRuns()
    } catch { toast.error('Failed to mark as paid') }
  }

  const handleInitiateTransfers = async () => {
    if (!markPayId) return
    setInitiatingTransfer(true); setTransferResults(null)
    try {
      const { data } = await payrollApi.initiateTransfers(markPayId)
      setTransferResults(data.results ?? [])
      if (data.success) {
        toast.success(data.message ?? 'Transfers initiated')
        await payrollApi.markPaid(markPayId, { payment_date: paymentDate })
        loadRuns()
      } else {
        toast.error(data.error ?? 'Transfer failed')
      }
    } catch (err: any) {
      toast.error(err?.response?.data?.error ?? 'Transfer initiation failed')
    } finally { setInitiatingTransfer(false) }
  }

  const handleRetryFailed = async () => {
    if (!markPayId) return
    setRetrying(true)
    try {
      const { data } = await payrollApi.retryFailed(markPayId)
      setTransferResults(data.results ?? [])
      toast.success(`${data.retried ?? 0} transfer(s) retried`)
      loadRuns()
    } catch (err: any) {
      toast.error(err?.response?.data?.error ?? 'Retry failed')
    } finally { setRetrying(false) }
  }

  const handleExportBankFile = async (id: string) => {
    setExportingBankFile(id)
    try {
      const resp = await payrollApi.exportBankFile(id)
      const run = runs.find(r => r.id === id)
      const period = run ? `-${run.period_year}${String(run.period_month).padStart(2, '0')}` : ''
      saveBlobFile(resp.data, `${run?.run_number ?? 'payroll'}-bank-payment${period}.xlsx`)
      toast.success('Bank transfer file downloaded')
    } catch { toast.error('Failed to export') }
    finally { setExportingBankFile(null) }
  }

  // ── Attendance handlers ──────────────────────────────────────────────────────

  const handleSaveAttendance = async () => {
    if (!attForm.employee || !attForm.date) { toast.error('Employee and date are required'); return }
    setSavingAtt(true)
    try {
      await payrollApi.markAttendance({
        employee: attForm.employee,
        date: attForm.date,
        status: attForm.status,
        clock_in: attForm.clock_in || null,
        clock_out: attForm.clock_out || null,
        overtime_hours: attForm.overtime_hours || '0',
        notes: attForm.notes,
      })
      toast.success('Attendance recorded')
      setShowAttModal(false)
      setAttForm({ employee: '', date: now.toISOString().split('T')[0], status: 'present', clock_in: '', clock_out: '', overtime_hours: '0', notes: '' })
      loadAttendance()
    } catch (err: any) {
      toast.error(err?.response?.data?.employee?.[0] ?? err?.response?.data?.non_field_errors?.[0] ?? 'Failed to save')
    } finally { setSavingAtt(false) }
  }

  const handleBulkMark = async () => {
    if (!bulkAttDate) { toast.error('Date is required'); return }
    setSavingBulk(true)
    try {
      const empIds = employees.filter(e => e.is_active).map(e => e.id)
      await payrollApi.bulkMarkAttendance({
        employee_ids: empIds,
        date: bulkAttDate,
        status: bulkAttStatus,
        overtime_hours: bulkAttOvertime || '0',
      })
      toast.success(`All ${empIds.length} employees marked as ${bulkAttStatus}`)
      setShowBulkAttModal(false)
      loadAttendance()
    } catch { toast.error('Bulk mark failed') }
    finally { setSavingBulk(false) }
  }

  const handleDeleteAttendance = async (id: string) => {
    try {
      await payrollApi.attendance({ page_size: 1 }) // validate access
      // use fetch delete via api
      const { default: axios } = await import('axios')
      const token = useAuthStore.getState().tokens?.access
      const base = (import.meta.env.VITE_API_BASE_URL ?? '/api/v1')
      await axios.delete(`${base}/payroll/attendance/${id}/`, { headers: { Authorization: `Bearer ${token}` } })
      toast.success('Record deleted')
      loadAttendance()
    } catch { toast.error('Failed to delete') }
  }

  // ── Bonus handlers ───────────────────────────────────────────────────────────

  const handleSaveBonus = async () => {
    if (!bonusForm.employee || !bonusForm.amount || !bonusForm.reason) {
      toast.error('Employee, amount and reason are required')
      return
    }
    setSavingBonus(true)
    try {
      await payrollApi.createBonus(bonusForm)
      toast.success('Bonus added — will be applied in the next payroll run')
      setShowBonusModal(false)
      setBonusForm({ employee: '', amount: '', bonus_type: 'performance', reason: '', period_year: selectedYear, period_month: selectedMonth })
      loadBonuses()
    } catch (err: any) {
      toast.error(err?.response?.data?.error ?? 'Failed to add bonus')
    } finally { setSavingBonus(false) }
  }

  const handleDeleteBonus = async (id: string) => {
    if (!(await confirmDialog('Remove this bonus?'))) return
    try {
      await payrollApi.deleteBonus(id)
      toast.success('Bonus removed')
      loadBonuses()
    } catch { toast.error('Failed to remove') }
  }

  // ── Derived ──────────────────────────────────────────────────────────────────

  const displayRuns = archiveYear ? runs.filter((r) => r.period_year === archiveYear) : runs
  const latestRun = runs.find((r) => r.status === 'approved' || r.status === 'paid') ?? runs[0]

  const totalCashOutflow = latestRun
    ? parseFloat(latestRun.total_net ?? '0')
      + parseFloat(latestRun.total_pension_employer ?? '0')
      + parseFloat(latestRun.total_nhf ?? '0')
      + parseFloat(latestRun.total_nsitf ?? '0')
    : 0

  // Attendance summary: group records by employee
  const attByEmp: Record<string, { absent: number; halfDay: number; overtime: number; records: AttendanceRecord[] }> = {}
  for (const rec of attendanceRecords) {
    if (!attByEmp[rec.employee]) attByEmp[rec.employee] = { absent: 0, halfDay: 0, overtime: 0, records: [] }
    if (rec.status === 'absent') attByEmp[rec.employee].absent++
    if (rec.status === 'half_day') attByEmp[rec.employee].halfDay++
    attByEmp[rec.employee].overtime += parseFloat(rec.overtime_hours || '0')
    attByEmp[rec.employee].records.push(rec)
  }

  // ─── Render ──────────────────────────────────────────────────────────────────

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold text-white">Payroll</h1>
          <p className="text-slate-400 text-sm">Compute salaries, approve, and disburse — all in one flow</p>
        </div>
        <button
          onClick={() => { bypassNextGets(); loadRuns(); loadEmployees() }}
          disabled={loadingRuns}
          className="btn-ghost p-2 text-slate-400 hover:text-white"
          title="Refresh"
        >
          <RefreshCw size={16} className={loadingRuns ? 'animate-spin' : ''} />
        </button>
      </div>

      {/* Page tabs */}
      <div className="flex gap-1 p-1 bg-surface-800 rounded-xl w-fit">
        {([
          ['runs', 'Payroll Runs', Banknote],
          ['attendance', 'Attendance', Calendar],
          ['bonuses', 'Bonuses', Gift],
          ['paye', 'PAYE Remittance', Shield],
        ] as [PageTab, string, any][]).map(([t, label, Icon]) => (
          <button
            key={t}
            onClick={() => setPageTab(t)}
            className={pageTab === t
              ? 'px-4 py-2 rounded-lg text-sm font-semibold bg-brand-500 text-white flex items-center gap-2'
              : 'px-4 py-2 rounded-lg text-sm text-slate-400 hover:text-white transition-colors flex items-center gap-2'}
          >
            <Icon size={14} /> {label}
          </button>
        ))}
      </div>

      {/* ── PAYROLL RUNS TAB ── */}
      {pageTab === 'runs' && (
        <div className="space-y-6">
          {/* Run Payroll bar */}
          <div className="card p-5 flex flex-col sm:flex-row items-start sm:items-center gap-4 flex-wrap">
            <p className="text-white font-semibold shrink-0">Run Payroll for:</p>
            <div className="flex items-center gap-2 flex-wrap">
              <select className="input py-1.5" value={selectedMonth} onChange={(e) => setSelectedMonth(parseInt(e.target.value))}>
                {MONTHS.map((m, i) => <option key={i} value={i + 1}>{m}</option>)}
              </select>
              <select className="input py-1.5" value={selectedYear} onChange={(e) => setSelectedYear(parseInt(e.target.value))}>
                {[now.getFullYear() - 1, now.getFullYear(), now.getFullYear() + 1].map((y) => <option key={y} value={y}>{y}</option>)}
              </select>
              <button onClick={handleRunPayroll} disabled={running} className="btn-primary flex items-center gap-2 disabled:opacity-50">
                {running ? <Loader2 size={15} className="animate-spin" /> : <Banknote size={15} />}
                Run Payroll
              </button>
            </div>
            <div className="sm:ml-auto flex items-center gap-2">
              <YearFilter selectedYear={archiveYear} onChange={setArchiveYear} />
              <ExportButton endpoint="/payroll/employees/" filename="employees" />
            </div>
          </div>

          {/* Summary cards */}
          {latestRun && (
            <div className="grid grid-cols-2 lg:grid-cols-6 gap-4">
              <div className="card p-4">
                <p className="text-xs text-slate-400 flex items-center gap-1"><Users size={11} /> Employees</p>
                <p className="text-xl font-bold text-white mt-1">{latestRun.employee_count ?? latestRun.payslips?.length ?? '—'}</p>
              </div>
              <div className="card p-4">
                <p className="text-xs text-slate-400">Total Gross</p>
                <p className="text-xl font-bold text-white mt-1">{formatCurrency(latestRun.total_gross)}</p>
              </div>
              <div className="card p-4">
                <p className="text-xs text-slate-400">Total PAYE</p>
                <p className="text-xl font-bold text-red-400 mt-1">{formatCurrency(latestRun.total_paye)}</p>
              </div>
              <div className="card p-4">
                <p className="text-xs text-slate-400">Pension (Emp)</p>
                <p className="text-xl font-bold text-orange-400 mt-1">{formatCurrency(latestRun.total_pension_employee)}</p>
              </div>
              <div className="card p-4">
                <p className="text-xs text-slate-400">Total Net Pay</p>
                <p className="text-xl font-bold text-emerald-400 mt-1">{formatCurrency(latestRun.total_net)}</p>
              </div>
              <div className="card p-4 border border-amber-500/20 bg-amber-500/5">
                <p className="text-xs text-amber-400 flex items-center gap-1"><TrendingUp size={11} /> Cash Outflow</p>
                <p className="text-xl font-bold text-amber-300 mt-1">{formatCurrency(totalCashOutflow)}</p>
                <p className="text-[10px] text-slate-500 mt-0.5">Net + Employer costs</p>
              </div>
            </div>
          )}

          {/* Statutory Remittances */}
          {latestRun && (
            <div className="card p-6 space-y-4">
              <div className="flex flex-col sm:flex-row sm:items-center gap-3">
                <div className="flex items-center gap-2">
                  <h3 className="text-white font-semibold">Statutory Remittances</h3>
                  <span className="text-xs text-slate-500">({MONTHS[latestRun.period_month - 1]} {latestRun.period_year})</span>
                </div>
                <div className="sm:ml-auto flex items-center gap-2">
                  <Building2 size={14} className="text-slate-400 shrink-0" />
                  <select className="input py-1.5 text-xs max-w-xs" value={pensionProvider} onChange={(e) => setPensionProvider(e.target.value)}>
                    <option value="">— Select PFA (Pension Provider) —</option>
                    {PFAS.map((p) => <option key={p.name} value={p.name}>{p.name}</option>)}
                  </select>
                </div>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                {STATUTORY_ITEMS(pensionProvider, latestRun).map((item) => {
                  const isActive = activePaymentKey === item.key
                  return (
                    <div key={item.key} className={`p-4 bg-surface-900/50 rounded-xl border transition-all ${isActive ? 'border-brand-500 ring-1 ring-brand-500/30' : 'border-surface-700'}`}>
                      <div className="flex items-start justify-between mb-1">
                        <p className="text-xs text-slate-400 font-medium">{item.label}</p>
                        <button onClick={() => openLink(item.portal)} className="text-brand-400 hover:text-brand-300 flex items-center gap-1 text-xs ml-1 shrink-0">
                          <ExternalLink size={11} />
                          <span className="hidden sm:inline">{item.portalLabel}</span>
                        </button>
                      </div>
                      <p className={`text-lg font-bold ${item.color} mt-1`}>{formatCurrency(item.amount)}</p>
                      <p className="text-xs text-slate-500 mt-1">{item.deadline}</p>
                      <button onClick={() => setActivePaymentKey(isActive ? null : item.key)} className="mt-2 text-xs text-brand-400 hover:text-brand-300 flex items-center gap-1">
                        <CreditCard size={11} />{isActive ? 'Hide details' : 'View payment details'}
                      </button>
                      {isActive && (
                        <div className="mt-3 space-y-2 border-t border-surface-700 pt-3">
                          <div><p className="text-xs text-slate-500 uppercase tracking-wider">Bank / Institution</p><p className="text-xs text-white mt-0.5">{item.bankDetails.bank}</p></div>
                          <div><p className="text-xs text-slate-500 uppercase tracking-wider">Account / Reference</p><p className="text-xs text-white mt-0.5">{item.bankDetails.account}</p></div>
                          <div><p className="text-xs text-slate-500 uppercase tracking-wider">How to Pay</p><p className="text-xs text-slate-300 mt-0.5 leading-relaxed">{item.bankDetails.instruction}</p></div>
                          <button onClick={() => openLink(item.portal)} className="inline-flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg bg-brand-500/15 text-brand-400 hover:bg-brand-500/25 mt-1">
                            <ExternalLink size={11} /> Open {item.portalLabel}
                          </button>
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            </div>
          )}

          {/* Runs table */}
          <div className="card p-0 overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-surface-700">
                    {['', 'Run #', 'Period', 'Status', 'Employees', 'Total Gross', 'Total Net', 'Actions'].map((h) => (
                      <th key={h} className="px-4 py-3.5 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {loadingRuns ? (
                    Array.from({ length: 3 }).map((_, i) => (
                      <tr key={i}>{Array.from({ length: 8 }).map((_, j) => (
                        <td key={j} className="px-4 py-3.5"><div className="h-4 bg-surface-700 rounded animate-pulse w-16" /></td>
                      ))}</tr>
                    ))
                  ) : displayRuns.length === 0 ? (
                    <tr><td colSpan={8} className="px-4 py-12 text-center">
                      <Banknote size={32} className="mx-auto mb-2 text-slate-600" />
                      <p className="text-slate-500">{archiveYear ? `No runs for ${archiveYear}.` : 'No payroll runs yet. Click "Run Payroll" to get started.'}</p>
                    </td></tr>
                  ) : displayRuns.map((r) => (
                    <>
                      <tr key={r.id} className="table-row">
                        <td className="px-4 py-3.5">
                          <button onClick={() => setExpandedRun(expandedRun === r.id ? null : r.id)} className="text-slate-400 hover:text-white">
                            {expandedRun === r.id ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                          </button>
                        </td>
                        <td className="px-4 py-3.5 font-mono text-brand-400">{r.run_number}</td>
                        <td className="px-4 py-3.5 text-slate-300">{MONTHS[r.period_month - 1]} {r.period_year}</td>
                        <td className="px-4 py-3.5">
                          <div className="flex items-center gap-1.5">
                            <span className={STATUS_BADGE[r.status] ?? 'badge-slate'}>{r.status}</span>
                            {r.submitted_for_approval && r.status === 'processing' && (
                              <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-400">Pending Approval</span>
                            )}
                          </div>
                        </td>
                        <td className="px-4 py-3.5 text-slate-300">{r.employee_count ?? r.payslips?.length ?? '—'}</td>
                        <td className="px-4 py-3.5 font-mono text-white">{formatCurrency(r.total_gross)}</td>
                        <td className="px-4 py-3.5 font-mono text-emerald-400">{formatCurrency(r.total_net)}</td>
                        <td className="px-4 py-3.5">
                          <div className="flex items-center gap-1.5 flex-wrap">
                            {r.status === 'processing' && !r.submitted_for_approval && (
                              <button onClick={() => openApproverPicker(r.id)} disabled={submittingId === r.id}
                                className="text-xs px-2.5 py-1 rounded-lg bg-amber-500/15 text-amber-400 hover:bg-amber-500/25 disabled:opacity-50">
                                {submittingId === r.id ? <Loader2 size={10} className="animate-spin inline mr-1" /> : null}Submit for Approval
                              </button>
                            )}
                            {r.status === 'processing' && (r.submitted_for_approval || isOwnerOrAdmin) && (
                              <button onClick={() => handleApprove(r.id)} disabled={approvingId === r.id}
                                className="text-xs px-2.5 py-1 rounded-lg bg-blue-500/15 text-blue-400 hover:bg-blue-500/25 disabled:opacity-50">
                                {approvingId === r.id ? <Loader2 size={10} className="animate-spin inline mr-1" /> : null}Approve
                              </button>
                            )}
                            {r.status === 'approved' && (
                              <button onClick={() => { setMarkPayId(r.id); setPaymentDate(now.toISOString().split('T')[0]) }}
                                className="text-xs px-2.5 py-1 rounded-lg bg-emerald-500/15 text-emerald-400 hover:bg-emerald-500/25">
                                Pay Salaries
                              </button>
                            )}
                            {r.status !== 'draft' && (
                              <button onClick={() => handleExportBankFile(r.id)} disabled={exportingBankFile === r.id}
                                className="text-xs px-2 py-1 rounded-lg bg-surface-700 text-slate-400 hover:text-white" title="Export bank CSV">
                                {exportingBankFile === r.id ? <Loader2 size={11} className="animate-spin" /> : <Download size={11} />}
                              </button>
                            )}
                            {r.payment_date && <span className="text-xs text-slate-500">{formatDate(r.payment_date)}</span>}
                          </div>
                        </td>
                      </tr>
                      {expandedRun === r.id && (
                        <tr key={`${r.id}-detail`} className="bg-surface-900/50">
                          <td colSpan={8} className="px-6 py-4">
                            {/* Cash outflow breakdown */}
                            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4 p-3 bg-surface-800/50 rounded-xl border border-surface-700">
                              <div><p className="text-xs text-slate-500">Salaries (Net)</p><p className="text-sm font-mono text-white font-semibold">{formatCurrency(r.total_net)}</p></div>
                              <div><p className="text-xs text-slate-500">PAYE Tax</p><p className="text-sm font-mono text-red-400 font-semibold">{formatCurrency(r.total_paye)}</p></div>
                              <div><p className="text-xs text-slate-500">Pension (Total)</p><p className="text-sm font-mono text-orange-400 font-semibold">{formatCurrency(parseFloat(r.total_pension_employee ?? '0') + parseFloat(r.total_pension_employer ?? '0'))}</p></div>
                              <div className="border-l border-surface-600 pl-3">
                                <p className="text-xs text-amber-400">Total Cash Outflow</p>
                                <p className="text-sm font-mono text-amber-300 font-bold">
                                  {formatCurrency(parseFloat(r.total_net ?? '0') + parseFloat(r.total_pension_employer ?? '0') + parseFloat(r.total_nhf ?? '0') + parseFloat(r.total_nsitf ?? '0'))}
                                </p>
                              </div>
                            </div>
                            <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">Employee Payslips</p>
                            <div className="overflow-x-auto">
                              <table className="w-full text-xs">
                                <thead>
                                  <tr className="border-b border-surface-700">
                                    {['Employee', 'Gross', 'Bonus', 'OT Pay', 'PAYE', 'Pension', 'NHF', 'Penalties', 'Loans', 'Att. Ded.', 'Net Pay', 'Transfer'].map((h) => (
                                      <th key={h} className="pb-2 pr-3 text-left text-slate-500 uppercase tracking-wider whitespace-nowrap">{h}</th>
                                    ))}
                                  </tr>
                                </thead>
                                <tbody className="divide-y divide-surface-700">
                                  {r.payslips.map((p) => (
                                    <tr key={p.id}>
                                      <td className="py-2 pr-3 text-slate-300 whitespace-nowrap">{p.employee_name}</td>
                                      <td className="py-2 pr-3 font-mono text-white">{formatCurrency(p.gross_salary)}</td>
                                      <td className="py-2 pr-3 font-mono text-emerald-400">{parseFloat(p.bonus_amount || '0') > 0 ? formatCurrency(p.bonus_amount) : <span className="text-slate-600">—</span>}</td>
                                      <td className="py-2 pr-3 font-mono text-teal-400">{parseFloat(p.overtime_amount || '0') > 0 ? formatCurrency(p.overtime_amount) : <span className="text-slate-600">—</span>}</td>
                                      <td className="py-2 pr-3 font-mono text-red-400">{formatCurrency(p.paye_tax)}</td>
                                      <td className="py-2 pr-3 font-mono text-orange-400">{formatCurrency(p.employee_pension)}</td>
                                      <td className="py-2 pr-3 font-mono text-blue-400">{formatCurrency(p.nhf)}</td>
                                      <td className="py-2 pr-3 font-mono text-rose-400">{parseFloat(p.penalty_deductions || '0') > 0 ? formatCurrency(p.penalty_deductions) : <span className="text-slate-600">—</span>}</td>
                                      <td className="py-2 pr-3 font-mono text-amber-400">{parseFloat(p.loan_deductions || '0') > 0 ? formatCurrency(p.loan_deductions) : <span className="text-slate-600">—</span>}</td>
                                      <td className="py-2 pr-3 font-mono text-yellow-500">{parseFloat(p.attendance_deduction || '0') > 0 ? formatCurrency(p.attendance_deduction) : <span className="text-slate-600">—</span>}</td>
                                      <td className="py-2 pr-3 font-mono text-emerald-400 font-semibold">{formatCurrency(p.net_salary)}</td>
                                      <td className="py-2 flex items-center gap-1">
                                        {TRANSFER_STATUS_ICON[p.transfer_status as keyof typeof TRANSFER_STATUS_ICON] ?? null}
                                        <span className="text-slate-500 capitalize">{p.transfer_status ?? 'pending'}</span>
                                      </td>
                                      <td className="py-2">
                                        <button onClick={() => setSelectedPayslip(p)} title="PAYE Bracket Detail" className="text-slate-500 hover:text-brand-400 transition-colors p-0.5">
                                          <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
                                        </button>
                                      </td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </div>
                          </td>
                        </tr>
                      )}
                    </>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* ── ATTENDANCE TAB ── */}
      {pageTab === 'attendance' && (
        <div className="space-y-4">
          {/* Controls */}
          <div className="card p-4 flex flex-col sm:flex-row items-start sm:items-center gap-3 flex-wrap">
            <p className="text-white font-semibold shrink-0">Period:</p>
            <select className="input py-1.5" value={selectedMonth} onChange={(e) => setSelectedMonth(parseInt(e.target.value))}>
              {MONTHS.map((m, i) => <option key={i} value={i + 1}>{m}</option>)}
            </select>
            <select className="input py-1.5" value={selectedYear} onChange={(e) => setSelectedYear(parseInt(e.target.value))}>
              {[now.getFullYear() - 1, now.getFullYear()].map((y) => <option key={y} value={y}>{y}</option>)}
            </select>
            <div className="sm:ml-auto flex items-center gap-2">
              <button onClick={() => setShowBulkAttModal(true)} className="btn-secondary flex items-center gap-2 text-sm py-1.5">
                <Users size={14} /> Bulk Mark Day
              </button>
              <button onClick={() => setShowAttModal(true)} className="btn-primary flex items-center gap-2 text-sm py-1.5">
                <Plus size={14} /> Add Record
              </button>
            </div>
          </div>

          {/* Info banner */}
          <div className="p-3 bg-blue-500/5 border border-blue-500/20 rounded-xl text-xs text-slate-400">
            <strong className="text-blue-400">How it works:</strong> Attendance records for this period are automatically applied when you run payroll.
            Absent days proportionally deduct from salary. Overtime hours add taxable pay at 1.5× hourly rate.
          </div>

          {/* Per-employee attendance summary */}
          {loadingAtt ? (
            <div className="card p-8 text-center text-slate-500"><Loader2 size={20} className="animate-spin mx-auto" /></div>
          ) : employees.filter(e => e.is_active).length === 0 ? (
            <div className="card p-12 text-center text-slate-500">No active employees found.</div>
          ) : (
            <div className="card p-0 overflow-hidden">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-surface-700">
                    {['Employee', 'Department', 'Absent Days', 'Half Days', 'Overtime Hrs', 'Records', ''].map((h) => (
                      <th key={h} className="px-4 py-3.5 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {employees.filter(e => e.is_active).map((emp) => {
                    const summary = attByEmp[emp.id]
                    return (
                      <tr key={emp.id} className="table-row">
                        <td className="px-4 py-3 text-white font-medium">{emp.first_name} {emp.last_name}</td>
                        <td className="px-4 py-3 text-slate-400 text-xs">{emp.department || '—'}</td>
                        <td className="px-4 py-3">
                          {summary?.absent > 0
                            ? <span className="badge-red">{summary.absent} {summary.absent === 1 ? 'day' : 'days'}</span>
                            : <span className="text-slate-600 text-xs">—</span>}
                        </td>
                        <td className="px-4 py-3">
                          {summary?.halfDay > 0
                            ? <span className="badge-yellow">{summary.halfDay}</span>
                            : <span className="text-slate-600 text-xs">—</span>}
                        </td>
                        <td className="px-4 py-3">
                          {summary?.overtime > 0
                            ? <span className="badge-blue">{summary.overtime.toFixed(1)} hrs</span>
                            : <span className="text-slate-600 text-xs">—</span>}
                        </td>
                        <td className="px-4 py-3 text-slate-400 text-xs">{summary?.records.length ?? 0} record{(summary?.records.length ?? 0) !== 1 ? 's' : ''}</td>
                        <td className="px-4 py-3">
                          <button
                            onClick={() => { setAttForm(f => ({ ...f, employee: emp.id })); setShowAttModal(true) }}
                            className="text-xs px-2 py-1 rounded-lg bg-brand-500/15 text-brand-400 hover:bg-brand-500/25"
                          >
                            + Add
                          </button>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}

          {/* Individual records */}
          {attendanceRecords.length > 0 && (
            <div className="card p-0 overflow-hidden">
              <div className="px-4 py-3 border-b border-surface-700">
                <p className="text-sm font-semibold text-white">All Records — {MONTHS[selectedMonth - 1]} {selectedYear}</p>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-surface-700">
                      {['Employee', 'Date', 'Status', 'Clock In', 'Clock Out', 'Overtime', 'Notes', ''].map((h) => (
                        <th key={h} className="px-4 py-2.5 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {attendanceRecords.map((rec) => {
                      const statusMeta = ATTENDANCE_STATUSES.find(s => s.value === rec.status)
                      return (
                        <tr key={rec.id} className="table-row">
                          <td className="px-4 py-2.5 text-white">{rec.employee_name}</td>
                          <td className="px-4 py-2.5 font-mono text-slate-300 text-xs">{rec.date}</td>
                          <td className="px-4 py-2.5">
                            <span className={`text-xs font-medium capitalize ${statusMeta?.color ?? 'text-slate-400'}`}>{rec.status.replace('_', ' ')}</span>
                          </td>
                          <td className="px-4 py-2.5 text-slate-400 text-xs">{rec.clock_in ?? '—'}</td>
                          <td className="px-4 py-2.5 text-slate-400 text-xs">{rec.clock_out ?? '—'}</td>
                          <td className="px-4 py-2.5 text-blue-400 text-xs">{parseFloat(rec.overtime_hours) > 0 ? `${rec.overtime_hours} hrs` : '—'}</td>
                          <td className="px-4 py-2.5 text-slate-500 text-xs max-w-xs truncate">{rec.notes || '—'}</td>
                          <td className="px-4 py-2.5">
                            <button onClick={() => handleDeleteAttendance(rec.id)} className="text-slate-500 hover:text-red-400 p-1 rounded">
                              <Trash2 size={13} />
                            </button>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      )}

      {/* ── BONUSES TAB ── */}
      {pageTab === 'bonuses' && (
        <div className="space-y-4">
          {/* Controls */}
          <div className="card p-4 flex flex-col sm:flex-row items-start sm:items-center gap-3 flex-wrap">
            <p className="text-white font-semibold shrink-0">Period:</p>
            <select className="input py-1.5" value={selectedMonth} onChange={(e) => setSelectedMonth(parseInt(e.target.value))}>
              {MONTHS.map((m, i) => <option key={i} value={i + 1}>{m}</option>)}
            </select>
            <select className="input py-1.5" value={selectedYear} onChange={(e) => setSelectedYear(parseInt(e.target.value))}>
              {[now.getFullYear() - 1, now.getFullYear()].map((y) => <option key={y} value={y}>{y}</option>)}
            </select>
            <button onClick={() => { setBonusForm(f => ({ ...f, period_year: selectedYear, period_month: selectedMonth })); setShowBonusModal(true) }}
              className="sm:ml-auto btn-primary flex items-center gap-2 text-sm py-1.5">
              <Plus size={14} /> Add Bonus
            </button>
          </div>

          <div className="p-3 bg-emerald-500/5 border border-emerald-500/20 rounded-xl text-xs text-slate-400">
            <strong className="text-emerald-400">How it works:</strong> Pending bonuses for this period are automatically added to gross salary when payroll is run.
            Bonuses are taxable income and PAYE is computed on gross + bonus.
          </div>

          {loadingBonuses ? (
            <div className="card p-8 text-center"><Loader2 size={20} className="animate-spin mx-auto text-slate-500" /></div>
          ) : bonuses.length === 0 ? (
            <div className="card p-12 text-center">
              <Gift size={32} className="mx-auto mb-2 text-slate-600" />
              <p className="text-slate-400 font-medium">No bonuses for this period</p>
              <p className="text-slate-500 text-xs mt-1">Add bonuses before running payroll — they will be included automatically.</p>
              <button onClick={() => { setBonusForm(f => ({ ...f, period_year: selectedYear, period_month: selectedMonth })); setShowBonusModal(true) }}
                className="btn-primary mt-4 inline-flex items-center gap-2 text-sm">
                <Plus size={14} /> Add First Bonus
              </button>
            </div>
          ) : (
            <div className="card p-0 overflow-hidden">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-surface-700">
                    {['Employee', 'Type', 'Amount', 'Reason', 'Status', ''].map((h) => (
                      <th key={h} className="px-4 py-3.5 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {bonuses.map((b) => (
                    <tr key={b.id} className="table-row">
                      <td className="px-4 py-3 text-white font-medium">{b.employee_name}</td>
                      <td className="px-4 py-3">
                        <span className="badge-blue capitalize">{b.bonus_type.replace('_', ' ')}</span>
                      </td>
                      <td className="px-4 py-3 font-mono text-emerald-400 font-semibold">{formatCurrency(b.amount)}</td>
                      <td className="px-4 py-3 text-slate-400 text-xs max-w-xs truncate">{b.reason}</td>
                      <td className="px-4 py-3">
                        <span className={b.status === 'applied' ? 'badge-green' : 'badge-yellow'}>{b.status}</span>
                      </td>
                      <td className="px-4 py-3">
                        {b.status === 'pending' && (
                          <button onClick={() => handleDeleteBonus(b.id)} className="text-slate-500 hover:text-red-400 p-1 rounded">
                            <Trash2 size={13} />
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div className="px-4 py-3 border-t border-surface-700 flex justify-between items-center">
                <span className="text-xs text-slate-500">{bonuses.length} bonus{bonuses.length !== 1 ? 'es' : ''}</span>
                <span className="text-sm font-mono text-emerald-400 font-semibold">
                  Total: {formatCurrency(bonuses.reduce((s, b) => s + parseFloat(b.amount), 0))}
                </span>
              </div>
            </div>
          )}
        </div>
      )}

      {/* ── ADD ATTENDANCE MODAL ── */}
      {showAttModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={() => setShowAttModal(false)} />
          <div className="relative bg-surface-800 border border-surface-700 rounded-2xl w-full max-w-md shadow-2xl">
            <div className="flex items-center justify-between p-6 border-b border-surface-700">
              <h2 className="text-lg font-bold text-white">Add Attendance Record</h2>
              <button onClick={() => setShowAttModal(false)} className="text-slate-400 hover:text-white"><X size={18} /></button>
            </div>
            <div className="p-6 space-y-4">
              <div>
                <label className="label">Employee *</label>
                <select className="input" value={attForm.employee} onChange={(e) => setAttForm(f => ({ ...f, employee: e.target.value }))}>
                  <option value="">— Select employee —</option>
                  {employees.filter(e => e.is_active).map((e) => (
                    <option key={e.id} value={e.id}>{e.first_name} {e.last_name} ({e.employee_id})</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="label">Date *</label>
                <DateInput value={attForm.date} onChange={(v) => setAttForm(f => ({ ...f, date: v }))} />
              </div>
              <div>
                <label className="label">Status</label>
                <div className="flex flex-wrap gap-2">
                  {ATTENDANCE_STATUSES.map((s) => (
                    <button key={s.value} type="button"
                      onClick={() => setAttForm(f => ({ ...f, status: s.value }))}
                      className={`px-3 py-1.5 rounded-lg border text-sm transition-all ${attForm.status === s.value ? 'bg-brand-500/20 border-brand-500 text-white' : 'border-surface-600 text-slate-400 hover:border-surface-500'}`}>
                      {s.label}
                    </button>
                  ))}
                </div>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="label">Clock In</label>
                  <input type="time" className="input" value={attForm.clock_in} onChange={(e) => setAttForm(f => ({ ...f, clock_in: e.target.value }))} />
                </div>
                <div>
                  <label className="label">Clock Out</label>
                  <input type="time" className="input" value={attForm.clock_out} onChange={(e) => setAttForm(f => ({ ...f, clock_out: e.target.value }))} />
                </div>
              </div>
              <div>
                <label className="label">Overtime Hours</label>
                <input type="number" min="0" step="0.5" className="input" placeholder="0" value={attForm.overtime_hours} onChange={(e) => setAttForm(f => ({ ...f, overtime_hours: e.target.value }))} />
              </div>
              <div>
                <label className="label">Notes</label>
                <input type="text" className="input" placeholder="Optional note" value={attForm.notes} onChange={(e) => setAttForm(f => ({ ...f, notes: e.target.value }))} />
              </div>
            </div>
            <div className="flex gap-3 p-6 border-t border-surface-700">
              <button onClick={() => setShowAttModal(false)} className="btn-ghost flex-1">Cancel</button>
              <button onClick={handleSaveAttendance} disabled={savingAtt} className="btn-primary flex-1 disabled:opacity-50">
                {savingAtt ? 'Saving…' : 'Save Record'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── BULK MARK MODAL ── */}
      {showBulkAttModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={() => setShowBulkAttModal(false)} />
          <div className="relative bg-surface-800 border border-surface-700 rounded-2xl w-full max-w-sm shadow-2xl">
            <div className="flex items-center justify-between p-6 border-b border-surface-700">
              <h2 className="text-lg font-bold text-white">Bulk Mark Attendance</h2>
              <button onClick={() => setShowBulkAttModal(false)} className="text-slate-400 hover:text-white"><X size={18} /></button>
            </div>
            <div className="p-6 space-y-4">
              <p className="text-slate-400 text-sm">Marks <strong className="text-white">all {employees.filter(e => e.is_active).length} active employees</strong> for one day.</p>
              <div>
                <label className="label">Date *</label>
                <DateInput value={bulkAttDate} onChange={setBulkAttDate} />
              </div>
              <div>
                <label className="label">Status</label>
                <div className="flex flex-wrap gap-2">
                  {ATTENDANCE_STATUSES.map((s) => (
                    <button key={s.value} type="button"
                      onClick={() => setBulkAttStatus(s.value)}
                      className={`px-3 py-1.5 rounded-lg border text-sm transition-all ${bulkAttStatus === s.value ? 'bg-brand-500/20 border-brand-500 text-white' : 'border-surface-600 text-slate-400 hover:border-surface-500'}`}>
                      {s.label}
                    </button>
                  ))}
                </div>
              </div>
              <div>
                <label className="label">Overtime Hours (all employees)</label>
                <input type="number" min="0" step="0.5" className="input" placeholder="0" value={bulkAttOvertime} onChange={(e) => setBulkAttOvertime(e.target.value)} />
              </div>
            </div>
            <div className="flex gap-3 p-6 border-t border-surface-700">
              <button onClick={() => setShowBulkAttModal(false)} className="btn-ghost flex-1">Cancel</button>
              <button onClick={handleBulkMark} disabled={savingBulk} className="btn-primary flex-1 disabled:opacity-50">
                {savingBulk ? <Loader2 size={15} className="animate-spin mx-auto" /> : `Mark ${employees.filter(e => e.is_active).length} Employees`}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── ADD BONUS MODAL ── */}
      {showBonusModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={() => setShowBonusModal(false)} />
          <div className="relative bg-surface-800 border border-surface-700 rounded-2xl w-full max-w-md shadow-2xl">
            <div className="flex items-center justify-between p-6 border-b border-surface-700">
              <h2 className="text-lg font-bold text-white">Add Bonus</h2>
              <button onClick={() => setShowBonusModal(false)} className="text-slate-400 hover:text-white"><X size={18} /></button>
            </div>
            <div className="p-6 space-y-4">
              <div>
                <label className="label">Employee *</label>
                <select className="input" value={bonusForm.employee} onChange={(e) => setBonusForm(f => ({ ...f, employee: e.target.value }))}>
                  <option value="">— Select employee —</option>
                  {employees.filter(e => e.is_active).map((e) => (
                    <option key={e.id} value={e.id}>{e.first_name} {e.last_name} ({e.employee_id})</option>
                  ))}
                </select>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="label">Amount (₦) *</label>
                  <AmountInput className="input" placeholder="e.g. 50000" value={bonusForm.amount} onChange={(v) => setBonusForm(f => ({ ...f, amount: v }))} />
                </div>
                <div>
                  <label className="label">Bonus Type</label>
                  <select className="input" value={bonusForm.bonus_type} onChange={(e) => setBonusForm(f => ({ ...f, bonus_type: e.target.value }))}>
                    {BONUS_TYPES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
                  </select>
                </div>
              </div>
              <div>
                <label className="label">Reason *</label>
                <input type="text" className="input" placeholder="e.g. Q4 performance bonus" value={bonusForm.reason} onChange={(e) => setBonusForm(f => ({ ...f, reason: e.target.value }))} />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="label">Month</label>
                  <select className="input" value={bonusForm.period_month} onChange={(e) => setBonusForm(f => ({ ...f, period_month: parseInt(e.target.value) }))}>
                    {MONTHS.map((m, i) => <option key={i} value={i + 1}>{m}</option>)}
                  </select>
                </div>
                <div>
                  <label className="label">Year</label>
                  <select className="input" value={bonusForm.period_year} onChange={(e) => setBonusForm(f => ({ ...f, period_year: parseInt(e.target.value) }))}>
                    {[now.getFullYear() - 1, now.getFullYear()].map((y) => <option key={y} value={y}>{y}</option>)}
                  </select>
                </div>
              </div>
              <p className="text-xs text-slate-500">This bonus will be automatically applied when payroll is run for the selected period.</p>
            </div>
            <div className="flex gap-3 p-6 border-t border-surface-700">
              <button onClick={() => setShowBonusModal(false)} className="btn-ghost flex-1">Cancel</button>
              <button onClick={handleSaveBonus} disabled={savingBonus} className="btn-primary flex-1 disabled:opacity-50">
                {savingBonus ? 'Saving…' : 'Add Bonus'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── PAY SALARIES MODAL ── */}
      {markPayId && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={() => { setMarkPayId(null); setTransferResults(null) }} />
          <div className="relative bg-surface-800 border border-surface-700 rounded-2xl w-full max-w-lg shadow-2xl max-h-[90vh] flex flex-col">
            <div className="p-6 border-b border-surface-700">
              <h2 className="text-lg font-bold text-white">Pay Employees</h2>
              <p className="text-xs text-slate-400 mt-0.5">
                {runs.find(r => r.id === markPayId)?.run_number} —{' '}
                <span className="text-emerald-400 font-mono">{formatCurrency(runs.find(r => r.id === markPayId)?.total_net ?? 0)}</span> net to{' '}
                {runs.find(r => r.id === markPayId)?.payslips?.length ?? '?'} employees
              </p>
            </div>
            <div className="p-6 space-y-4 overflow-y-auto flex-1">
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Payment Date</label>
                <DateInput value={paymentDate} onChange={setPaymentDate} />
              </div>
              {(() => {
                const run = runs.find(r => r.id === markPayId)
                if (!run) return null
                const failed = transferResults?.filter(r => r.status === 'failed') ?? []
                const initiated = transferResults?.filter(r => r.status === 'initiated') ?? []
                return (
                  <div>
                    <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">
                      {run.payslips.length} Employee{run.payslips.length !== 1 ? 's' : ''}
                    </p>
                    <div className="space-y-1.5 max-h-48 overflow-y-auto pr-1">
                      {run.payslips.map((p) => {
                        const hasBankDetails = p.employee_account_number && p.employee_bank_code
                        const result = transferResults?.find(r => r.employee === p.employee_id_str)
                        return (
                          <div key={p.id} className={`flex items-center justify-between px-3 py-2 rounded-lg border text-xs ${hasBankDetails ? 'border-surface-600 bg-surface-700/30' : 'border-amber-500/20 bg-amber-500/5'}`}>
                            <div className="min-w-0 flex-1">
                              <p className="text-white font-medium truncate">{p.employee_name}</p>
                              {hasBankDetails
                                ? <p className="text-slate-500">{p.employee_bank_name} · {p.employee_account_number}</p>
                                : <p className="text-amber-500 flex items-center gap-1"><AlertTriangle size={10} /> No bank details</p>}
                            </div>
                            <div className="text-right ml-3 shrink-0">
                              <p className="font-mono text-emerald-400 font-semibold">{formatCurrency(p.net_salary)}</p>
                              {result && (
                                <p className={`text-[10px] mt-0.5 flex items-center gap-1 justify-end ${result.status === 'initiated' ? 'text-emerald-400' : result.status === 'failed' ? 'text-red-400' : 'text-amber-400'}`}>
                                  {result.status === 'initiated' ? <CheckCircle size={10} /> : result.status === 'failed' ? <XCircle size={10} /> : <AlertTriangle size={10} />}
                                  {result.status}
                                </p>
                              )}
                            </div>
                          </div>
                        )
                      })}
                    </div>
                    {transferResults && (
                      <div className={`rounded-xl p-3 text-xs border mt-2 ${initiated.length > 0 ? 'bg-emerald-500/10 border-emerald-500/30' : 'bg-red-500/10 border-red-500/30'}`}>
                        <div className="flex items-center gap-4 mb-1">
                          <span className="text-emerald-400 flex items-center gap-1"><CheckCircle size={11} /> Initiated: {initiated.length}</span>
                          <span className="text-amber-400 flex items-center gap-1"><AlertTriangle size={11} /> Skipped: {transferResults.filter(r => r.status === 'skipped').length}</span>
                          <span className="text-red-400 flex items-center gap-1"><XCircle size={11} /> Failed: {failed.length}</span>
                        </div>
                        {failed.map((r, i) => <p key={i} className="text-red-300 mt-0.5">{r.name}: {r.reason}</p>)}
                      </div>
                    )}
                  </div>
                )
              })()}
            </div>
            <div className="p-6 border-t border-surface-700 space-y-2">
              {transferResults?.some(r => r.status === 'failed') && (
                <button onClick={handleRetryFailed} disabled={retrying}
                  className="w-full flex items-center justify-center gap-2 py-2.5 rounded-xl bg-amber-500/15 border border-amber-500/30 text-amber-400 font-semibold text-sm hover:bg-amber-500/25 disabled:opacity-50">
                  {retrying ? <Loader2 size={15} className="animate-spin" /> : <RotateCcw size={15} />}
                  Retry Failed Payments
                </button>
              )}
              {!transferResults?.some(r => r.status === 'initiated') && (
                <button onClick={handleInitiateTransfers} disabled={initiatingTransfer}
                  className="w-full flex items-center justify-center gap-2 py-2.5 rounded-xl bg-brand-500 hover:bg-brand-600 text-white font-semibold text-sm disabled:opacity-50">
                  {initiatingTransfer ? <Loader2 size={16} className="animate-spin" /> : <Send size={15} />}
                  {initiatingTransfer ? 'Initiating…' : 'Pay via Paystack (Bulk Transfer)'}
                </button>
              )}
              <div className="flex gap-2">
                <button onClick={() => { setMarkPayId(null); setTransferResults(null) }}
                  className="flex-1 py-2.5 rounded-xl border border-surface-600 text-slate-400 hover:text-white text-sm">Cancel</button>
                <button onClick={handleMarkPaid}
                  className="flex-1 py-2.5 rounded-xl border border-slate-600 text-slate-300 hover:bg-surface-700 text-sm flex items-center justify-center gap-1.5">
                  <RefreshCw size={14} /> Mark as Paid (Manual)
                </button>
              </div>
              <p className="text-center text-[10px] text-slate-600">Paystack bulk transfers require sufficient Paystack balance and a verified business account.</p>
            </div>
          </div>
        </div>
      )}

      {/* ── PAYE Remittance Tab ──────────────────────────────────────────────── */}
      {pageTab === 'paye' && (
        <div className="space-y-6">
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-white font-semibold">PAYE Remittance Tracker</h2>
                <p className="text-slate-500 text-xs mt-0.5">Monthly PAYE obligations auto-created after each payroll run. Remit by the 10th of the following month.</p>
              </div>
              <button onClick={loadPayeRemittances} className="btn-ghost flex items-center gap-1.5 text-sm"><RefreshCw size={14} /> Refresh</button>
            </div>

            {loadingPaye ? (
              <div className="card p-8 text-center text-slate-500">Loading…</div>
            ) : payeRemittances.length === 0 ? (
              <div className="card p-12 text-center">
                <Shield size={36} className="mx-auto text-slate-600 mb-3" />
                <p className="text-slate-400 font-medium">No PAYE remittances yet</p>
                <p className="text-slate-500 text-xs mt-1">Run payroll to generate monthly PAYE obligations</p>
              </div>
            ) : (
              <div className="card overflow-hidden">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-surface-700">
                      {['Period', 'Due Date', 'Amount Due', 'Paid', 'Balance', 'Status', ''].map((h) => (
                        <th key={h} className="px-5 py-3.5 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-surface-700">
                    {payeRemittances.map((pr) => (
                      <tr key={pr.id} className={`table-row ${pr.status === 'overdue' ? 'bg-red-500/5' : ''}`}>
                        <td className="px-5 py-3.5 text-white font-medium">
                          {String(pr.period_month).padStart(2, '0')}/{pr.period_year}
                        </td>
                        <td className="px-5 py-3.5 text-slate-400">{formatDate(pr.due_date)}</td>
                        <td className="px-5 py-3.5 font-mono text-white">{formatCurrency(pr.amount_due)}</td>
                        <td className="px-5 py-3.5 font-mono text-emerald-400">{formatCurrency(pr.amount_paid)}</td>
                        <td className="px-5 py-3.5 font-mono">
                          <span className={parseFloat(pr.balance_due) > 0 ? 'text-red-400' : 'text-emerald-400'}>
                            {formatCurrency(pr.balance_due)}
                          </span>
                        </td>
                        <td className="px-5 py-3.5">
                          <span className={pr.status === 'remitted' ? 'badge-green' : pr.status === 'overdue' ? 'badge-red' : 'badge-yellow'}>
                            {pr.status}
                          </span>
                        </td>
                        <td className="px-5 py-3.5">
                          {pr.status !== 'remitted' && (
                            <button onClick={() => { setRemittingPayeId(pr.id); setPayeRemitForm({ reference: '', amount_paid: pr.balance_due, notes: '' }); setShowPayeRemitModal(true) }}
                              className="text-xs px-2.5 py-1 rounded-lg bg-brand-500/15 text-brand-400 hover:bg-brand-500/25 transition-colors">
                              Remit
                            </button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* Employee Tax Profiles */}
          <div className="space-y-4">
            <div>
              <h2 className="text-white font-semibold">Employee Tax Profiles</h2>
              <p className="text-slate-500 text-xs mt-0.5">Customise individual relief items per employee — NHF, voluntary pension, life assurance premiums, PAYE exempt status</p>
            </div>
            {employees.length === 0 ? (
              <div className="card p-8 text-center text-slate-500">No employees found</div>
            ) : (
              <div className="card overflow-hidden">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-surface-700">
                      {['Employee', 'Department', 'Gross Salary', 'Tax Profile', ''].map((h) => (
                        <th key={h} className="px-5 py-3.5 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-surface-700">
                    {employees.filter((e) => e.is_active).map((emp) => (
                      <tr key={emp.id} className="table-row">
                        <td className="px-5 py-3.5 text-white font-medium">{emp.first_name} {emp.last_name}</td>
                        <td className="px-5 py-3.5 text-slate-400">{emp.department || '—'}</td>
                        <td className="px-5 py-3.5 font-mono text-white">{formatCurrency(emp.gross_salary)}</td>
                        <td className="px-5 py-3.5">
                          <span className="badge-slate">Custom relief configurable</span>
                        </td>
                        <td className="px-5 py-3.5">
                          <button onClick={() => openTaxProfile(emp)}
                            className="text-xs px-2.5 py-1 rounded-lg bg-surface-600 text-slate-300 hover:bg-surface-500 hover:text-white transition-colors flex items-center gap-1">
                            <Shield size={11} /> Tax Profile
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      )}

      {/* PAYE Remit Modal */}
      {showPayeRemitModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
          <div className="bg-surface-800 border border-surface-600 rounded-2xl p-6 w-full max-w-md shadow-2xl">
            <div className="flex items-center justify-between mb-5">
              <h2 className="text-lg font-bold text-white">Record PAYE Remittance</h2>
              <button onClick={() => setShowPayeRemitModal(false)} className="text-slate-400 hover:text-white"><X size={18} /></button>
            </div>
            <div className="space-y-4">
              <div>
                <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider block mb-1.5">Amount Paid (₦) *</label>
                <AmountInput className="input" value={payeRemitForm.amount_paid} onChange={(v) => setPayeRemitForm({ ...payeRemitForm, amount_paid: v })} />
              </div>
              <div>
                <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider block mb-1.5">FIRS Reference / Receipt *</label>
                <input className="input" placeholder="e.g. FIRS-PAYE-2024-001234" value={payeRemitForm.reference} onChange={(e) => setPayeRemitForm({ ...payeRemitForm, reference: e.target.value })} />
              </div>
              <div>
                <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider block mb-1.5">Notes</label>
                <textarea className="input resize-none" rows={2} value={payeRemitForm.notes} onChange={(e) => setPayeRemitForm({ ...payeRemitForm, notes: e.target.value })} />
              </div>
            </div>
            <div className="flex gap-3 mt-6">
              <button onClick={() => setShowPayeRemitModal(false)} className="btn-ghost flex-1">Cancel</button>
              <button disabled={savingPayeRemit || !payeRemitForm.reference.trim()} className="btn-primary flex-1 disabled:opacity-50"
                onClick={async () => {
                  if (!remittingPayeId) return
                  setSavingPayeRemit(true)
                  try {
                    await payrollApi.markPayeRemitted(remittingPayeId, { reference: payeRemitForm.reference, amount_paid: parseFloat(payeRemitForm.amount_paid) || 0, notes: payeRemitForm.notes })
                    toast.success('PAYE remittance recorded')
                    setShowPayeRemitModal(false); loadPayeRemittances()
                  } catch { toast.error('Failed to record remittance') }
                  finally { setSavingPayeRemit(false) }
                }}>
                {savingPayeRemit ? 'Saving…' : 'Record Remittance'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Employee Tax Profile Modal */}
      {showTaxProfileModal && taxProfileEmployee && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
          <div className="bg-surface-800 border border-surface-600 rounded-2xl p-6 w-full max-w-lg shadow-2xl">
            <div className="flex items-center justify-between mb-5">
              <div>
                <h2 className="text-lg font-bold text-white">Tax Profile — {taxProfileEmployee.first_name} {taxProfileEmployee.last_name}</h2>
                <p className="text-xs text-slate-500 mt-0.5">Override individual tax relief items used in PAYE computation</p>
              </div>
              <button onClick={() => setShowTaxProfileModal(false)} className="text-slate-400 hover:text-white"><X size={18} /></button>
            </div>
            {loadingTaxProfile ? (
              <div className="py-8 flex justify-center"><Loader2 size={20} className="animate-spin text-brand-400" /></div>
            ) : (
              <div className="space-y-4">
                <div className="p-3 rounded-xl bg-brand-500/5 border border-brand-500/20">
                  <p className="text-xs text-brand-400 font-semibold mb-2">Standard PAYE reliefs (auto-applied to all):</p>
                  <p className="text-xs text-slate-400">Consolidated Relief Allowance: ₦200,000 + 20% of gross · Pension: 8% employee · NHF: 2.5% basic (if enrolled)</p>
                </div>
                <div>
                  <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider block mb-1.5">Voluntary Pension (₦/month)</label>
                  <AmountInput className="input" placeholder="0" value={taxProfileForm.voluntary_pension} onChange={(v) => setTaxProfileForm({ ...taxProfileForm, voluntary_pension: v })} />
                  <p className="text-xs text-slate-500 mt-1">Added to the 8% statutory pension (increases pre-tax deduction)</p>
                </div>
                <div>
                  <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider block mb-1.5">Life Assurance Premium (₦/month)</label>
                  <AmountInput className="input" placeholder="0" value={taxProfileForm.life_assurance_premium} onChange={(v) => setTaxProfileForm({ ...taxProfileForm, life_assurance_premium: v })} />
                </div>
                <div className="flex gap-6">
                  <label className="flex items-center gap-3 cursor-pointer">
                    <input type="checkbox" className="w-4 h-4 accent-orange-500" checked={taxProfileForm.nhf_enrolled} onChange={(e) => setTaxProfileForm({ ...taxProfileForm, nhf_enrolled: e.target.checked })} />
                    <span className="text-sm text-slate-300">NHF enrolled (2.5% basic salary deducted)</span>
                  </label>
                </div>
                <div className="flex gap-6">
                  <label className="flex items-center gap-3 cursor-pointer">
                    <input type="checkbox" className="w-4 h-4 accent-red-500" checked={taxProfileForm.paye_exempt} onChange={(e) => setTaxProfileForm({ ...taxProfileForm, paye_exempt: e.target.checked })} />
                    <span className="text-sm text-slate-300">PAYE Exempt (skip tax computation for this employee)</span>
                  </label>
                </div>
                <div>
                  <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider block mb-1.5">Notes</label>
                  <textarea className="input resize-none" rows={2} placeholder="e.g. Expat with DTA treaty exemption" value={taxProfileForm.notes} onChange={(e) => setTaxProfileForm({ ...taxProfileForm, notes: e.target.value })} />
                </div>
              </div>
            )}
            <div className="flex gap-3 mt-6">
              <button onClick={() => setShowTaxProfileModal(false)} className="btn-ghost flex-1">Cancel</button>
              <button onClick={handleSaveTaxProfile} disabled={savingTaxProfile || loadingTaxProfile} className="btn-primary flex-1 disabled:opacity-50">
                {savingTaxProfile ? 'Saving…' : taxProfile ? 'Save Changes' : 'Create Profile'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Approver Picker Modal ─────────────────────────────────────────── */}
      {approverPickerId && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={() => setApproverPickerId(null)} />
          <div className="relative bg-surface-800 border border-surface-700 rounded-2xl shadow-2xl p-6 w-full max-w-sm space-y-4 z-10">
            <div className="flex items-center justify-between">
              <h3 className="text-white font-semibold flex items-center gap-2"><Users size={16} className="text-amber-400" /> Send for Approval</h3>
              <button onClick={() => setApproverPickerId(null)} className="text-slate-500 hover:text-white"><X size={16} /></button>
            </div>
            <p className="text-sm text-slate-400">Select which admin or owner should review and approve this payroll run.</p>
            {loadingApprovers ? (
              <div className="flex justify-center py-4"><Loader2 size={18} className="animate-spin text-brand-400" /></div>
            ) : approvers.length === 0 ? (
              <p className="text-sm text-slate-500 text-center py-3">No other admins or owners found. You can still submit — any admin can approve.</p>
            ) : (
              <div className="space-y-2">
                {approvers.map((a) => (
                  <label key={a.id} className={`flex items-center gap-3 p-3 rounded-xl border cursor-pointer transition-colors ${selectedApproverId === a.id ? 'border-brand-500/50 bg-brand-500/5' : 'border-surface-600 hover:border-surface-500'}`}>
                    <input type="radio" name="approver" value={a.id} checked={selectedApproverId === a.id}
                      onChange={() => setSelectedApproverId(a.id)} className="text-brand-500" />
                    <div>
                      <p className="text-sm text-white font-medium">{a.name}</p>
                      <p className="text-xs text-slate-500">{a.email} · <span className="capitalize">{a.role}</span></p>
                    </div>
                  </label>
                ))}
              </div>
            )}
            <div className="flex gap-2 pt-2">
              <button onClick={() => setApproverPickerId(null)} className="flex-1 btn-ghost text-sm">Cancel</button>
              <button onClick={handleSubmitForApproval} className="flex-1 btn-primary text-sm flex items-center justify-center gap-1.5">
                <Send size={13} /> Submit
              </button>
            </div>
          </div>
        </div>
      )}
      {/* PAYE Bracket Breakdown Modal */}
      {selectedPayslip && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
          <div className="bg-surface-800 border border-surface-600 rounded-2xl p-6 w-full max-w-lg shadow-2xl">
            <div className="flex items-center justify-between mb-4">
              <div>
                <h2 className="text-lg font-bold text-white">PAYE Bracket Breakdown</h2>
                <p className="text-xs text-slate-400 mt-0.5">{selectedPayslip.employee_name} — Monthly PAYE: <span className="text-red-400 font-mono font-semibold">₦{parseFloat(selectedPayslip.paye_tax).toLocaleString('en-NG', { minimumFractionDigits: 2 })}</span></p>
              </div>
              <button onClick={() => setSelectedPayslip(null)} className="text-slate-400 hover:text-white">
                <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
              </button>
            </div>
            <div className="space-y-2 mb-4">
              <div className="grid grid-cols-3 gap-3">
                <div className="bg-surface-700 rounded-xl p-3">
                  <p className="text-xs text-slate-400 mb-1">Monthly Gross</p>
                  <p className="font-mono text-white font-semibold">₦{parseFloat(selectedPayslip.gross_salary).toLocaleString('en-NG', { minimumFractionDigits: 2 })}</p>
                </div>
                <div className="bg-surface-700 rounded-xl p-3">
                  <p className="text-xs text-slate-400 mb-1">Monthly Taxable</p>
                  <p className="font-mono text-amber-400 font-semibold">₦{parseFloat(selectedPayslip.taxable_income).toLocaleString('en-NG', { minimumFractionDigits: 2 })}</p>
                </div>
                <div className="bg-surface-700 rounded-xl p-3">
                  <p className="text-xs text-slate-400 mb-1">Monthly PAYE</p>
                  <p className="font-mono text-red-400 font-semibold">₦{parseFloat(selectedPayslip.paye_tax).toLocaleString('en-NG', { minimumFractionDigits: 2 })}</p>
                </div>
              </div>
            </div>
            {selectedPayslip.paye_bracket_breakdown && selectedPayslip.paye_bracket_breakdown.length > 0 ? (
              <div className="overflow-hidden rounded-xl border border-surface-600">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="bg-surface-700 text-xs text-slate-400 uppercase tracking-wider">
                      <th className="py-2.5 px-3 text-left">Bracket</th>
                      <th className="py-2.5 px-3 text-center">Rate</th>
                      <th className="py-2.5 px-3 text-right">Annual Tax</th>
                      <th className="py-2.5 px-3 text-right">Monthly Tax</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-surface-700">
                    {selectedPayslip.paye_bracket_breakdown.map((b, i) => (
                      <tr key={i} className="hover:bg-surface-700/50 transition-colors">
                        <td className="py-2.5 px-3 text-slate-300 font-mono text-xs">{b.bracket}</td>
                        <td className="py-2.5 px-3 text-center">
                          <span className="bg-brand-500/10 text-brand-400 px-2 py-0.5 rounded-full text-xs font-semibold">{b.rate}</span>
                        </td>
                        <td className="py-2.5 px-3 text-right font-mono text-slate-300">₦{b.tax_annual.toLocaleString('en-NG', { minimumFractionDigits: 2 })}</td>
                        <td className="py-2.5 px-3 text-right font-mono text-red-400 font-semibold">₦{b.tax_monthly.toLocaleString('en-NG', { minimumFractionDigits: 2 })}</td>
                      </tr>
                    ))}
                  </tbody>
                  <tfoot>
                    <tr className="bg-surface-700/50 border-t border-surface-600">
                      <td colSpan={3} className="py-2.5 px-3 text-right text-xs font-semibold text-slate-300 uppercase">Total Monthly PAYE</td>
                      <td className="py-2.5 px-3 text-right font-mono text-red-400 font-bold">₦{parseFloat(selectedPayslip.paye_tax).toLocaleString('en-NG', { minimumFractionDigits: 2 })}</td>
                    </tr>
                  </tfoot>
                </table>
              </div>
            ) : (
              <p className="text-center text-slate-500 py-6 text-sm">No bracket breakdown available — reload payroll run to refresh.</p>
            )}
            <p className="text-xs text-slate-500 mt-3 text-center">Based on Nigeria PITA progressive brackets. Annualised then divided by 12 for monthly PAYE.</p>
          </div>
        </div>
      )}
    </div>
  )
}

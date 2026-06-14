import { useEffect, useRef, useState } from 'react'
import { useDataRefresh } from '@/hooks/useDataRefresh'
import {
  Plus, X, UsersRound, Loader2, Search, Edit2, ChevronDown, CheckCircle2,
  AlertTriangle, CreditCard, Trash2, Ban, FileText, Upload, Eye, Download, Mail, RefreshCw,
} from 'lucide-react'
import toast from 'react-hot-toast'
import { payrollApi, bypassNextGets } from '@/services/api'
import { formatCurrency, formatAmountInput, stripCommas, formatDate } from '@/lib/utils'
import AmountInput from '@/components/AmountInput'
import type { Employee, EmployeeDocument, EmployeePenalty, EmployeeLoan } from '@/types'
import DateInput from '@/components/DateInput'
import { FieldTooltip } from '@/components/FieldTooltip'
import { usePagination } from '@/hooks/usePagination'
import Pagination from '@/components/Pagination'

interface EmployeeForm {
  first_name: string; last_name: string; email: string; phone: string
  job_title: string; department: string; employment_type: string; hire_date: string
  basic_salary: string; housing_allowance: string; transport_allowance: string
  leave_allowance: string; other_allowances: string
  bank_name: string; account_number: string; account_name: string
  pfa_name: string; pfa_number: string; tin: string
}

interface PenaltyForm { reason: string; amount: string; penalty_date: string }
interface LoanForm {
  principal_amount: string; interest_rate: string; duration_months: string; start_date: string; notes: string
}

const today = new Date().toISOString().split('T')[0]

const BLANK: EmployeeForm = {
  first_name: '', last_name: '', email: '', phone: '',
  job_title: '', department: '', employment_type: 'full_time', hire_date: today,
  basic_salary: '', housing_allowance: '0', transport_allowance: '0',
  leave_allowance: '0', other_allowances: '0',
  bank_name: '', account_number: '', account_name: '',
  pfa_name: '', pfa_number: '', tin: '',
}
const BLANK_PENALTY: PenaltyForm = { reason: '', amount: '', penalty_date: today }
const BLANK_LOAN: LoanForm = { principal_amount: '', interest_rate: '0', duration_months: '12', start_date: today, notes: '' }

type FormTab = 'personal' | 'salary' | 'banking' | 'statutory' | 'penalties' | 'loans' | 'documents'

const DOC_TYPE_LABELS: Record<string, string> = {
  cv: 'CV / Resume', id: 'ID / Passport', certificate: 'Certificate',
  contract: 'Contract', other: 'Other',
}
const DOC_TYPE_BADGE: Record<string, string> = {
  cv: 'badge-blue', id: 'badge-orange', certificate: 'badge-green',
  contract: 'badge-slate', other: 'badge-slate',
}

// Complete list of CBN-licensed banks in Nigeria with Paystack bank codes
const NIGERIAN_BANKS = [
  { name: 'Access Bank', code: '044' },
  { name: 'Carbon (One Finance)', code: '565' },
  { name: 'Citibank Nigeria', code: '023' },
  { name: 'Ecobank Nigeria', code: '050' },
  { name: 'Fidelity Bank', code: '070' },
  { name: 'First Bank of Nigeria', code: '011' },
  { name: 'First City Monument Bank (FCMB)', code: '214' },
  { name: 'Globus Bank', code: '00103' },
  { name: 'Guaranty Trust Bank (GTBank)', code: '058' },
  { name: 'Jaiz Bank', code: '301' },
  { name: 'Keystone Bank', code: '082' },
  { name: 'Kuda Microfinance Bank', code: '090267' },
  { name: 'Lotus Bank', code: '303' },
  { name: 'Moniepoint MFB', code: '50515' },
  { name: 'OPay Digital Services', code: '100004' },
  { name: 'PalmPay', code: '999991' },
  { name: 'Parallex Bank', code: '526' },
  { name: 'Polaris Bank', code: '076' },
  { name: 'Premium Trust Bank', code: '105' },
  { name: 'Providus Bank', code: '101' },
  { name: 'Rubies MFB', code: '125' },
  { name: 'Sparkle MFB', code: '51310' },
  { name: 'Stanbic IBTC Bank', code: '221' },
  { name: 'Standard Chartered Bank', code: '068' },
  { name: 'Sterling Bank', code: '232' },
  { name: 'SunTrust Bank', code: '100' },
  { name: 'Taj Bank', code: '302' },
  { name: 'Titan Trust Bank', code: '102' },
  { name: 'Union Bank of Nigeria', code: '032' },
  { name: 'United Bank for Africa (UBA)', code: '033' },
  { name: 'Unity Bank', code: '215' },
  { name: 'VFD Microfinance Bank', code: '566' },
  { name: 'Wema Bank', code: '035' },
  { name: 'Zenith Bank', code: '057' },
] as const

// ── Loan calculation preview (mirrors backend logic) ───────────────────────────
function calcLoanPreview(lf: LoanForm) {
  const principal = parseFloat(stripCommas(lf.principal_amount)) || 0
  const rate = parseFloat(lf.interest_rate) || 0
  const months = Math.max(1, parseInt(lf.duration_months) || 1)
  const totalRepayable = rate > 0 ? principal * (1 + rate / 100) : principal
  const monthly = totalRepayable / months
  return { totalRepayable, monthly, interest: totalRepayable - principal }
}

export default function EmployeesPage() {
  const [employees, setEmployees] = useState<Employee[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')

  const [showModal, setShowModal] = useState(false)
  const [editId, setEditId] = useState<string | null>(null)
  const [form, setForm] = useState<EmployeeForm>(BLANK)
  const [formTab, setFormTab] = useState<FormTab>('personal')
  const [saving, setSaving] = useState(false)

  // Bank combobox state
  const [bankSearch, setBankSearch] = useState('')
  const [bankOpen, setBankOpen] = useState(false)
  const [bankCode, setBankCode] = useState('')
  const [resolving, setResolving] = useState(false)
  const bankRef = useRef<HTMLDivElement>(null)

  // Penalties state
  const [penalties, setPenalties] = useState<EmployeePenalty[]>([])
  const [penaltiesLoading, setPenaltiesLoading] = useState(false)
  const [penaltyForm, setPenaltyForm] = useState<PenaltyForm>(BLANK_PENALTY)
  const [savingPenalty, setSavingPenalty] = useState(false)

  // Loans state
  const [loans, setLoans] = useState<EmployeeLoan[]>([])
  const [loansLoading, setLoansLoading] = useState(false)
  const [loanForm, setLoanForm] = useState<LoanForm>(BLANK_LOAN)
  const [savingLoan, setSavingLoan] = useState(false)

  // Documents state
  const [documents, setDocuments] = useState<EmployeeDocument[]>([])
  const [docsLoading, setDocsLoading] = useState(false)
  const [uploadingDoc, setUploadingDoc] = useState(false)
  const [docName, setDocName] = useState('')
  const [docType, setDocType] = useState('other')
  const [docFile, setDocFile] = useState<File | null>(null)
  const [viewingDoc, setViewingDoc] = useState<EmployeeDocument | null>(null)
  const docFileRef = useRef<HTMLInputElement>(null)

  const load = async () => {
    setLoading(true)
    try {
      const params: Record<string, string> = {}
      if (search) params.search = search
      const { data } = await payrollApi.employees({ ...params, page_size: 5000 })
      setEmployees(data.results ?? data)
    } catch { toast.error('Failed to load employees') }
    finally { setLoading(false) }
  }

  useEffect(() => { load() }, [search])
  useDataRefresh(load)

  // Load penalties / loans when tab is activated on an existing employee
  useEffect(() => {
    if (!editId) return
    if (formTab === 'penalties') {
      setPenaltiesLoading(true)
      payrollApi.penalties(editId)
        .then(({ data }) => setPenalties(data.results ?? data))
        .catch(() => toast.error('Failed to load penalties'))
        .finally(() => setPenaltiesLoading(false))
    }
    if (formTab === 'loans') {
      setLoansLoading(true)
      payrollApi.loans(editId)
        .then(({ data }) => setLoans(data.results ?? data))
        .catch(() => toast.error('Failed to load loans'))
        .finally(() => setLoansLoading(false))
    }
    if (formTab === 'documents') {
      loadDocs()
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [formTab, editId])

  const gross = (f: EmployeeForm) =>
    (parseFloat(stripCommas(f.basic_salary)) || 0) +
    (parseFloat(stripCommas(f.housing_allowance)) || 0) +
    (parseFloat(stripCommas(f.transport_allowance)) || 0) +
    (parseFloat(stripCommas(f.leave_allowance)) || 0) +
    (parseFloat(stripCommas(f.other_allowances)) || 0)

  const openCreate = () => {
    setEditId(null); setForm(BLANK); setFormTab('personal')
    setBankSearch(''); setBankCode(''); setBankOpen(false)
    setPenalties([]); setLoans([]); setDocuments([])
    setPenaltyForm(BLANK_PENALTY); setLoanForm(BLANK_LOAN)
    setDocName(''); setDocType('other'); setDocFile(null)
    setShowModal(true)
  }

  const openEdit = (e: Employee) => {
    setEditId(e.id)
    setForm({
      first_name: e.first_name, last_name: e.last_name, email: e.email, phone: e.phone,
      job_title: e.job_title, department: e.department, employment_type: e.employment_type, hire_date: e.hire_date,
      basic_salary: formatAmountInput(e.basic_salary), housing_allowance: formatAmountInput(e.housing_allowance),
      transport_allowance: formatAmountInput(e.transport_allowance),
      leave_allowance: formatAmountInput(e.leave_allowance), other_allowances: formatAmountInput(e.other_allowances),
      bank_name: e.bank_name, account_number: e.account_number, account_name: e.account_name,
      pfa_name: e.pfa_name, pfa_number: e.pfa_number, tin: e.tin,
    })
    const matched = NIGERIAN_BANKS.find((b) => b.name === e.bank_name)
    setBankSearch(e.bank_name)
    setBankCode((e as any).bank_code || matched?.code || '')
    setBankOpen(false)
    setPenalties([]); setLoans([]); setDocuments([])
    setPenaltyForm(BLANK_PENALTY); setLoanForm(BLANK_LOAN)
    setDocName(''); setDocType('other'); setDocFile(null)
    setFormTab('personal')
    setShowModal(true)
  }

  const handleSave = async () => {
    if (!form.first_name.trim() || !form.last_name.trim()) { toast.error('Name is required'); return }
    if (!form.basic_salary || parseFloat(stripCommas(form.basic_salary)) <= 0) { toast.error('Basic salary must be > 0'); return }
    setSaving(true)
    try {
      const payload = {
        ...form,
        bank_code: bankCode,
        basic_salary: parseFloat(stripCommas(form.basic_salary)),
        housing_allowance: parseFloat(stripCommas(form.housing_allowance)) || 0,
        transport_allowance: parseFloat(stripCommas(form.transport_allowance)) || 0,
        leave_allowance: parseFloat(stripCommas(form.leave_allowance)) || 0,
        other_allowances: parseFloat(stripCommas(form.other_allowances)) || 0,
      }
      if (editId) { await payrollApi.updateEmployee(editId, payload); toast.success('Employee updated') }
      else { await payrollApi.createEmployee(payload); toast.success('Employee added') }
      setShowModal(false); load()
    } catch { toast.error('Failed to save employee') }
    finally { setSaving(false) }
  }

  // ── Penalty handlers ────────────────────────────────────────────────────────
  const handleAddPenalty = async () => {
    if (!penaltyForm.reason.trim()) { toast.error('Reason is required'); return }
    const amount = parseFloat(stripCommas(penaltyForm.amount))
    if (!amount || amount <= 0) { toast.error('Amount must be > 0'); return }
    setSavingPenalty(true)
    try {
      await payrollApi.createPenalty({
        employee: editId,
        reason: penaltyForm.reason,
        amount,
        penalty_date: penaltyForm.penalty_date,
      })
      toast.success('Penalty added')
      setPenaltyForm(BLANK_PENALTY)
      const { data } = await payrollApi.penalties(editId!)
      setPenalties(data.results ?? data)
    } catch { toast.error('Failed to add penalty') }
    finally { setSavingPenalty(false) }
  }

  const handleWaivePenalty = async (id: string) => {
    try {
      await payrollApi.waivePenalty(id)
      toast.success('Penalty waived')
      const { data } = await payrollApi.penalties(editId!)
      setPenalties(data.results ?? data)
    } catch { toast.error('Failed to waive') }
  }

  const handleDeletePenalty = async (id: string) => {
    if (!confirm('Delete this penalty?')) return
    try {
      await payrollApi.deletePenalty(id)
      setPenalties((p) => p.filter((x) => x.id !== id))
    } catch { toast.error('Failed to delete') }
  }

  // ── Loan handlers ────────────────────────────────────────────────────────────
  const handleAddLoan = async () => {
    const principal = parseFloat(stripCommas(loanForm.principal_amount))
    const months = parseInt(loanForm.duration_months)
    if (!principal || principal <= 0) { toast.error('Principal must be > 0'); return }
    if (!months || months < 1) { toast.error('Duration must be at least 1 month'); return }
    setSavingLoan(true)
    try {
      await payrollApi.createLoan({
        employee: editId,
        principal_amount: principal,
        interest_rate: parseFloat(loanForm.interest_rate) || 0,
        duration_months: months,
        start_date: loanForm.start_date,
        notes: loanForm.notes,
      })
      toast.success('Loan recorded')
      setLoanForm(BLANK_LOAN)
      const { data } = await payrollApi.loans(editId!)
      setLoans(data.results ?? data)
    } catch { toast.error('Failed to add loan') }
    finally { setSavingLoan(false) }
  }

  // ── Document handlers ────────────────────────────────────────────────────────
  const loadDocs = async () => {
    if (!editId) return
    setDocsLoading(true)
    try {
      const { data } = await payrollApi.documents(editId)
      setDocuments(data.results ?? data)
    } catch { toast.error('Failed to load documents') }
    finally { setDocsLoading(false) }
  }

  const handleUploadDoc = async () => {
    if (!docFile) { toast.error('Select a file first'); return }
    if (!docName.trim()) { toast.error('Document name is required'); return }
    setUploadingDoc(true)
    try {
      await payrollApi.uploadDocument(docFile, {
        employee: editId!,
        name: docName.trim(),
        document_type: docType,
      })
      toast.success('Document uploaded')
      setDocName(''); setDocType('other'); setDocFile(null)
      if (docFileRef.current) docFileRef.current.value = ''
      await loadDocs()
    } catch { toast.error('Failed to upload document') }
    finally { setUploadingDoc(false) }
  }

  const handleDeleteDoc = async (id: string) => {
    if (!confirm('Delete this document?')) return
    try {
      await payrollApi.deleteDocument(id)
      setDocuments((d) => d.filter((x) => x.id !== id))
      toast.success('Document deleted')
    } catch { toast.error('Failed to delete') }
  }

  const handleDownloadDoc = (doc: EmployeeDocument) => {
    if (!doc.file_url) return
    const a = document.createElement('a')
    a.href = doc.file_url
    a.download = doc.name
    a.target = '_blank'
    a.click()
  }

  const handleEmailDoc = (doc: EmployeeDocument) => {
    if (!doc.file_url) return
    const subject = encodeURIComponent(`Document: ${doc.name}`)
    const body = encodeURIComponent(`Please find the document "${doc.name}" at:\n${doc.file_url}`)
    window.open(`mailto:?subject=${subject}&body=${body}`)
  }

  const handleCancelLoan = async (id: string) => {
    if (!confirm('Cancel this loan? No further deductions will be made.')) return
    try {
      await payrollApi.cancelLoan(id)
      toast.success('Loan cancelled')
      const { data } = await payrollApi.loans(editId!)
      setLoans(data.results ?? data)
    } catch { toast.error('Failed to cancel') }
  }

  // ── Bank combobox ────────────────────────────────────────────────────────────
  useEffect(() => {
    if (form.account_number.length !== 10 || !bankCode) return
    let cancelled = false
    const resolve = async () => {
      setResolving(true)
      try {
        const { data } = await payrollApi.resolveAccount(form.account_number, bankCode)
        if (!cancelled) setForm((f) => ({ ...f, account_name: data.account_name }))
      } catch (err: any) {
        if (!cancelled) toast.error(err?.response?.data?.error ?? 'Could not verify account — enter name manually', { duration: 4000 })
      } finally {
        if (!cancelled) setResolving(false)
      }
    }
    resolve()
    return () => { cancelled = true }
  }, [form.account_number, bankCode])

  const selectBank = (bank: { name: string; code: string }) => {
    setForm((f) => ({ ...f, bank_name: bank.name }))
    setBankCode(bank.code); setBankSearch(bank.name); setBankOpen(false)
  }

  const filteredBanks = NIGERIAN_BANKS.filter((b) => b.name.toLowerCase().includes(bankSearch.toLowerCase()))

  const handleDeactivate = async (e: Employee) => {
    if (!confirm(`Deactivate ${e.full_name}?`)) return
    try {
      await payrollApi.updateEmployee(e.id, { is_active: false })
      toast.success('Employee deactivated'); load()
    } catch { toast.error('Failed to deactivate') }
  }

  const handleDelete = async (e: Employee) => {
    if (!confirm(`Permanently delete ${e.full_name}? This will remove all their records and cannot be undone.`)) return
    try {
      await payrollApi.deleteEmployee(e.id)
      toast.success('Employee deleted'); load()
    } catch { toast.error('Failed to delete employee') }
  }

  const { page: empPage, setPage: setEmpPage, pageSize: empPageSize, setPageSize: setEmpPageSize, totalPages: empTotalPages, paged: pagedEmployees, total: empTotal } = usePagination(employees)

  const totalEmployees = employees.length
  const active = employees.filter((e) => e.is_active).length
  const contracted = employees.filter((e) => e.employment_type === 'contract').length
  const totalGross = employees.filter((e) => e.is_active).reduce((s, e) => s + parseFloat(e.gross_salary), 0)

  const EMP_TYPE_BADGE: Record<string, string> = {
    full_time: 'badge-green', part_time: 'badge-blue', contract: 'badge-orange',
  }

  const FORM_TABS: { id: FormTab; label: string }[] = [
    { id: 'personal', label: 'Personal' },
    { id: 'salary', label: 'Salary' },
    { id: 'banking', label: 'Banking' },
    { id: 'statutory', label: 'Statutory' },
    { id: 'penalties', label: 'Penalties' },
    { id: 'loans', label: 'Loans' },
    { id: 'documents', label: 'Documents' },
  ]

  // Loan preview
  const loanPreview = calcLoanPreview(loanForm)

  const PENALTY_STATUS_COLOR: Record<string, string> = {
    pending: 'badge-orange', applied: 'badge-green', waived: 'badge-slate',
  }
  const LOAN_STATUS_COLOR: Record<string, string> = {
    active: 'badge-blue', settled: 'badge-green', cancelled: 'badge-slate',
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white">Employees</h1>
          <p className="text-slate-400 text-sm">{totalEmployees} total employees</p>
        </div>
        <div className="flex items-center gap-2 sm:ml-auto">
          <button onClick={() => { bypassNextGets(); load() }} disabled={loading} className="btn-ghost p-2 text-slate-400 hover:text-white" title="Refresh">
            <RefreshCw size={16} className={loading ? 'animate-spin' : ''} />
          </button>
          <button className="btn-primary" onClick={openCreate}>
            <Plus size={16} /> Add Employee
          </button>
        </div>
      </div>

      {/* Summary */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="card p-5"><p className="text-xs text-slate-400">Total Employees</p><p className="text-xl font-bold text-white mt-1">{totalEmployees}</p></div>
        <div className="card p-5"><p className="text-xs text-slate-400">Active</p><p className="text-xl font-bold text-emerald-400 mt-1">{active}</p></div>
        <div className="card p-5"><p className="text-xs text-slate-400">On Contract</p><p className="text-xl font-bold text-orange-400 mt-1">{contracted}</p></div>
        <div className="card p-5"><p className="text-xs text-slate-400">Total Monthly Gross</p><p className="text-xl font-bold text-brand-400 mt-1">{formatCurrency(String(totalGross))}</p></div>
      </div>

      {/* Search */}
      <div className="relative max-w-xs">
        <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
        <input className="input pl-9" placeholder="Search name/department…" value={search} onChange={(e) => setSearch(e.target.value)} />
      </div>

      {/* Table */}
      <div className="card p-0 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-surface-700">
                {['Employee ID', 'Name', 'Department', 'Job Title', 'Type', 'Gross Salary', 'Status', 'Actions'].map((h) => (
                  <th key={h} className="px-4 py-3.5 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading ? (
                Array.from({ length: 6 }).map((_, i) => (
                  <tr key={i} className="table-row">
                    {Array.from({ length: 8 }).map((_, j) => (
                      <td key={j} className="px-4 py-3.5"><div className="h-4 bg-surface-700 rounded animate-pulse w-16" /></td>
                    ))}
                  </tr>
                ))
              ) : empTotal === 0 ? (
                <tr>
                  <td colSpan={8} className="px-4 py12 text-center">
                    <UsersRound size={32} className="mx-auto mb-2 text-slate-600" />
                    <p className="text-slate-500">No employees yet</p>
                  </td>
                </tr>
              ) : pagedEmployees.map((e) => (
                <tr key={e.id} className="table-row">
                  <td className="px-4 py-3.5 font-mono text-slate-400">{e.employee_id}</td>
                  <td className="px-4 py-3.5 text-white font-medium">{e.full_name}</td>
                  <td className="px-4 py-3.5 text-slate-400">{e.department || '—'}</td>
                  <td className="px-4 py-3.5 text-slate-400">{e.job_title || '—'}</td>
                  <td className="px-4 py-3.5"><span className={EMP_TYPE_BADGE[e.employment_type] ?? 'badge-slate'}>{e.employment_type.replace('_', ' ')}</span></td>
                  <td className="px-4 py-3.5 font-mono text-white">{formatCurrency(e.gross_salary)}</td>
                  <td className="px-4 py-3.5">{e.is_active ? <span className="badge-green">Active</span> : <span className="badge-slate">Inactive</span>}</td>
                  <td className="px-4 py-3.5">
                    <div className="flex items-center gap-1.5">
                      <button onClick={() => openEdit(e)} className="p-1.5 text-slate-500 hover:text-white hover:bg-surface-600 rounded-lg transition-colors"><Edit2 size={14} /></button>
                      {e.is_active && (
                        <button onClick={() => handleDeactivate(e)} className="text-xs px-2.5 py-1 rounded-lg bg-red-500/10 text-red-400 hover:bg-red-500/20 transition-colors">Deactivate</button>
                      )}
                      <button onClick={() => handleDelete(e)} className="p-1.5 text-slate-600 hover:text-red-400 hover:bg-red-500/10 rounded-lg transition-colors" title="Delete employee permanently"><Trash2 size={14} /></button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <Pagination page={empPage} totalPages={empTotalPages} pageSize={empPageSize} total={empTotal} onPage={setEmpPage} onPageSize={setEmpPageSize} />
      </div>

      {/* Employee Modal */}
      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={() => setShowModal(false)} />
          <div className="relative card w-full max-w-2xl p-6 space-y-5 overflow-y-auto max-h-[90vh]">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-bold text-white">{editId ? 'Edit Employee' : 'Add Employee'}</h2>
              <button onClick={() => setShowModal(false)} className="text-slate-400 hover:text-white"><X size={20} /></button>
            </div>

            {/* Form tabs */}
            <div className="flex flex-wrap gap-1 p-1 bg-surface-900 rounded-xl">
              {FORM_TABS
                .filter((t) => editId || !['penalties', 'loans', 'documents'].includes(t.id))
                .map((t) => (
                  <button key={t.id} onClick={() => setFormTab(t.id)}
                    className={`flex-1 min-w-[70px] py-1.5 rounded-lg text-xs font-medium transition-all ${formTab === t.id ? 'bg-brand-500 text-white' : 'text-slate-400 hover:text-white'}`}>
                    {t.label}
                  </button>
                ))}
            </div>

            {/* ── Personal ── */}
            {formTab === 'personal' && (
              <div className="grid grid-cols-2 gap-4">
                <div><label className="text-xs text-slate-400 mb-1 block flex items-center gap-1">First Name *<FieldTooltip text="Employee's full legal name as it appears on their employment contract." /></label><input className="input" value={form.first_name} onChange={(e) => setForm({ ...form, first_name: e.target.value })} /></div>
                <div><label className="text-xs text-slate-400 mb-1 block flex items-center gap-1">Last Name *<FieldTooltip text="Employee's full legal name as it appears on their employment contract." /></label><input className="input" value={form.last_name} onChange={(e) => setForm({ ...form, last_name: e.target.value })} /></div>
                <div><label className="text-xs text-slate-400 mb-1 block flex items-center gap-1">Email<FieldTooltip text="Employee's work email — used for payslip delivery." /></label><input type="email" className="input" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></div>
                <div><label className="text-xs text-slate-400 mb-1 block flex items-center gap-1">Phone<FieldTooltip text="Employee's contact number." /></label><input className="input" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} /></div>
                <div><label className="text-xs text-slate-400 mb-1 block flex items-center gap-1">Job Title<FieldTooltip text="The employee's role or position in your company." /></label><input className="input" value={form.job_title} onChange={(e) => setForm({ ...form, job_title: e.target.value })} /></div>
                <div><label className="text-xs text-slate-400 mb-1 block flex items-center gap-1">Department<FieldTooltip text="Which team or department this employee belongs to — e.g. Sales, Operations, Finance." /></label><input className="input" value={form.department} onChange={(e) => setForm({ ...form, department: e.target.value })} /></div>
                <div>
                  <label className="text-xs text-slate-400 mb-1 block flex items-center gap-1">Employment Type<FieldTooltip text="Whether this is a full-time permanent employee, part-time, or a contractor." /></label>
                  <select className="input" value={form.employment_type} onChange={(e) => setForm({ ...form, employment_type: e.target.value })}>
                    <option value="full_time">Full Time</option>
                    <option value="part_time">Part Time</option>
                    <option value="contract">Contract</option>
                  </select>
                </div>
                <div><label className="text-xs text-slate-400 mb-1 block flex items-center gap-1">Hire Date<FieldTooltip text="The date this employee joined your company. Used to calculate tenure." /></label><DateInput value={form.hire_date} onChange={(v) => setForm({ ...form, hire_date: v })} /></div>
              </div>
            )}

            {/* ── Salary ── */}
            {formTab === 'salary' && (
              <div className="space-y-4">
                <div className="grid grid-cols-2 gap-4">
                  <div><label className="text-xs text-slate-400 mb-1 block flex items-center gap-1">Basic Salary *<FieldTooltip text="The employee's total monthly pay before any deductions like tax (PAYE) or pension." /></label><AmountInput className="input" value={form.basic_salary} onChange={(v) => setForm({ ...form, basic_salary: v })} /></div>
                  <div><label className="text-xs text-slate-400 mb-1 block">Housing Allowance</label><AmountInput className="input" value={form.housing_allowance} onChange={(v) => setForm({ ...form, housing_allowance: v })} /></div>
                  <div><label className="text-xs text-slate-400 mb-1 block">Transport Allowance</label><AmountInput className="input" value={form.transport_allowance} onChange={(v) => setForm({ ...form, transport_allowance: v })} /></div>
                  <div><label className="text-xs text-slate-400 mb-1 block">Leave Allowance</label><AmountInput className="input" value={form.leave_allowance} onChange={(v) => setForm({ ...form, leave_allowance: v })} /></div>
                  <div className="col-span-2"><label className="text-xs text-slate-400 mb-1 block">Other Allowances</label><AmountInput className="input" value={form.other_allowances} onChange={(v) => setForm({ ...form, other_allowances: v })} /></div>
                </div>
                <div className="p-3 bg-brand-500/10 border border-brand-500/20 rounded-xl">
                  <p className="text-xs text-slate-400">Computed Gross Salary</p>
                  <p className="text-xl font-bold text-brand-400">{formatCurrency(String(gross(form)))}</p>
                </div>
              </div>
            )}

            {/* ── Banking ── */}
            {formTab === 'banking' && (
              <div className="grid grid-cols-2 gap-4">
                <div className="col-span-2" ref={bankRef}>
                  <label className="text-xs text-slate-400 mb-1 block flex items-center gap-1">Bank Name<FieldTooltip text="Employee's bank details where their salary will be transferred. Keep this accurate." /></label>
                  <div className="relative">
                    <input className="input pr-9" placeholder="Search bank…" value={bankSearch}
                      onChange={(e) => { setBankSearch(e.target.value); setBankOpen(true); if (e.target.value !== form.bank_name) { setForm((f) => ({ ...f, bank_name: '' })); setBankCode('') } }}
                      onFocus={() => setBankOpen(true)} onBlur={() => setTimeout(() => setBankOpen(false), 180)} autoComplete="off" />
                    <ChevronDown size={15} className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 pointer-events-none" />
                    {bankOpen && filteredBanks.length > 0 && (
                      <div className="absolute z-30 top-full left-0 right-0 mt-1 bg-surface-800 border border-surface-600 rounded-xl shadow-2xl max-h-52 overflow-y-auto">
                        {filteredBanks.map((b) => (
                          <button key={b.code} type="button" onMouseDown={(e) => e.preventDefault()} onClick={() => selectBank(b)}
                            className={`w-full text-left px-3 py-2.5 text-sm transition-colors flex items-center justify-between ${form.bank_name === b.name ? 'bg-brand-500/20 text-brand-300' : 'text-slate-200 hover:bg-surface-700'}`}>
                            {b.name}{form.bank_name === b.name && <CheckCircle2 size={14} className="text-brand-400 shrink-0" />}
                          </button>
                        ))}
                      </div>
                    )}
                    {bankOpen && bankSearch && filteredBanks.length === 0 && (
                      <div className="absolute z-30 top-full left-0 right-0 mt-1 bg-surface-800 border border-surface-600 rounded-xl shadow-2xl px-3 py-3 text-sm text-slate-500">No banks match "{bankSearch}"</div>
                    )}
                  </div>
                </div>
                <div>
                  <label className="text-xs text-slate-400 mb-1 block flex items-center gap-1">Account Number<FieldTooltip text="Employee's bank account number where their salary will be transferred. Keep this accurate." /></label>
                  <input className="input" placeholder="10-digit NUBAN" maxLength={10} value={form.account_number}
                    onChange={(e) => { const val = e.target.value.replace(/\D/g, '').slice(0, 10); setForm((f) => ({ ...f, account_number: val, account_name: val.length < 10 ? '' : f.account_name })) }} />
                </div>
                <div>
                  <label className="text-xs text-slate-400 mb-1 block flex items-center gap-1.5">
                    Account Name {resolving && <Loader2 size={11} className="animate-spin text-brand-400" />}
                  </label>
                  <input className="input" placeholder={resolving ? 'Resolving…' : 'Auto-filled or type manually'} value={form.account_name}
                    onChange={(e) => setForm((f) => ({ ...f, account_name: e.target.value }))} readOnly={resolving} />
                </div>
              </div>
            )}

            {/* ── Statutory ── */}
            {formTab === 'statutory' && (
              <div className="grid grid-cols-2 gap-4">
                <div><label className="text-xs text-slate-400 mb-1 block flex items-center gap-1">PFA Name<FieldTooltip text="The pension fund administrator managing this employee's retirement contributions." /></label><input className="input" placeholder="e.g. ARM Pension" value={form.pfa_name} onChange={(e) => setForm({ ...form, pfa_name: e.target.value })} /></div>
                <div><label className="text-xs text-slate-400 mb-1 block">PFA Number (RSA PIN)</label><input className="input" value={form.pfa_number} onChange={(e) => setForm({ ...form, pfa_number: e.target.value })} /></div>
                <div className="col-span-2"><label className="text-xs text-slate-400 mb-1 block flex items-center gap-1">TIN (Tax ID)<FieldTooltip text="Employee's Tax Identification Number issued by FIRS. Required for accurate PAYE remittance." /></label><input className="input" placeholder="FIRS Tax Identification Number" value={form.tin} onChange={(e) => setForm({ ...form, tin: e.target.value })} /></div>
              </div>
            )}

            {/* ── Penalties (edit only) ── */}
            {formTab === 'penalties' && editId && (
              <div className="space-y-5">
                {/* Add form */}
                <div className="p-4 bg-red-500/5 border border-red-500/20 rounded-xl space-y-3">
                  <p className="text-sm font-semibold text-red-400 flex items-center gap-2"><AlertTriangle size={14} /> Add Penalty Deduction</p>
                  <div className="grid grid-cols-2 gap-3">
                    <div className="col-span-2">
                      <label className="text-xs text-slate-400 mb-1 block">Reason *</label>
                      <input className="input" placeholder="e.g. Late arrival, Equipment damage" value={penaltyForm.reason} onChange={(e) => setPenaltyForm({ ...penaltyForm, reason: e.target.value })} />
                    </div>
                    <div>
                      <label className="text-xs text-slate-400 mb-1 block">Amount (₦) *</label>
                      <AmountInput className="input" value={penaltyForm.amount} onChange={(v) => setPenaltyForm({ ...penaltyForm, amount: v })} />
                    </div>
                    <div>
                      <label className="text-xs text-slate-400 mb-1 block">Penalty Date</label>
                      <DateInput value={penaltyForm.penalty_date} onChange={(v) => setPenaltyForm({ ...penaltyForm, penalty_date: v })} />
                    </div>
                  </div>
                  <button className="btn-primary text-sm py-2 w-full justify-center disabled:opacity-50" onClick={handleAddPenalty} disabled={savingPenalty}>
                    {savingPenalty ? <Loader2 size={14} className="animate-spin" /> : <><Plus size={14} /> Add Penalty</>}
                  </button>
                </div>

                {/* List */}
                {penaltiesLoading ? (
                  <div className="flex justify-center py-6"><Loader2 size={20} className="animate-spin text-slate-500" /></div>
                ) : penalties.length === 0 ? (
                  <p className="text-center text-slate-500 text-sm py-4">No penalties recorded for this employee.</p>
                ) : (
                  <div className="space-y-2">
                    <p className="text-xs text-slate-400 font-semibold uppercase tracking-wider">Recorded Penalties</p>
                    {penalties.map((p) => (
                      <div key={p.id} className="flex items-center justify-between p-3 bg-surface-800 rounded-xl border border-surface-700">
                        <div>
                          <p className="text-sm text-white font-medium">{p.reason}</p>
                          <p className="text-xs text-slate-500 mt-0.5">{formatDate(p.penalty_date)} · {formatCurrency(p.amount)}</p>
                        </div>
                        <div className="flex items-center gap-2">
                          <span className={PENALTY_STATUS_COLOR[p.status] ?? 'badge-slate'}>{p.status}</span>
                          {p.status === 'pending' && (
                            <>
                              <button onClick={() => handleWaivePenalty(p.id)} className="p-1.5 text-slate-500 hover:text-amber-400 hover:bg-amber-400/10 rounded-lg transition-colors" title="Waive"><Ban size={13} /></button>
                              <button onClick={() => handleDeletePenalty(p.id)} className="p-1.5 text-slate-500 hover:text-red-400 hover:bg-red-400/10 rounded-lg transition-colors" title="Delete"><Trash2 size={13} /></button>
                            </>
                          )}
                        </div>
                      </div>
                    ))}
                    <div className="p-3 bg-surface-900 rounded-xl text-xs text-slate-400">
                      <span className="font-semibold text-white">
                        Pending total: {formatCurrency(String(penalties.filter(p => p.status === 'pending').reduce((s, p) => s + parseFloat(p.amount), 0)))}
                      </span>
                      {' '}— will be deducted from next payroll run
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* ── Loans (edit only) ── */}
            {formTab === 'loans' && editId && (
              <div className="space-y-5">
                {/* Add form */}
                <div className="p-4 bg-blue-500/5 border border-blue-500/20 rounded-xl space-y-3">
                  <p className="text-sm font-semibold text-blue-400 flex items-center gap-2"><CreditCard size={14} /> Record Employee Loan</p>
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="text-xs text-slate-400 mb-1 block">Principal Amount (₦) *</label>
                      <AmountInput className="input" value={loanForm.principal_amount} onChange={(v) => setLoanForm({ ...loanForm, principal_amount: v })} />
                    </div>
                    <div>
                      <label className="text-xs text-slate-400 mb-1 block">Interest Rate (%) <span className="text-slate-600">— 0 = interest-free</span></label>
                      <input type="text" inputMode="decimal" className="input" placeholder="0" value={loanForm.interest_rate} onChange={(e) => setLoanForm({ ...loanForm, interest_rate: e.target.value })} />
                    </div>
                    <div>
                      <label className="text-xs text-slate-400 mb-1 block">Repayment Duration (months) *</label>
                      <input type="text" inputMode="numeric" className="input" placeholder="12" value={loanForm.duration_months} onChange={(e) => setLoanForm({ ...loanForm, duration_months: e.target.value })} />
                    </div>
                    <div>
                      <label className="text-xs text-slate-400 mb-1 block">Start Date</label>
                      <DateInput value={loanForm.start_date} onChange={(v) => setLoanForm({ ...loanForm, start_date: v })} />
                    </div>
                    <div className="col-span-2">
                      <label className="text-xs text-slate-400 mb-1 block">Notes</label>
                      <input className="input" placeholder="Optional notes" value={loanForm.notes} onChange={(e) => setLoanForm({ ...loanForm, notes: e.target.value })} />
                    </div>
                  </div>

                  {/* Live preview */}
                  {parseFloat(stripCommas(loanForm.principal_amount)) > 0 && (
                    <div className="grid grid-cols-3 gap-2 text-center">
                      <div className="p-2 bg-surface-800 rounded-lg">
                        <p className="text-[10px] text-slate-500">Total Repayable</p>
                        <p className="text-sm font-bold text-white">{formatCurrency(String(loanPreview.totalRepayable))}</p>
                      </div>
                      <div className="p-2 bg-surface-800 rounded-lg">
                        <p className="text-[10px] text-slate-500">Monthly Deduction</p>
                        <p className="text-sm font-bold text-brand-400">{formatCurrency(String(loanPreview.monthly))}</p>
                      </div>
                      <div className="p-2 bg-surface-800 rounded-lg">
                        <p className="text-[10px] text-slate-500">Total Interest</p>
                        <p className="text-sm font-bold text-amber-400">{formatCurrency(String(loanPreview.interest))}</p>
                      </div>
                    </div>
                  )}

                  <button className="btn-primary text-sm py-2 w-full justify-center disabled:opacity-50" onClick={handleAddLoan} disabled={savingLoan}>
                    {savingLoan ? <Loader2 size={14} className="animate-spin" /> : <><Plus size={14} /> Record Loan</>}
                  </button>
                </div>

                {/* List */}
                {loansLoading ? (
                  <div className="flex justify-center py-6"><Loader2 size={20} className="animate-spin text-slate-500" /></div>
                ) : loans.length === 0 ? (
                  <p className="text-center text-slate-500 text-sm py-4">No loans recorded for this employee.</p>
                ) : (
                  <div className="space-y-2">
                    <p className="text-xs text-slate-400 font-semibold uppercase tracking-wider">Loan History</p>
                    {loans.map((loan) => {
                      const pct = parseFloat(loan.total_repayable) > 0
                        ? Math.min(100, (parseFloat(loan.amount_repaid) / parseFloat(loan.total_repayable)) * 100)
                        : 0
                      return (
                        <div key={loan.id} className="p-3 bg-surface-800 rounded-xl border border-surface-700 space-y-2">
                          <div className="flex items-start justify-between">
                            <div>
                              <p className="text-sm text-white font-medium">{formatCurrency(loan.principal_amount)} loan</p>
                              <p className="text-xs text-slate-500 mt-0.5">
                                Started {formatDate(loan.start_date)} · {loan.duration_months}m ·{' '}
                                {parseFloat(loan.interest_rate) > 0 ? `${loan.interest_rate}% interest` : 'Interest-free'}
                              </p>
                            </div>
                            <div className="flex items-center gap-2">
                              <span className={LOAN_STATUS_COLOR[loan.status] ?? 'badge-slate'}>{loan.status}</span>
                              {loan.status === 'active' && (
                                <button onClick={() => handleCancelLoan(loan.id)} className="p-1.5 text-slate-500 hover:text-red-400 hover:bg-red-400/10 rounded-lg transition-colors" title="Cancel loan"><Ban size={13} /></button>
                              )}
                            </div>
                          </div>
                          {/* Repayment progress */}
                          <div>
                            <div className="flex justify-between text-[10px] text-slate-500 mb-1">
                              <span>Repaid: {formatCurrency(loan.amount_repaid)}</span>
                              <span>Balance: {formatCurrency(loan.balance_remaining)}</span>
                            </div>
                            <div className="h-1.5 bg-surface-700 rounded-full overflow-hidden">
                              <div className="h-full bg-brand-500 rounded-full transition-all" style={{ width: `${pct}%` }} />
                            </div>
                            <p className="text-right text-[10px] text-slate-600 mt-0.5">{pct.toFixed(0)}% repaid · Monthly: {formatCurrency(loan.monthly_installment)}</p>
                          </div>
                          {loan.notes && <p className="text-xs text-slate-500 italic">{loan.notes}</p>}
                        </div>
                      )
                    })}
                  </div>
                )}
              </div>
            )}

            {/* ── Documents (edit only) ── */}
            {formTab === 'documents' && editId && (
              <div className="space-y-5">
                {/* Upload form */}
                <div className="p-4 bg-surface-800 border border-surface-700 rounded-xl space-y-3">
                  <p className="text-sm font-semibold text-white flex items-center gap-2"><Upload size={14} className="text-brand-400" /> Upload Document</p>
                  <div className="grid grid-cols-2 gap-3">
                    <div className="col-span-2">
                      <label className="text-xs text-slate-400 mb-1 block">Document Name *</label>
                      <input className="input" placeholder="e.g. National ID Card, BSc Certificate" value={docName} onChange={(e) => setDocName(e.target.value)} />
                    </div>
                    <div>
                      <label className="text-xs text-slate-400 mb-1 block">Type</label>
                      <select className="input" value={docType} onChange={(e) => setDocType(e.target.value)}>
                        {Object.entries(DOC_TYPE_LABELS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                      </select>
                    </div>
                    <div>
                      <label className="text-xs text-slate-400 mb-1 block">File *</label>
                      <input ref={docFileRef} type="file" accept="*/*" className="hidden" onChange={(e) => setDocFile(e.target.files?.[0] ?? null)} />
                      <button type="button" onClick={() => docFileRef.current?.click()} className="input text-left text-slate-400 hover:text-white flex items-center gap-2 w-full">
                        <FileText size={14} className="shrink-0" />
                        <span className="truncate">{docFile ? docFile.name : 'Choose file…'}</span>
                      </button>
                    </div>
                  </div>
                  <button className="btn-primary text-sm py-2 w-full justify-center disabled:opacity-50" onClick={handleUploadDoc} disabled={uploadingDoc}>
                    {uploadingDoc ? <Loader2 size={14} className="animate-spin" /> : <><Upload size={14} /> Upload</>}
                  </button>
                </div>

                {/* Document list */}
                {docsLoading ? (
                  <div className="flex justify-center py-6"><Loader2 size={20} className="animate-spin text-slate-500" /></div>
                ) : documents.length === 0 ? (
                  <p className="text-center text-slate-500 text-sm py-4">No documents uploaded yet.</p>
                ) : (
                  <div className="space-y-2">
                    <p className="text-xs text-slate-400 font-semibold uppercase tracking-wider">{documents.length} document{documents.length !== 1 ? 's' : ''}</p>
                    {documents.map((doc) => (
                      <div key={doc.id} className="flex items-center justify-between p-3 bg-surface-800 rounded-xl border border-surface-700 gap-3">
                        <div className="flex items-center gap-3 min-w-0">
                          <FileText size={16} className="text-brand-400 shrink-0" />
                          <div className="min-w-0">
                            <p className="text-sm text-white font-medium truncate">{doc.name}</p>
                            <p className="text-xs text-slate-500 mt-0.5">{doc.file_size_display} · {formatDate(doc.created_at)}</p>
                          </div>
                        </div>
                        <div className="flex items-center gap-1 shrink-0">
                          <span className={DOC_TYPE_BADGE[doc.document_type] ?? 'badge-slate'}>{DOC_TYPE_LABELS[doc.document_type]}</span>
                          {doc.file_url && (
                            <>
                              <button onClick={() => setViewingDoc(doc)} className="p-1.5 text-slate-500 hover:text-brand-400 hover:bg-brand-400/10 rounded-lg transition-colors" title="View"><Eye size={14} /></button>
                              <button onClick={() => handleDownloadDoc(doc)} className="p-1.5 text-slate-500 hover:text-white hover:bg-surface-600 rounded-lg transition-colors" title="Download / Save"><Download size={14} /></button>
                              <button onClick={() => handleEmailDoc(doc)} className="p-1.5 text-slate-500 hover:text-white hover:bg-surface-600 rounded-lg transition-colors" title="Share via email"><Mail size={14} /></button>
                            </>
                          )}
                          <button onClick={() => handleDeleteDoc(doc.id)} className="p-1.5 text-slate-500 hover:text-red-400 hover:bg-red-400/10 rounded-lg transition-colors" title="Delete"><Trash2 size={14} /></button>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {/* Save button (only on form tabs) */}
            {!['penalties', 'loans', 'documents'].includes(formTab) && (
              <div className="flex gap-3 pt-1">
                <button className="flex-1 py-2.5 rounded-xl border border-surface-600 text-slate-400 hover:text-white hover:border-surface-500 transition-colors text-sm" onClick={() => setShowModal(false)}>Cancel</button>
                <button className="btn-primary flex-1 py-2.5 justify-center disabled:opacity-50" onClick={handleSave} disabled={saving}>
                  {saving ? <Loader2 size={16} className="animate-spin" /> : editId ? 'Save Changes' : 'Add Employee'}
                </button>
              </div>
            )}
            {['penalties', 'loans', 'documents'].includes(formTab) && (
              <button className="w-full py-2.5 rounded-xl border border-surface-600 text-slate-400 hover:text-white transition-colors text-sm" onClick={() => setShowModal(false)}>Close</button>
            )}
          </div>
        </div>
      )}

      {/* ── Document Viewer Modal ──────────────────────────────────────────── */}
      {viewingDoc && (
        <div className="fixed inset-0 z-[70] flex flex-col">
          <div className="flex items-center justify-between px-4 py-3 bg-surface-900 border-b border-surface-700 shrink-0">
            <div className="flex items-center gap-2 min-w-0">
              <FileText size={15} className="text-brand-400 shrink-0" />
              <span className="text-sm font-medium text-white truncate">{viewingDoc.name}</span>
              <span className={`${DOC_TYPE_BADGE[viewingDoc.document_type] ?? 'badge-slate'} ml-1`}>{DOC_TYPE_LABELS[viewingDoc.document_type]}</span>
            </div>
            <div className="flex items-center gap-2 ml-4 shrink-0">
              <button onClick={() => handleDownloadDoc(viewingDoc)} className="btn-secondary text-xs py-1.5 px-3 flex items-center gap-1.5"><Download size={13} /> Save</button>
              <button onClick={() => handleEmailDoc(viewingDoc)} className="btn-secondary text-xs py-1.5 px-3 flex items-center gap-1.5"><Mail size={13} /> Email</button>
              <button onClick={() => { if (viewingDoc.file_url) { window.open(viewingDoc.file_url, '_blank') } }} className="btn-secondary text-xs py-1.5 px-3 flex items-center gap-1.5"><Eye size={13} /> Open</button>
              <button onClick={() => setViewingDoc(null)} className="p-1.5 text-slate-400 hover:text-white transition-colors"><X size={18} /></button>
            </div>
          </div>
          {viewingDoc.file_url && /\.(png|jpe?g|gif|webp|svg)(\?|$)/i.test(viewingDoc.file_url) ? (
            <div className="flex-1 flex items-center justify-center bg-white p-8">
              <img
                src={viewingDoc.file_url}
                alt={viewingDoc.name}
                className="max-w-full max-h-full object-contain rounded-lg shadow-md"
                style={{ background: '#fff' }}
              />
            </div>
          ) : (
            <iframe
              src={viewingDoc.file_url ?? ''}
              className="flex-1 w-full border-0"
              title={viewingDoc.name}
              style={{ background: '#fff' }}
            />
          )}
        </div>
      )}
    </div>
  )
}

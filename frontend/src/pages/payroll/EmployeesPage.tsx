import { useEffect, useRef, useState } from 'react'
import { Plus, X, UsersRound, Loader2, Search, Edit2, ChevronDown, CheckCircle2 } from 'lucide-react'
import toast from 'react-hot-toast'
import { payrollApi } from '@/services/api'
import { formatCurrency, formatAmountInput, stripCommas } from '@/lib/utils'
import type { Employee } from '@/types'

interface EmployeeForm {
  first_name: string; last_name: string; email: string; phone: string
  job_title: string; department: string; employment_type: string; hire_date: string
  basic_salary: string; housing_allowance: string; transport_allowance: string
  leave_allowance: string; other_allowances: string
  bank_name: string; account_number: string; account_name: string
  pfa_name: string; pfa_number: string; tin: string
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

type FormTab = 'personal' | 'salary' | 'banking' | 'statutory'

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

  const load = async () => {
    setLoading(true)
    try {
      const params: Record<string, string> = {}
      if (search) params.search = search
      const { data } = await payrollApi.employees(params)
      setEmployees(data.results ?? data)
    } catch { toast.error('Failed to load employees') }
    finally { setLoading(false) }
  }

  useEffect(() => { load() }, [search])

  const gross = (f: EmployeeForm) => {
    return (
      (parseFloat(stripCommas(f.basic_salary)) || 0) +
      (parseFloat(stripCommas(f.housing_allowance)) || 0) +
      (parseFloat(stripCommas(f.transport_allowance)) || 0) +
      (parseFloat(stripCommas(f.leave_allowance)) || 0) +
      (parseFloat(stripCommas(f.other_allowances)) || 0)
    )
  }

  const openCreate = () => {
    setEditId(null); setForm(BLANK); setFormTab('personal')
    setBankSearch(''); setBankCode(''); setBankOpen(false)
    setShowModal(true)
  }
  const openEdit = (e: Employee) => {
    setEditId(e.id)
    setForm({
      first_name: e.first_name, last_name: e.last_name, email: e.email, phone: e.phone,
      job_title: e.job_title, department: e.department, employment_type: e.employment_type, hire_date: e.hire_date,
      basic_salary: formatAmountInput(e.basic_salary), housing_allowance: formatAmountInput(e.housing_allowance), transport_allowance: formatAmountInput(e.transport_allowance),
      leave_allowance: formatAmountInput(e.leave_allowance), other_allowances: formatAmountInput(e.other_allowances),
      bank_name: e.bank_name, account_number: e.account_number, account_name: e.account_name,
      pfa_name: e.pfa_name, pfa_number: e.pfa_number, tin: e.tin,
    })
    // Pre-populate bank combobox from saved bank_name
    const matched = NIGERIAN_BANKS.find((b) => b.name === e.bank_name)
    setBankSearch(e.bank_name)
    setBankCode(matched?.code ?? '')
    setBankOpen(false)
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
        basic_salary: parseFloat(stripCommas(form.basic_salary)),
        housing_allowance: parseFloat(stripCommas(form.housing_allowance)) || 0,
        transport_allowance: parseFloat(stripCommas(form.transport_allowance)) || 0,
        leave_allowance: parseFloat(stripCommas(form.leave_allowance)) || 0,
        other_allowances: parseFloat(stripCommas(form.other_allowances)) || 0,
      }
      if (editId) { await payrollApi.updateEmployee(editId, payload); toast.success('Employee updated') }
      else { await payrollApi.createEmployee(payload); toast.success('Employee added') }
      setShowModal(false)
      load()
    } catch { toast.error('Failed to save employee') }
    finally { setSaving(false) }
  }

  // Auto-resolve account name when 10-digit NUBAN + bank are both present
  useEffect(() => {
    if (form.account_number.length !== 10 || !bankCode) return
    let cancelled = false
    const resolve = async () => {
      setResolving(true)
      try {
        const { data } = await payrollApi.resolveAccount(form.account_number, bankCode)
        if (!cancelled) setForm((f) => ({ ...f, account_name: data.account_name }))
      } catch {
        // Silently fail — user can still type manually
      } finally {
        if (!cancelled) setResolving(false)
      }
    }
    resolve()
    return () => { cancelled = true }
  }, [form.account_number, bankCode])

  const selectBank = (bank: { name: string; code: string }) => {
    setForm((f) => ({ ...f, bank_name: bank.name }))
    setBankCode(bank.code)
    setBankSearch(bank.name)
    setBankOpen(false)
  }

  const filteredBanks = NIGERIAN_BANKS.filter((b) =>
    b.name.toLowerCase().includes(bankSearch.toLowerCase())
  )

  const handleDeactivate = async (e: Employee) => {
    if (!confirm(`Deactivate ${e.full_name}?`)) return
    try {
      await payrollApi.updateEmployee(e.id, { is_active: false })
      toast.success('Employee deactivated')
      load()
    } catch { toast.error('Failed to deactivate') }
  }

  const totalEmployees = employees.length
  const active = employees.filter((e) => e.is_active).length
  const contracted = employees.filter((e) => e.employment_type === 'contract').length
  const totalGross = employees.filter((e) => e.is_active).reduce((s, e) => s + parseFloat(e.gross_salary), 0)

  const EMP_TYPE_BADGE: Record<string, string> = { full_time: 'badge-green', part_time: 'badge-blue', contract: 'badge-orange' }

  const FORM_TABS: { id: FormTab; label: string }[] = [
    { id: 'personal', label: 'Personal' }, { id: 'salary', label: 'Salary' },
    { id: 'banking', label: 'Banking' }, { id: 'statutory', label: 'Statutory' },
  ]

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white">Employees</h1>
          <p className="text-slate-400 text-sm">{totalEmployees} total employees</p>
        </div>
        <button className="btn-primary sm:ml-auto" onClick={openCreate}>
          <Plus size={16} /> Add Employee
        </button>
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
              ) : employees.length === 0 ? (
                <tr>
                  <td colSpan={8} className="px-4 py-12 text-center">
                    <UsersRound size={32} className="mx-auto mb-2 text-slate-600" />
                    <p className="text-slate-500">No employees yet</p>
                  </td>
                </tr>
              ) : employees.map((e) => (
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
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
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
            <div className="flex gap-1 p-1 bg-surface-900 rounded-xl">
              {FORM_TABS.map((t) => (
                <button key={t.id} onClick={() => setFormTab(t.id)}
                  className={`flex-1 py-1.5 rounded-lg text-xs font-medium transition-all ${formTab === t.id ? 'bg-brand-500 text-white' : 'text-slate-400 hover:text-white'}`}>
                  {t.label}
                </button>
              ))}
            </div>

            {formTab === 'personal' && (
              <div className="grid grid-cols-2 gap-4">
                <div><label className="text-xs text-slate-400 mb-1 block">First Name *</label><input className="input" value={form.first_name} onChange={(e) => setForm({ ...form, first_name: e.target.value })} /></div>
                <div><label className="text-xs text-slate-400 mb-1 block">Last Name *</label><input className="input" value={form.last_name} onChange={(e) => setForm({ ...form, last_name: e.target.value })} /></div>
                <div><label className="text-xs text-slate-400 mb-1 block">Email</label><input type="email" className="input" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></div>
                <div><label className="text-xs text-slate-400 mb-1 block">Phone</label><input className="input" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} /></div>
                <div><label className="text-xs text-slate-400 mb-1 block">Job Title</label><input className="input" value={form.job_title} onChange={(e) => setForm({ ...form, job_title: e.target.value })} /></div>
                <div><label className="text-xs text-slate-400 mb-1 block">Department</label><input className="input" value={form.department} onChange={(e) => setForm({ ...form, department: e.target.value })} /></div>
                <div>
                  <label className="text-xs text-slate-400 mb-1 block">Employment Type</label>
                  <select className="input" value={form.employment_type} onChange={(e) => setForm({ ...form, employment_type: e.target.value })}>
                    <option value="full_time">Full Time</option>
                    <option value="part_time">Part Time</option>
                    <option value="contract">Contract</option>
                  </select>
                </div>
                <div><label className="text-xs text-slate-400 mb-1 block">Hire Date</label><input type="date" className="input" value={form.hire_date} onChange={(e) => setForm({ ...form, hire_date: e.target.value })} /></div>
              </div>
            )}

            {formTab === 'salary' && (
              <div className="space-y-4">
                <div className="grid grid-cols-2 gap-4">
                  <div><label className="text-xs text-slate-400 mb-1 block">Basic Salary (₦) *</label><input type="text" inputMode="decimal" className="input" value={form.basic_salary} onChange={(e) => setForm({ ...form, basic_salary: formatAmountInput(e.target.value) })} /></div>
                  <div><label className="text-xs text-slate-400 mb-1 block">Housing Allowance (₦)</label><input type="text" inputMode="decimal" className="input" value={form.housing_allowance} onChange={(e) => setForm({ ...form, housing_allowance: formatAmountInput(e.target.value) })} /></div>
                  <div><label className="text-xs text-slate-400 mb-1 block">Transport Allowance (₦)</label><input type="text" inputMode="decimal" className="input" value={form.transport_allowance} onChange={(e) => setForm({ ...form, transport_allowance: formatAmountInput(e.target.value) })} /></div>
                  <div><label className="text-xs text-slate-400 mb-1 block">Leave Allowance (₦)</label><input type="text" inputMode="decimal" className="input" value={form.leave_allowance} onChange={(e) => setForm({ ...form, leave_allowance: formatAmountInput(e.target.value) })} /></div>
                  <div className="col-span-2"><label className="text-xs text-slate-400 mb-1 block">Other Allowances (₦)</label><input type="text" inputMode="decimal" className="input" value={form.other_allowances} onChange={(e) => setForm({ ...form, other_allowances: formatAmountInput(e.target.value) })} /></div>
                </div>
                <div className="p-3 bg-brand-500/10 border border-brand-500/20 rounded-xl">
                  <p className="text-xs text-slate-400">Computed Gross Salary</p>
                  <p className="text-xl font-bold text-brand-400">{formatCurrency(String(gross(form)))}</p>
                </div>
              </div>
            )}

            {formTab === 'banking' && (
              <div className="grid grid-cols-2 gap-4">
                {/* Searchable bank dropdown */}
                <div className="col-span-2" ref={bankRef}>
                  <label className="text-xs text-slate-400 mb-1 block">Bank Name</label>
                  <div className="relative">
                    <input
                      className="input pr-9"
                      placeholder="Search bank…"
                      value={bankSearch}
                      onChange={(e) => {
                        setBankSearch(e.target.value)
                        setBankOpen(true)
                        // Clear bank_name/code if user is typing a new search
                        if (e.target.value !== form.bank_name) {
                          setForm((f) => ({ ...f, bank_name: '' }))
                          setBankCode('')
                        }
                      }}
                      onFocus={() => setBankOpen(true)}
                      onBlur={() => setTimeout(() => setBankOpen(false), 180)}
                      autoComplete="off"
                    />
                    <ChevronDown
                      size={15}
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 pointer-events-none"
                    />
                    {bankOpen && filteredBanks.length > 0 && (
                      <div className="absolute z-30 top-full left-0 right-0 mt-1 bg-surface-800 border border-surface-600 rounded-xl shadow-2xl max-h-52 overflow-y-auto">
                        {filteredBanks.map((b) => (
                          <button
                            key={b.code}
                            type="button"
                            onMouseDown={(e) => e.preventDefault()} // keep focus on input so blur fires after click
                            onClick={() => selectBank(b)}
                            className={`w-full text-left px-3 py-2.5 text-sm transition-colors flex items-center justify-between
                              ${form.bank_name === b.name
                                ? 'bg-brand-500/20 text-brand-300'
                                : 'text-slate-200 hover:bg-surface-700'
                              }`}
                          >
                            {b.name}
                            {form.bank_name === b.name && <CheckCircle2 size={14} className="text-brand-400 shrink-0" />}
                          </button>
                        ))}
                      </div>
                    )}
                    {bankOpen && bankSearch && filteredBanks.length === 0 && (
                      <div className="absolute z-30 top-full left-0 right-0 mt-1 bg-surface-800 border border-surface-600 rounded-xl shadow-2xl px-3 py-3 text-sm text-slate-500">
                        No banks match "{bankSearch}"
                      </div>
                    )}
                  </div>
                </div>

                {/* Account number — triggers auto-resolve when 10 digits */}
                <div>
                  <label className="text-xs text-slate-400 mb-1 block">Account Number</label>
                  <input
                    className="input"
                    placeholder="10-digit NUBAN"
                    maxLength={10}
                    value={form.account_number}
                    onChange={(e) => {
                      const val = e.target.value.replace(/\D/g, '').slice(0, 10)
                      setForm((f) => ({ ...f, account_number: val, account_name: val.length < 10 ? '' : f.account_name }))
                    }}
                  />
                </div>

                {/* Account name — auto-filled; editable as fallback */}
                <div>
                  <label className="text-xs text-slate-400 mb-1 block flex items-center gap-1.5">
                    Account Name
                    {resolving && <Loader2 size={11} className="animate-spin text-brand-400" />}
                  </label>
                  <input
                    className="input"
                    placeholder={resolving ? 'Resolving…' : 'Auto-filled or type manually'}
                    value={form.account_name}
                    onChange={(e) => setForm((f) => ({ ...f, account_name: e.target.value }))}
                    readOnly={resolving}
                  />
                </div>

                {!bankCode && form.bank_name === '' && (
                  <p className="col-span-2 text-xs text-slate-500">
                    Select a bank, then enter the 10-digit account number to auto-fill the account name.
                  </p>
                )}
              </div>
            )}

            {formTab === 'statutory' && (
              <div className="grid grid-cols-2 gap-4">
                <div><label className="text-xs text-slate-400 mb-1 block">PFA Name</label><input className="input" placeholder="e.g. ARM Pension" value={form.pfa_name} onChange={(e) => setForm({ ...form, pfa_name: e.target.value })} /></div>
                <div><label className="text-xs text-slate-400 mb-1 block">PFA Number (RSA PIN)</label><input className="input" value={form.pfa_number} onChange={(e) => setForm({ ...form, pfa_number: e.target.value })} /></div>
                <div className="col-span-2"><label className="text-xs text-slate-400 mb-1 block">TIN (Tax ID)</label><input className="input" placeholder="FIRS Tax Identification Number" value={form.tin} onChange={(e) => setForm({ ...form, tin: e.target.value })} /></div>
              </div>
            )}

            <div className="flex gap-3 pt-1">
              <button className="flex-1 py-2.5 rounded-xl border border-surface-600 text-slate-400 hover:text-white hover:border-surface-500 transition-colors text-sm" onClick={() => setShowModal(false)}>Cancel</button>
              <button className="btn-primary flex-1 py-2.5 justify-center disabled:opacity-50" onClick={handleSave} disabled={saving}>
                {saving ? <Loader2 size={16} className="animate-spin" /> : editId ? 'Save Changes' : 'Add Employee'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

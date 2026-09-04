import { Fragment, useEffect, useState } from 'react'
import { useDataRefresh } from '@/hooks/useDataRefresh'
import { CreditCard, Search, Plus, X, Loader2, TrendingDown, TrendingUp, AlertCircle, ChevronDown, ChevronRight, Users } from 'lucide-react'
import toast from 'react-hot-toast'
import { creditApi, accountingApi, inventoryApi } from '@/services/api'
import { orgApi } from '@/services/api'
import { formatCurrency, formatDate, stripCommas } from '@/lib/utils'
import AmountInput from '@/components/AmountInput'
import type { Account, CreditPaymentMode, CreditTransaction, Customer, Invoice, Warehouse } from '@/types'
import DateInput from '@/components/DateInput'
import { NIGERIAN_BANKS } from '@/lib/banks'
import { useResolveBankAccount } from '@/hooks/useResolveBankAccount'
import CustomerPickerModal from '@/components/CustomerPickerModal'
import InvoicePickerModal from '@/components/InvoicePickerModal'

const TYPE_COLORS: Record<string, string> = {
  debit: 'badge-red',
  credit: 'badge-green',
  adjustment: 'badge-blue',
  write_off: 'badge-slate',
}

const PAYMENT_MODES: { value: CreditPaymentMode; label: string }[] = [
  { value: 'cash', label: 'Cash' },
  { value: 'bank_transfer', label: 'Bank Transfer' },
  { value: 'pos', label: 'POS' },
  { value: 'cheque', label: 'Cheque' },
  { value: 'credit_applied', label: 'Credit Applied' },
  { value: 'other', label: 'Other' },
]

interface AgingBucket {
  label: string
  count: number
  total: string
}

const EMPTY_PAY_FORM = {
  amount: '',
  description: '',
  due_date: '',
  payment_mode: '' as CreditPaymentMode | '',
  bank_name: '',
  account_name: '',
  payment_number: '',
  debit_account_id: '',
  credit_account_id: '',
  location_id: '',
}

export default function CreditsPage() {
  const [transactions, setTransactions] = useState<CreditTransaction[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [typeFilter, setTypeFilter] = useState('')

  const [showPayModal, setShowPayModal] = useState(false)
  const [saving, setSaving] = useState(false)

  const [aging, setAging] = useState<AgingBucket[] | null>(null)

  // ─── Record Payment form state ─────────────────────────────────────────────
  const [payForm, setPayForm] = useState(EMPTY_PAY_FORM)
  const [selectedCustomer, setSelectedCustomer] = useState<Customer | null>(null)
  const [selectedInvoice, setSelectedInvoice] = useState<Invoice | null>(null)
  const [showCustomerPicker, setShowCustomerPicker] = useState(false)
  const [showInvoicePicker, setShowInvoicePicker] = useState(false)
  const [accounts, setAccounts] = useState<Account[]>([])
  const [warehouses, setWarehouses] = useState<Warehouse[]>([])

  const {
    accountNumber,
    setAccountNumber,
    bankCode,
    setBankCode,
    accountName: resolvedAccountName,
    setAccountName: setResolvedAccountName,
    resolving: resolvingAccount,
  } = useResolveBankAccount({
    resolver: async (accNum, code) => {
      const { data } = await orgApi.resolveBankAccount(accNum, code)
      return data.data
    },
  })

  const load = async () => {
    setLoading(true)
    try {
      const params: Record<string, unknown> = {}
      if (search) params.search = search
      if (typeFilter) params.transaction_type = typeFilter
      const { data } = await creditApi.list(params)
      setTransactions(data.results ?? data)
    } catch {
      toast.error('Failed to load credit transactions')
    } finally {
      setLoading(false)
    }
  }

  const loadAging = async () => {
    try {
      const { data } = await creditApi.agingReport()
      setAging(data)
    } catch {
      // non-critical
    }
  }

  useEffect(() => { load() }, [search, typeFilter])
  useEffect(() => { loadAging() }, [])
  useDataRefresh(load)

  const resetPayForm = () => {
    setPayForm(EMPTY_PAY_FORM)
    setSelectedCustomer(null)
    setSelectedInvoice(null)
    setAccountNumber('')
    setBankCode('')
    setResolvedAccountName('')
  }

  const openPayModal = async () => {
    resetPayForm()
    setShowPayModal(true)
    if (accounts.length === 0) {
      try {
        const { data } = await accountingApi.accounts()
        setAccounts(data.results ?? data)
      } catch { /* ignore */ }
    }
    if (warehouses.length === 0) {
      try {
        const { data } = await inventoryApi.warehouses()
        setWarehouses(data.results ?? data)
      } catch { /* ignore */ }
    }
  }

  const handlePickCustomer = (customer: Customer) => {
    setSelectedCustomer(customer)
    setSelectedInvoice(null)
  }

  const handlePickInvoice = (invoice: Invoice) => {
    setSelectedInvoice(invoice)
  }

  const handleBankSelect = (bankName: string) => {
    const bank = NIGERIAN_BANKS.find((b) => b.name === bankName)
    setPayForm({ ...payForm, bank_name: bankName })
    setBankCode(bank?.code ?? '')
    setResolvedAccountName('')
  }

  const handleAccountNumberChange = (v: string) => {
    const digits = v.replace(/\D/g, '').slice(0, 10)
    setAccountNumber(digits)
  }

  // ─── Outstanding balance preview ───────────────────────────────────────────
  const previouslyOwed = selectedCustomer ? parseFloat(selectedCustomer.outstanding_balance || '0') : 0
  const amountReceived = parseFloat(stripCommas(payForm.amount) || '0') || 0
  const currentlyOwed = Math.max(previouslyOwed - amountReceived, 0)

  const handleRecordPayment = async () => {
    if (!selectedCustomer) { toast.error('Choose a customer'); return }
    if (!payForm.amount || amountReceived <= 0) { toast.error('Enter a valid amount'); return }
    setSaving(true)
    try {
      await creditApi.recordPayment({
        customer_id: selectedCustomer.id,
        invoice: selectedInvoice?.id || undefined,
        amount: stripCommas(payForm.amount),
        due_date: payForm.due_date || undefined,
        description: payForm.description || undefined,
        payment_mode: payForm.payment_mode || undefined,
        bank_name: payForm.bank_name || undefined,
        bank_code: bankCode || undefined,
        account_number: accountNumber || undefined,
        account_name: resolvedAccountName || payForm.account_name || undefined,
        payment_number: payForm.payment_number || undefined,
        debit_account_id: payForm.debit_account_id || undefined,
        credit_account_id: payForm.credit_account_id || undefined,
        location_id: payForm.location_id || undefined,
      })
      toast.success('Payment recorded')
      setShowPayModal(false)
      resetPayForm()
      load()
    } catch (err: any) {
      const apiErr = err?.response?.data?.error
      const msg = typeof apiErr === 'string' ? apiErr : (apiErr?.message ?? 'Failed to record payment')
      toast.error(msg)
    } finally {
      setSaving(false)
    }
  }

  // ─── Grouped view: customer → invoice → transactions ───────────────────────
  const [expandedCustomers, setExpandedCustomers] = useState<Record<string, boolean>>({})
  const [expandedInvoices, setExpandedInvoices] = useState<Record<string, boolean>>({})

  const invoiceKeyOf = (t: CreditTransaction): string => {
    const m = /INV[-A-Za-z0-9]*(?:-[A-Za-z0-9]+)*/.exec(t.description || '')
    if (m) return m[0]
    return t.invoice ? `Invoice ${String(t.invoice).slice(0, 8)}` : 'General / no invoice'
  }

  const customerGroups = (() => {
    const byCustomer = new Map<string, CreditTransaction[]>()
    for (const t of transactions) {
      const key = t.customer_name || 'Unknown customer'
      if (!byCustomer.has(key)) byCustomer.set(key, [])
      byCustomer.get(key)!.push(t)
    }
    return Array.from(byCustomer.entries()).map(([customer, txns]) => {
      const byInvoice = new Map<string, CreditTransaction[]>()
      for (const t of txns) {
        const k = invoiceKeyOf(t)
        if (!byInvoice.has(k)) byInvoice.set(k, [])
        byInvoice.get(k)!.push(t)
      }
      const owed = txns.filter((t) => t.transaction_type === 'debit').reduce((a, t) => a + parseFloat(t.amount), 0)
      const paid = txns.filter((t) => t.transaction_type === 'credit').reduce((a, t) => a + parseFloat(t.amount), 0)
      return { customer, txns, owed, paid, invoices: Array.from(byInvoice.entries()) }
    })
  })()

  const totalOutstanding = transactions
    .filter((t) => t.transaction_type === 'debit')
    .reduce((s, t) => s + parseFloat(t.amount), 0)

  const totalPaid = transactions
    .filter((t) => t.transaction_type === 'credit')
    .reduce((s, t) => s + parseFloat(t.amount), 0)

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white">Payment Information</h1>
          <p className="text-slate-400 text-sm">{transactions.length} transactions</p>
        </div>
        <button className="btn-primary sm:ml-auto" onClick={openPayModal}>
          <Plus size={16} /> Record Payment
        </button>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <div className="card p-5 flex items-center gap-4">
          <div className="w-11 h-11 rounded-xl bg-red-500/15 flex items-center justify-center">
            <TrendingDown size={22} className="text-red-400" />
          </div>
          <div>
            <p className="text-xs text-slate-400">Total Outstanding</p>
            <p className="text-xl font-bold text-red-400">{formatCurrency(totalOutstanding)}</p>
          </div>
        </div>
        <div className="card p-5 flex items-center gap-4">
          <div className="w-11 h-11 rounded-xl bg-emerald-500/15 flex items-center justify-center">
            <TrendingUp size={22} className="text-emerald-400" />
          </div>
          <div>
            <p className="text-xs text-slate-400">Total Payments</p>
            <p className="text-xl font-bold text-emerald-400">{formatCurrency(totalPaid)}</p>
          </div>
        </div>
        <div className="card p-5 flex items-center gap-4">
          <div className="w-11 h-11 rounded-xl bg-brand-500/15 flex items-center justify-center">
            <CreditCard size={22} className="text-brand-400" />
          </div>
          <div>
            <p className="text-xs text-slate-400">Net Balance</p>
            <p className={`text-xl font-bold ${totalOutstanding - totalPaid > 0 ? 'text-red-400' : 'text-emerald-400'}`}>
              {formatCurrency(Math.abs(totalOutstanding - totalPaid))}
            </p>
          </div>
        </div>
      </div>

      {/* Aging report */}
      {aging && aging.length > 0 && (
        <div className="card p-5">
          <div className="flex items-center gap-2 mb-4">
            <AlertCircle size={16} className="text-amber-400" />
            <h3 className="text-sm font-semibold text-white">Aging Report</h3>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {aging.map((bucket) => (
              <div key={bucket.label} className="bg-surface-800 rounded-xl p-3">
                <p className="text-xs text-slate-500 mb-1">{bucket.label}</p>
                <p className="text-sm font-bold text-white">{formatCurrency(bucket.total)}</p>
                <p className="text-xs text-slate-500">{bucket.count} customer{bucket.count !== 1 ? 's' : ''}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Filters */}
      <div className="flex flex-col sm:flex-row gap-3">
        <div className="relative flex-1 max-w-sm">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
          <input className="input pl-9" placeholder="Search customer…" value={search} onChange={(e) => setSearch(e.target.value)} />
        </div>
        <select className="input max-w-xs" value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)}>
          <option value="">All types</option>
          {['debit', 'credit', 'adjustment', 'write_off'].map((t) => (
            <option key={t} value={t}>{t.replace('_', ' ').toUpperCase()}</option>
          ))}
        </select>
      </div>

      {/* Table */}
      <div className="card p-0 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-surface-700">
                {['Date', 'Payment #', 'Mode', 'Customer', 'Type', 'Amount', 'Balance After', 'Due Date', 'Description'].map((h) => (
                  <th key={h} className="px-5 py-3.5 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading ? (
                Array.from({ length: 6 }).map((_, i) => (
                  <tr key={i} className="table-row">
                    {Array.from({ length: 9 }).map((_, j) => (
                      <td key={j} className="px-5 py-3.5"><div className="h-4 bg-surface-700 rounded animate-pulse w-20" /></td>
                    ))}
                  </tr>
                ))
              ) : transactions.length === 0 ? (
                <tr><td colSpan={9} className="px-5 py-12 text-center">
                  <CreditCard size={32} className="mx-auto mb-2 text-slate-600" />
                  <p className="text-slate-500">No credit transactions</p>
                </td></tr>
              ) : (
                customerGroups.map((g) => {
                  const custOpen = expandedCustomers[g.customer] ?? false
                  return (
                    <Fragment key={g.customer}>
                      {/* Customer parent row */}
                      <tr
                        className="table-row cursor-pointer bg-surface-800/60 hover:bg-surface-700/50"
                        onClick={() => setExpandedCustomers((p) => ({ ...p, [g.customer]: !custOpen }))}
                      >
                        <td className="px-5 py-3.5" colSpan={4}>
                          <span className="flex items-center gap-2.5 font-semibold text-white">
                            {custOpen ? <ChevronDown size={15} className="text-brand-400 shrink-0" /> : <ChevronRight size={15} className="text-slate-500 shrink-0" />}
                            <Users size={14} className="text-slate-500 shrink-0" />
                            {g.customer}
                            <span className="text-xs font-normal text-slate-500">· {g.txns.length} transaction{g.txns.length !== 1 ? 's' : ''} · {g.invoices.length} invoice group{g.invoices.length !== 1 ? 's' : ''}</span>
                          </span>
                        </td>
                        <td className="px-5 py-3.5" colSpan={2}>
                          <span className="text-xs text-slate-500">Owed </span>
                          <span className="font-semibold text-red-400">{formatCurrency(g.owed)}</span>
                          <span className="text-xs text-slate-500 ml-3">Paid </span>
                          <span className="font-semibold text-emerald-400">{formatCurrency(g.paid)}</span>
                        </td>
                        <td className="px-5 py-3.5" colSpan={3}>
                          <span className="text-xs text-slate-500">Net </span>
                          <span className={`font-semibold ${g.owed - g.paid > 0 ? 'text-red-400' : 'text-emerald-400'}`}>{formatCurrency(Math.abs(g.owed - g.paid))}</span>
                        </td>
                      </tr>
                      {custOpen && g.invoices.map(([invKey, txns]) => {
                        const ik = `${g.customer}::${invKey}`
                        const invOpen = expandedInvoices[ik] ?? true
                        return (
                          <Fragment key={ik}>
                            {/* Invoice child row */}
                            <tr
                              className="table-row cursor-pointer bg-surface-800/30"
                              onClick={() => setExpandedInvoices((p) => ({ ...p, [ik]: !invOpen }))}
                            >
                              <td className="px-5 py-2.5" colSpan={9}>
                                <span className="flex items-center gap-2 pl-6 text-sm font-medium text-brand-400">
                                  {invOpen ? <ChevronDown size={13} className="shrink-0" /> : <ChevronRight size={13} className="shrink-0" />}
                                  {invKey}
                                  <span className="text-xs font-normal text-slate-500">· {txns.length} entr{txns.length !== 1 ? 'ies' : 'y'}</span>
                                </span>
                              </td>
                            </tr>
                            {/* Transaction grandchild rows */}
                            {invOpen && txns.map((t) => (
                              <tr key={t.id} className="table-row">
                                <td className="px-5 py-3.5 text-slate-400 whitespace-nowrap"><span className="pl-10 inline-block">{formatDate(t.created_at)}</span></td>
                                <td className="px-5 py-3.5 text-slate-300 font-mono text-xs whitespace-nowrap">{t.payment_number || '—'}</td>
                                <td className="px-5 py-3.5 text-slate-400 whitespace-nowrap">
                                  {t.payment_mode ? PAYMENT_MODES.find((m) => m.value === t.payment_mode)?.label ?? t.payment_mode : '—'}
                                </td>
                                <td className="px-5 py-3.5 text-slate-400">{t.customer_name}</td>
                                <td className="px-5 py-3.5">
                                  <span className={TYPE_COLORS[t.transaction_type] ?? 'badge-slate'}>{t.transaction_type.replace('_', ' ').toUpperCase()}</span>
                                </td>
                                <td className={`px-5 py-3.5 font-semibold ${t.transaction_type === 'credit' ? 'text-emerald-400' : 'text-red-400'}`}>
                                  {t.transaction_type === 'credit' ? '+' : '−'} {formatCurrency(t.amount)}
                                </td>
                                <td className="px-5 py-3.5 text-slate-300">{formatCurrency(t.balance_after)}</td>
                                <td className="px-5 py-3.5 text-slate-400">{t.due_date ? formatDate(t.due_date) : '—'}</td>
                                <td className="px-5 py-3.5 text-slate-400 max-w-xs truncate">{t.description || '—'}</td>
                              </tr>
                            ))}
                          </Fragment>
                        )
                      })}
                    </Fragment>
                  )
                })
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Record Payment modal */}
      {showPayModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={() => setShowPayModal(false)} />
          <div className="relative card w-full max-w-lg p-6 space-y-5 max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between">
              <div><h2 className="text-lg font-bold text-white">Record Payment</h2><p className="text-xs text-slate-500 mt-0.5">Fields marked <span className="text-brand-400">*</span> are required — everything else is optional.</p></div>
              <button onClick={() => setShowPayModal(false)} className="text-slate-400 hover:text-white"><X size={20} /></button>
            </div>

            <div className="space-y-4">
              {/* Customer */}
              <div>
                <label className="label">Customer *</label>
                <div className="flex items-center gap-2">
                  <div className="input flex-1 flex items-center text-slate-300">
                    {selectedCustomer ? selectedCustomer.name : <span className="text-slate-500">No customer selected</span>}
                  </div>
                  <button type="button" className="btn-secondary shrink-0" onClick={() => setShowCustomerPicker(true)}>
                    Choose
                  </button>
                </div>
                {selectedCustomer && (
                  <p className="text-xs text-slate-500 mt-1.5">
                    Amount previously owed: <span className="text-red-400 font-medium">{formatCurrency(previouslyOwed)}</span>
                  </p>
                )}
              </div>

              {/* Invoice */}
              <div>
                <label className="label">Invoice <span className="text-slate-500 font-normal">(optional)</span></label>
                <div className="flex items-center gap-2">
                  <div className="input flex-1 flex items-center text-slate-300">
                    {selectedInvoice ? selectedInvoice.invoice_number : <span className="text-slate-500">No invoice selected</span>}
                  </div>
                  <button
                    type="button"
                    className="btn-secondary shrink-0 disabled:opacity-40 disabled:cursor-not-allowed"
                    onClick={() => setShowInvoicePicker(true)}
                    disabled={!selectedCustomer}
                  >
                    Choose
                  </button>
                </div>
              </div>

              {/* Payment mode */}
              <div>
                <label className="label">Payment Mode <span className="text-slate-500 font-normal">(optional)</span></label>
                <select
                  className="input"
                  value={payForm.payment_mode}
                  onChange={(e) => setPayForm({ ...payForm, payment_mode: e.target.value as CreditPaymentMode })}
                >
                  <option value="">— Select mode —</option>
                  {PAYMENT_MODES.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
                </select>
              </div>

              {/* Amount received */}
              <div>
                <label className="label">Amount Received *</label>
                <AmountInput className="input" placeholder="0.00"
                  value={payForm.amount} onChange={(v) => setPayForm({ ...payForm, amount: v })} />
              </div>

              {/* Bank received from */}
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="label">Bank Received From <span className="text-slate-500 font-normal">(optional)</span></label>
                  <select className="input" value={payForm.bank_name} onChange={(e) => handleBankSelect(e.target.value)}>
                    <option value="">— Select bank —</option>
                    {NIGERIAN_BANKS.map((b) => <option key={b.code + b.name} value={b.name}>{b.name}</option>)}
                  </select>
                </div>
                <div>
                  <label className="label">Account Number <span className="text-slate-500 font-normal">(optional)</span></label>
                  <input
                    className="input font-mono"
                    placeholder="10-digit NUBAN"
                    inputMode="numeric"
                    maxLength={10}
                    value={accountNumber}
                    onChange={(e) => handleAccountNumberChange(e.target.value)}
                  />
                </div>
              </div>

              {/* Account name */}
              <div>
                <label className="label flex items-center gap-2">
                  Account Name <span className="text-slate-500 font-normal">(optional)</span>
                  {resolvingAccount && <Loader2 size={12} className="animate-spin text-brand-400" />}
                </label>
                <input
                  className="input"
                  placeholder={resolvingAccount ? 'Resolving…' : 'Auto-filled when account resolves'}
                  value={resolvedAccountName || payForm.account_name}
                  onChange={(e) => { setResolvedAccountName(''); setPayForm({ ...payForm, account_name: e.target.value }) }}
                />
              </div>

              {/* Debit / Credit account */}
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="label">Debit Account <span className="text-slate-500 font-normal">(optional)</span></label>
                  <select className="input" value={payForm.debit_account_id}
                    onChange={(e) => setPayForm({ ...payForm, debit_account_id: e.target.value })}>
                    <option value="">— None —</option>
                    {accounts.map((a) => <option key={a.id} value={a.id}>{a.code} · {a.name}</option>)}
                  </select>
                </div>
                <div>
                  <label className="label">Credit Account <span className="text-slate-500 font-normal">(optional)</span></label>
                  <select className="input" value={payForm.credit_account_id}
                    onChange={(e) => setPayForm({ ...payForm, credit_account_id: e.target.value })}>
                    <option value="">— None —</option>
                    {accounts.map((a) => <option key={a.id} value={a.id}>{a.code} · {a.name}</option>)}
                  </select>
                </div>
              </div>
              <p className="text-xs text-slate-500 -mt-2">
                For your records only — this payment always posts to the standard cash/bank and receivable accounts; it does not yet redirect the ledger entry to the accounts chosen above.
              </p>

              {/* Payment number — auto-generated if left blank, but manually editable */}
              <div>
                <label className="label">Payment Number <span className="text-slate-500 font-normal">(optional)</span></label>
                <input
                  className="input"
                  placeholder="Leave blank to auto-generate"
                  value={payForm.payment_number}
                  onChange={(e) => setPayForm({ ...payForm, payment_number: e.target.value })}
                />
              </div>

              {/* Location/Warehouse */}
              <div>
                <label className="label">Location / Warehouse <span className="text-slate-500 font-normal">(optional)</span></label>
                <select className="input" value={payForm.location_id}
                  onChange={(e) => setPayForm({ ...payForm, location_id: e.target.value })}>
                  <option value="">— None —</option>
                  {warehouses.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
                </select>
              </div>

              {/* Owed preview */}
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="label">Amount Previously Owed</label>
                  <div className="input text-slate-400 flex items-center">{formatCurrency(previouslyOwed)}</div>
                </div>
                <div>
                  <label className="label">Amount Currently Owed</label>
                  <div className="input text-slate-300 flex items-center">{formatCurrency(currentlyOwed)}</div>
                </div>
              </div>

              {/* Date received */}
              <div>
                <label className="label">Date Received <span className="text-slate-500 font-normal">(optional)</span></label>
                <DateInput
                  value={payForm.due_date}
                  onChange={(v) => setPayForm({ ...payForm, due_date: v })}
                  placeholder="DD/MM/YYYY"
                />
              </div>

              {/* Note */}
              <div>
                <label className="label">Note <span className="text-slate-500 font-normal">(optional)</span></label>
                <textarea className="input resize-none" rows={2} placeholder="Payment reference or note"
                  value={payForm.description} onChange={(e) => setPayForm({ ...payForm, description: e.target.value })} />
              </div>
            </div>

            <div className="flex gap-3 pt-1">
              <button className="flex-1 py-2.5 rounded-xl border border-surface-600 text-slate-400 hover:text-white transition-colors text-sm"
                onClick={() => setShowPayModal(false)}>Cancel</button>
              <button className="btn-primary flex-1 justify-center disabled:opacity-50" onClick={handleRecordPayment} disabled={saving}>
                {saving ? <Loader2 size={16} className="animate-spin" /> : 'Record Payment'}
              </button>
            </div>
          </div>
        </div>
      )}

      <CustomerPickerModal
        open={showCustomerPicker}
        onClose={() => setShowCustomerPicker(false)}
        onSelect={handlePickCustomer}
      />
      <InvoicePickerModal
        open={showInvoicePicker}
        onClose={() => setShowInvoicePicker(false)}
        onSelect={handlePickInvoice}
        customerId={selectedCustomer?.id ?? ''}
      />
    </div>
  )
}

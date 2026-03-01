import { useEffect, useState } from 'react'
import { Plus, X, Landmark, Loader2, ChevronDown, ChevronUp } from 'lucide-react'
import toast from 'react-hot-toast'
import { accountingApi } from '@/services/api'
import { formatCurrency, formatDate } from '@/lib/utils'
import type { FixedAsset, Account } from '@/types'

const CATEGORIES = ['land', 'building', 'vehicle', 'equipment', 'furniture', 'other'] as const

interface AssetForm {
  name: string
  asset_code: string
  category: string
  account: string
  purchase_date: string
  purchase_cost: string
  depreciation_method: string
  useful_life_years: string
  residual_value: string
}

const today = new Date().toISOString().split('T')[0]
const BLANK: AssetForm = {
  name: '', asset_code: '', category: 'equipment', account: '',
  purchase_date: today, purchase_cost: '', depreciation_method: 'straight_line',
  useful_life_years: '5', residual_value: '0',
}

export default function AssetsPage() {
  const [assets, setAssets] = useState<FixedAsset[]>([])
  const [accounts, setAccounts] = useState<Account[]>([])
  const [loading, setLoading] = useState(true)
  const [expandedRow, setExpandedRow] = useState<string | null>(null)

  const [showModal, setShowModal] = useState(false)
  const [editId, setEditId] = useState<string | null>(null)
  const [form, setForm] = useState<AssetForm>(BLANK)
  const [saving, setSaving] = useState(false)

  const [runningDep, setRunningDep] = useState(false)

  const load = async () => {
    setLoading(true)
    try {
      const [aRes, accRes] = await Promise.all([accountingApi.assets(), accountingApi.accounts()])
      setAssets(aRes.data.results ?? aRes.data)
      setAccounts(accRes.data.results ?? accRes.data)
    } catch { toast.error('Failed to load fixed assets') }
    finally { setLoading(false) }
  }

  useEffect(() => { load() }, [])

  const handleRunDepreciation = async () => {
    const now = new Date()
    const payload = { year: now.getFullYear(), month: now.getMonth() + 1 }
    if (!confirm(`Run depreciation for ${now.toLocaleString('default', { month: 'long' })} ${now.getFullYear()}?`)) return
    setRunningDep(true)
    try {
      const { data } = await accountingApi.runDepreciation(payload)
      toast.success(`Depreciation run complete — ${(data as { count?: number }).count ?? 0} assets processed`)
      load()
    } catch { toast.error('Failed to run depreciation') }
    finally { setRunningDep(false) }
  }

  const openCreate = () => { setEditId(null); setForm(BLANK); setShowModal(true) }
  const openEdit = (a: FixedAsset) => {
    setEditId(a.id)
    setForm({
      name: a.name, asset_code: a.asset_code, category: a.category,
      account: a.account ?? '', purchase_date: a.purchase_date,
      purchase_cost: a.purchase_cost, depreciation_method: a.depreciation_method,
      useful_life_years: String(a.useful_life_years), residual_value: a.residual_value,
    })
    setShowModal(true)
  }

  const handleSave = async () => {
    if (!form.name.trim()) { toast.error('Asset name is required'); return }
    if (!form.purchase_cost || parseFloat(form.purchase_cost) <= 0) { toast.error('Purchase cost must be > 0'); return }
    setSaving(true)
    try {
      const payload = {
        ...form,
        account: form.account || null,
        purchase_cost: parseFloat(form.purchase_cost),
        useful_life_years: parseInt(form.useful_life_years),
        residual_value: parseFloat(form.residual_value) || 0,
      }
      if (editId) { await accountingApi.updateAsset(editId, payload); toast.success('Asset updated') }
      else { await accountingApi.createAsset(payload); toast.success('Asset created') }
      setShowModal(false)
      load()
    } catch { toast.error('Failed to save asset') }
    finally { setSaving(false) }
  }

  const totalCost = assets.reduce((s, a) => s + parseFloat(a.purchase_cost), 0)
  const totalDepreciation = assets.reduce((s, a) => s + parseFloat(a.accumulated_depreciation), 0)
  const totalNBV = assets.reduce((s, a) => s + parseFloat(a.net_book_value), 0)

  const assetAccounts = accounts.filter((a) => a.account_type === 'asset')

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white">Fixed Assets Register</h1>
          <p className="text-slate-400 text-sm">{assets.length} assets</p>
        </div>
        <div className="sm:ml-auto flex gap-2">
          <button onClick={handleRunDepreciation} disabled={runningDep} className="btn-ghost flex items-center gap-2 text-sm">
            {runningDep ? <Loader2 size={14} className="animate-spin" /> : null}
            Run Depreciation
          </button>
          <button onClick={openCreate} className="btn-primary flex items-center gap-2">
            <Plus size={16} /> Add Asset
          </button>
        </div>
      </div>

      {/* Summary */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <div className="card p-5"><p className="text-xs text-slate-400">Total Assets Value</p><p className="text-xl font-bold text-white mt-1">{formatCurrency(String(totalCost))}</p></div>
        <div className="card p-5"><p className="text-xs text-slate-400">Total Depreciation</p><p className="text-xl font-bold text-red-400 mt-1">{formatCurrency(String(totalDepreciation))}</p></div>
        <div className="card p-5"><p className="text-xs text-slate-400">Net Book Value</p><p className="text-xl font-bold text-emerald-400 mt-1">{formatCurrency(String(totalNBV))}</p></div>
      </div>

      {/* Table */}
      <div className="card p-0 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-surface-700">
                {['', 'Code', 'Name', 'Category', 'Purchase Date', 'Cost', 'Acc. Dep', 'Net Book Value', 'Method', 'Status', ''].map((h) => (
                  <th key={h} className="px-4 py-3.5 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading ? (
                Array.from({ length: 5 }).map((_, i) => (
                  <tr key={i} className="table-row">
                    {Array.from({ length: 11 }).map((_, j) => (
                      <td key={j} className="px-4 py-3.5"><div className="h-4 bg-surface-700 rounded animate-pulse w-16" /></td>
                    ))}
                  </tr>
                ))
              ) : assets.length === 0 ? (
                <tr>
                  <td colSpan={11} className="px-4 py-12 text-center">
                    <Landmark size={32} className="mx-auto mb-2 text-slate-600" />
                    <p className="text-slate-500">No fixed assets yet</p>
                  </td>
                </tr>
              ) : assets.map((a) => (
                <>
                  <tr key={a.id} className="table-row">
                    <td className="px-4 py-3.5">
                      <button onClick={() => setExpandedRow(expandedRow === a.id ? null : a.id)} className="text-slate-400 hover:text-white">
                        {expandedRow === a.id ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                      </button>
                    </td>
                    <td className="px-4 py-3.5 font-mono text-slate-400">{a.asset_code}</td>
                    <td className="px-4 py-3.5 text-white font-medium">{a.name}</td>
                    <td className="px-4 py-3.5"><span className="badge-slate capitalize">{a.category}</span></td>
                    <td className="px-4 py-3.5 text-slate-400">{formatDate(a.purchase_date)}</td>
                    <td className="px-4 py-3.5 font-mono text-white">{formatCurrency(a.purchase_cost)}</td>
                    <td className="px-4 py-3.5 font-mono text-red-400">{formatCurrency(a.accumulated_depreciation)}</td>
                    <td className="px-4 py-3.5 font-mono text-emerald-400">{formatCurrency(a.net_book_value)}</td>
                    <td className="px-4 py-3.5 text-slate-400 text-xs">{a.depreciation_method === 'straight_line' ? 'SL' : 'RB'}</td>
                    <td className="px-4 py-3.5">{a.is_active ? <span className="badge-green">Active</span> : <span className="badge-slate">Disposed</span>}</td>
                    <td className="px-4 py-3.5">
                      <button onClick={() => openEdit(a)} className="text-xs px-2.5 py-1 rounded-lg bg-brand-500/15 text-brand-400 hover:bg-brand-500/25 transition-colors">Edit</button>
                    </td>
                  </tr>
                  {expandedRow === a.id && (
                    <tr key={`${a.id}-dep`} className="bg-surface-900/50">
                      <td colSpan={11} className="px-6 py-4">
                        <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">Depreciation Schedule</p>
                        {a.depreciation_entries.length === 0 ? (
                          <p className="text-slate-500 text-sm">No depreciation entries yet. Run depreciation first.</p>
                        ) : (
                          <table className="w-full text-xs">
                            <thead>
                              <tr className="border-b border-surface-700">
                                {['Period', 'Depreciation', 'Accumulated', 'NBV'].map((h) => (
                                  <th key={h} className="pb-2 text-left text-slate-500 uppercase tracking-wider">{h}</th>
                                ))}
                              </tr>
                            </thead>
                            <tbody className="divide-y divide-surface-700">
                              {a.depreciation_entries.map((d) => (
                                <tr key={d.id}>
                                  <td className="py-2 text-slate-400">{d.period_year}-{String(d.period_month).padStart(2, '0')}</td>
                                  <td className="py-2 text-red-400 font-mono">{formatCurrency(d.depreciation_amount)}</td>
                                  <td className="py-2 text-slate-400 font-mono">{formatCurrency(d.accumulated_to_date)}</td>
                                  <td className="py-2 text-emerald-400 font-mono">{formatCurrency(d.net_book_value)}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        )}
                      </td>
                    </tr>
                  )}
                </>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Asset Modal */}
      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={() => setShowModal(false)} />
          <div className="relative card w-full max-w-lg p-6 space-y-5 overflow-y-auto max-h-[90vh]">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-bold text-white">{editId ? 'Edit Asset' : 'Add Fixed Asset'}</h2>
              <button onClick={() => setShowModal(false)} className="text-slate-400 hover:text-white"><X size={20} /></button>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="col-span-2">
                <label className="text-xs text-slate-400 mb-1 block">Asset Name *</label>
                <input className="input" placeholder="e.g. Office Generator" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Asset Code</label>
                <input className="input" placeholder="e.g. AST-001" value={form.asset_code} onChange={(e) => setForm({ ...form, asset_code: e.target.value })} />
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Category</label>
                <select className="input" value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })}>
                  {CATEGORIES.map((c) => <option key={c} value={c}>{c.charAt(0).toUpperCase() + c.slice(1)}</option>)}
                </select>
              </div>
              <div className="col-span-2">
                <label className="text-xs text-slate-400 mb-1 block">Asset Account (optional)</label>
                <select className="input" value={form.account} onChange={(e) => setForm({ ...form, account: e.target.value })}>
                  <option value="">None</option>
                  {assetAccounts.map((a) => <option key={a.id} value={a.id}>{a.code} — {a.name}</option>)}
                </select>
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Purchase Date</label>
                <input type="date" className="input" value={form.purchase_date} onChange={(e) => setForm({ ...form, purchase_date: e.target.value })} />
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Purchase Cost (₦) *</label>
                <input type="number" min="0" step="0.01" className="input" value={form.purchase_cost} onChange={(e) => setForm({ ...form, purchase_cost: e.target.value })} />
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Depreciation Method</label>
                <select className="input" value={form.depreciation_method} onChange={(e) => setForm({ ...form, depreciation_method: e.target.value })}>
                  <option value="straight_line">Straight Line</option>
                  <option value="reducing_balance">Reducing Balance</option>
                </select>
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Useful Life (years)</label>
                <input type="number" min="1" className="input" value={form.useful_life_years} onChange={(e) => setForm({ ...form, useful_life_years: e.target.value })} />
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Residual Value (₦)</label>
                <input type="number" min="0" step="0.01" className="input" value={form.residual_value} onChange={(e) => setForm({ ...form, residual_value: e.target.value })} />
              </div>
            </div>
            <div className="flex gap-3 pt-1">
              <button className="flex-1 py-2.5 rounded-xl border border-surface-600 text-slate-400 hover:text-white hover:border-surface-500 transition-colors text-sm" onClick={() => setShowModal(false)}>Cancel</button>
              <button className="btn-primary flex-1 py-2.5 justify-center disabled:opacity-50" onClick={handleSave} disabled={saving}>
                {saving ? <Loader2 size={16} className="animate-spin" /> : editId ? 'Save Changes' : 'Add Asset'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

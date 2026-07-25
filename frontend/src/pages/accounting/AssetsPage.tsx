import { useEffect, useState } from 'react'
import { confirmDialog } from '@/lib/dialog'
import { useDataRefresh } from '@/hooks/useDataRefresh'
import { Plus, X, Landmark, Loader2, ChevronDown, ChevronUp, RefreshCw, AlertTriangle, CheckCircle2 } from 'lucide-react'
import toast from 'react-hot-toast'
import { accountingApi, inventoryApi, bypassNextGets } from '@/services/api'
import { formatCurrency, formatDate, stripCommas } from '@/lib/utils'
import AmountInput from '@/components/AmountInput'
import type { FixedAsset, Account, AssetReconciliation } from '@/types'
import DateInput from '@/components/DateInput'

const CATEGORIES = ['land', 'building', 'vehicle', 'equipment', 'furniture', 'other'] as const

const METHODS: { value: string; label: string }[] = [
  { value: 'straight_line', label: 'Straight Line' },
  { value: 'reducing_balance', label: 'Reducing Balance' },
  { value: 'immediate', label: 'Immediate Write-Off' },
  { value: 'zero', label: 'No Depreciation (0%)' },
  { value: 'units', label: 'Units of Production' },
]
const METHOD_ABBR: Record<string, string> = {
  straight_line: 'SL', reducing_balance: 'RB', immediate: 'IMM', zero: '0%', units: 'UoP',
}
const FUNDING: { value: string; label: string }[] = [
  { value: 'bank', label: 'Bank' },
  { value: 'cash', label: 'Cash' },
  { value: 'payable', label: 'Accounts Payable (supplier owed)' },
  { value: 'equity', label: 'Owner / Capital Introduced' },
  { value: 'none', label: 'Opening balance / already owned (take-on)' },
]

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
  funding_source: string
  reducing_balance_rate: string
  depreciation_convention: string
  opening_accumulated_depreciation: string
  total_units: string
  serial_number: string
  barcode: string
  master_asset: string
}

const today = new Date().toISOString().split('T')[0]
const BLANK: AssetForm = {
  name: '', asset_code: '', category: 'equipment', account: '',
  purchase_date: today, purchase_cost: '', depreciation_method: 'straight_line',
  useful_life_years: '5', residual_value: '0', funding_source: 'bank',
  reducing_balance_rate: '', depreciation_convention: 'full_month',
  opening_accumulated_depreciation: '0',
  total_units: '', serial_number: '', barcode: '', master_asset: '',
}

export default function AssetsPage() {
  const [assets, setAssets] = useState<FixedAsset[]>([])
  const [accounts, setAccounts] = useState<Account[]>([])
  const [recon, setRecon] = useState<AssetReconciliation | null>(null)
  const [loading, setLoading] = useState(true)
  const [expandedRow, setExpandedRow] = useState<string | null>(null)

  const [showModal, setShowModal] = useState(false)
  const [editId, setEditId] = useState<string | null>(null)
  const [form, setForm] = useState<AssetForm>(BLANK)
  const [saving, setSaving] = useState(false)

  const [runningDep, setRunningDep] = useState(false)

  // Disposal modal
  const [disposeAsset, setDisposeAsset] = useState<FixedAsset | null>(null)
  const [disposeForm, setDisposeForm] = useState({ proceeds: '', disposal_date: today, proceeds_funding: 'bank' })
  const [disposing, setDisposing] = useState(false)

  // Transfer / revalue modals
  const [warehouses, setWarehouses] = useState<{ id: string; name: string }[]>([])
  const [assetTypes, setAssetTypes] = useState<{ id: string; code: string; name: string }[]>([])
  const [transferAsset, setTransferAsset] = useState<FixedAsset | null>(null)
  const [transferForm, setTransferForm] = useState({ to_location: '', to_cost_centre: '', transfer_date: today, reference: '', to_asset_type: '' })
  const [transferring, setTransferring] = useState(false)
  const [revalueAsset, setRevalueAsset] = useState<FixedAsset | null>(null)
  const [revalueForm, setRevalueForm] = useState({ new_value: '', revaluation_date: today })
  const [revaluing, setRevaluing] = useState(false)

  // Record-usage modal (Units of Production)
  const [usageAsset, setUsageAsset] = useState<FixedAsset | null>(null)
  const [usageForm, setUsageForm] = useState({ year: new Date().getFullYear(), month: new Date().getMonth() + 1, units: '' })
  const [recordingUsage, setRecordingUsage] = useState(false)

  const load = async () => {
    setLoading(true)
    try {
      const [aRes, accRes, recRes] = await Promise.all([
        accountingApi.assets(),
        accountingApi.accounts(),
        accountingApi.assetReconciliation().catch(() => null),
      ])
      setAssets(aRes.data.results ?? aRes.data)
      setAccounts(accRes.data.results ?? accRes.data)
      setRecon(recRes ? recRes.data : null)
    } catch { toast.error('Failed to load fixed assets') }
    finally { setLoading(false) }
  }

  useEffect(() => { load() }, [])
  useDataRefresh(load)

  useEffect(() => {
    inventoryApi.warehouses().then((r) => setWarehouses(r.data.results ?? r.data)).catch(() => {})
    accountingApi.assetTypes().then((r) => setAssetTypes(r.data.results ?? r.data)).catch(() => {})
  }, [])

  const handleRunDepreciation = async (draft = false) => {
    const now = new Date()
    const monthLabel = now.toLocaleString('default', { month: 'long' })
    const verb = draft ? 'Generate a DRAFT depreciation batch' : 'Run and POST depreciation'
    const catchUp = await confirmDialog(
      `${verb} up to ${monthLabel} ${now.getFullYear()}?\n\nClick OK to catch up ALL outstanding months through this period, or Cancel to run just this month.`,
    )
    const payload = { year: now.getFullYear(), month: now.getMonth() + 1, catch_up: catchUp, draft }
    setRunningDep(true)
    try {
      const { data } = await accountingApi.runDepreciation(payload)
      const d = data as { entries_created?: number; already_run?: boolean; message?: string }
      if (d.already_run) toast(d.message ?? 'Depreciation already run for this period.', { icon: 'ℹ️' })
      else toast.success(d.message ?? `Depreciation run complete — ${d.entries_created ?? 0} entries created`)
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
      funding_source: a.funding_source ?? 'bank',
      reducing_balance_rate: a.reducing_balance_rate ?? '',
      depreciation_convention: a.depreciation_convention ?? 'full_month',
      opening_accumulated_depreciation: '0',
      total_units: a.total_units ?? '',
      serial_number: a.serial_number ?? '', barcode: a.barcode ?? '',
      master_asset: a.master_asset ?? '',
    })
    setShowModal(true)
  }

  const handleSave = async () => {
    if (!form.name.trim()) { toast.error('Asset name is required'); return }
    if (!form.purchase_cost || parseFloat(stripCommas(form.purchase_cost)) <= 0) { toast.error('Purchase cost must be > 0'); return }
    setSaving(true)
    try {
      const isTakeon = form.funding_source === 'none'
      const payload: Record<string, unknown> = {
        name: form.name,
        asset_code: form.asset_code,
        category: form.category,
        account: form.account || null,
        purchase_date: form.purchase_date,
        purchase_cost: parseFloat(stripCommas(form.purchase_cost)),
        depreciation_method: form.depreciation_method,
        useful_life_years: parseInt(form.useful_life_years) || 5,
        residual_value: parseFloat(stripCommas(form.residual_value)) || 0,
        funding_source: form.funding_source,
        capitalisation_source: isTakeon ? 'opening_balance' : 'direct',
        depreciation_convention: form.depreciation_convention,
        serial_number: form.serial_number,
        barcode: form.barcode,
        master_asset: form.master_asset || null,
      }
      if (form.depreciation_method === 'reducing_balance' && form.reducing_balance_rate) {
        payload.reducing_balance_rate = parseFloat(stripCommas(form.reducing_balance_rate))
      }
      if (form.depreciation_method === 'units' && form.total_units) {
        payload.total_units = parseFloat(stripCommas(form.total_units))
      }
      if (isTakeon) {
        payload.opening_accumulated_depreciation = parseFloat(stripCommas(form.opening_accumulated_depreciation)) || 0
      }
      if (editId) { await accountingApi.updateAsset(editId, payload); toast.success('Asset updated') }
      else { await accountingApi.createAsset(payload); toast.success('Asset created') }
      setShowModal(false)
      load()
    } catch { toast.error('Failed to save asset') }
    finally { setSaving(false) }
  }

  const openDispose = (a: FixedAsset) => {
    setDisposeAsset(a)
    setDisposeForm({ proceeds: '', disposal_date: today, proceeds_funding: 'bank' })
  }
  const handleDispose = async () => {
    if (!disposeAsset) return
    setDisposing(true)
    try {
      const { data } = await accountingApi.disposeAsset(disposeAsset.id, {
        proceeds: parseFloat(stripCommas(disposeForm.proceeds)) || 0,
        disposal_date: disposeForm.disposal_date,
        proceeds_funding: disposeForm.proceeds_funding,
      })
      const gl = parseFloat((data as { gain_loss?: string }).gain_loss ?? '0')
      toast.success(`Asset disposed — ${gl >= 0 ? 'gain' : 'loss'} of ${formatCurrency(String(Math.abs(gl)))}`)
      setDisposeAsset(null)
      load()
    } catch (e) {
      const msg = (e as { response?: { data?: { error?: string } } })?.response?.data?.error
      toast.error(typeof msg === 'string' ? msg : 'Failed to dispose asset')
    } finally { setDisposing(false) }
  }

  const openTransfer = (a: FixedAsset) => {
    setTransferAsset(a)
    setTransferForm({ to_location: a.location ?? '', to_cost_centre: a.cost_centre ?? '', transfer_date: today, reference: '', to_asset_type: a.asset_type ?? '' })
  }
  const handleTransfer = async () => {
    if (!transferAsset) return
    setTransferring(true)
    try {
      const payload: Record<string, unknown> = {
        to_location: transferForm.to_location || null,
        to_cost_centre: transferForm.to_cost_centre,
        transfer_date: transferForm.transfer_date,
        reference: transferForm.reference,
      }
      if (transferForm.to_asset_type && transferForm.to_asset_type !== (transferAsset.asset_type ?? '')) {
        payload.to_asset_type = transferForm.to_asset_type
      }
      await accountingApi.transferAsset(transferAsset.id, payload)
      toast.success('Asset transferred')
      setTransferAsset(null)
      load()
    } catch { toast.error('Failed to transfer asset') }
    finally { setTransferring(false) }
  }

  const openUsage = (a: FixedAsset) => {
    setUsageAsset(a)
    setUsageForm({ year: new Date().getFullYear(), month: new Date().getMonth() + 1, units: '' })
  }
  const handleRecordUsage = async () => {
    if (!usageAsset) return
    const units = parseFloat(stripCommas(usageForm.units))
    if (!units || units <= 0) { toast.error('Units used must be greater than 0'); return }
    setRecordingUsage(true)
    try {
      const { data } = await accountingApi.recordAssetUsage(usageAsset.id, {
        year: usageForm.year, month: usageForm.month, units,
      })
      const amt = (data as { depreciation_amount?: string }).depreciation_amount ?? '0'
      toast.success(`Usage recorded — depreciation of ${formatCurrency(String(amt))} posted`)
      setUsageAsset(null)
      load()
    } catch (e) {
      const msg = (e as { response?: { data?: { error?: string } } })?.response?.data?.error
      toast.error(typeof msg === 'string' ? msg : 'Failed to record usage')
    } finally { setRecordingUsage(false) }
  }

  const openRevalue = (a: FixedAsset) => { setRevalueAsset(a); setRevalueForm({ new_value: '', revaluation_date: today }) }
  const handleRevalue = async () => {
    if (!revalueAsset) return
    setRevaluing(true)
    try {
      const { data } = await accountingApi.revalueAsset(revalueAsset.id, {
        new_value: parseFloat(stripCommas(revalueForm.new_value)) || 0,
        revaluation_date: revalueForm.revaluation_date,
      })
      const surplus = parseFloat((data as { surplus?: string }).surplus ?? '0')
      toast.success(`Asset revalued — ${surplus >= 0 ? 'surplus' : 'deficit'} of ${formatCurrency(String(Math.abs(surplus)))}`)
      setRevalueAsset(null)
      load()
    } catch (e) {
      const msg = (e as { response?: { data?: { error?: string } } })?.response?.data?.error
      toast.error(typeof msg === 'string' ? msg : 'Failed to revalue asset')
    } finally { setRevaluing(false) }
  }

  const handlePostBatch = async () => {
    const now = new Date()
    try {
      const { data } = await accountingApi.postDepreciationBatch({ year: now.getFullYear(), month: now.getMonth() + 1 })
      toast.success((data as { message?: string }).message ?? 'Draft batch posted')
      load()
    } catch { toast.error('Failed to post depreciation batch') }
  }

  const totalCost = assets.reduce((s, a) => s + parseFloat(a.purchase_cost), 0)
  const totalDepreciation = assets.reduce((s, a) => s + parseFloat(a.accumulated_depreciation), 0)
  const totalNBV = assets.reduce((s, a) => s + parseFloat(a.net_book_value), 0)

  const assetAccounts = accounts.filter((a) => a.account_type === 'asset')
  const isTakeon = form.funding_source === 'none'

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white">Fixed Assets Register</h1>
          <p className="text-slate-400 text-sm">{assets.length} assets</p>
        </div>
        <div className="sm:ml-auto flex gap-2">
          <button onClick={() => { bypassNextGets(); load() }} disabled={loading} className="btn-ghost p-2 text-slate-400 hover:text-white" title="Refresh">
            <RefreshCw size={16} className={loading ? 'animate-spin' : ''} />
          </button>
          <button onClick={() => handleRunDepreciation(false)} disabled={runningDep} className="btn-ghost flex items-center gap-2 text-sm" title="Compute and post depreciation">
            {runningDep ? <Loader2 size={14} className="animate-spin" /> : null}
            Run Depreciation
          </button>
          <button onClick={() => handleRunDepreciation(true)} disabled={runningDep} className="btn-ghost text-sm" title="Compute depreciation as a draft batch for review">
            Draft Batch
          </button>
          <button onClick={handlePostBatch} className="btn-ghost text-sm" title="Post this month's draft depreciation batch">
            Post Batch
          </button>
          <button onClick={openCreate} className="btn-primary flex items-center gap-2">
            <Plus size={16} /> Add Asset
          </button>
        </div>
      </div>

      {/* Register ↔ GL reconciliation banner */}
      {recon && (
        <div className={`card p-4 flex flex-col gap-2 border ${recon.reconciled ? 'border-emerald-500/30' : 'border-amber-500/40'}`}>
          <div className="flex items-center gap-2">
            {recon.reconciled
              ? <><CheckCircle2 size={16} className="text-emerald-400" /><span className="text-sm font-medium text-emerald-400">Register reconciles to the General Ledger</span></>
              : <><AlertTriangle size={16} className="text-amber-400" /><span className="text-sm font-medium text-amber-400">Register does not tie to the General Ledger</span></>}
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
            <div><p className="text-slate-500">Register NBV</p><p className="font-mono text-white">{formatCurrency(recon.register.net_book_value)}</p></div>
            <div><p className="text-slate-500">GL NBV (1500−1510)</p><p className="font-mono text-white">{formatCurrency(recon.gl.net_book_value)}</p></div>
            <div><p className="text-slate-500">Variance</p><p className={`font-mono ${Math.abs(parseFloat(recon.variance.net_book_value)) < 0.01 ? 'text-emerald-400' : 'text-amber-400'}`}>{formatCurrency(recon.variance.net_book_value)}</p></div>
            <div><p className="text-slate-500">Take-On Suspense (3900)</p><p className="font-mono text-slate-300">{formatCurrency(recon.suspense_balance)}</p></div>
          </div>
          {recon.assets_missing_acquisition.length > 0 && (
            <p className="text-xs text-amber-400/90">
              {recon.assets_missing_acquisition.length} asset(s) have no posted acquisition — e.g. {recon.assets_missing_acquisition.slice(0, 3).map((a) => a.asset_code).join(', ')}. Check GL account mapping.
            </p>
          )}
        </div>
      )}

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
                    <td className="px-4 py-3.5 text-white font-medium">
                      {a.name}
                      {a.acquisition_error ? <span className="ml-2 text-[10px] text-amber-400" title={a.acquisition_error}>⚠ not posted</span> : null}
                    </td>
                    <td className="px-4 py-3.5"><span className="badge-slate capitalize">{a.category}</span></td>
                    <td className="px-4 py-3.5 text-slate-400">{formatDate(a.purchase_date)}</td>
                    <td className="px-4 py-3.5 font-mono text-white">{formatCurrency(a.purchase_cost)}</td>
                    <td className="px-4 py-3.5 font-mono text-red-400">{formatCurrency(a.accumulated_depreciation)}</td>
                    <td className="px-4 py-3.5 font-mono text-emerald-400">{formatCurrency(a.net_book_value)}</td>
                    <td className="px-4 py-3.5 text-slate-400 text-xs">{METHOD_ABBR[a.depreciation_method] ?? a.depreciation_method}</td>
                    <td className="px-4 py-3.5">{a.is_active ? <span className="badge-green">Active</span> : <span className="badge-slate">Disposed</span>}</td>
                    <td className="px-4 py-3.5 whitespace-nowrap">
                      <button onClick={() => openEdit(a)} className="text-xs px-2.5 py-1 rounded-lg bg-brand-500/15 text-brand-400 hover:bg-brand-500/25 transition-colors">Edit</button>
                      {a.is_active && (
                        <>
                          {a.depreciation_method === 'units' && (
                            <button onClick={() => openUsage(a)} className="ml-2 text-xs px-2.5 py-1 rounded-lg bg-brand-500/15 text-brand-400 hover:bg-brand-500/25 transition-colors">Record Usage</button>
                          )}
                          <button onClick={() => openTransfer(a)} className="ml-2 text-xs px-2.5 py-1 rounded-lg bg-surface-700 text-slate-300 hover:bg-surface-600 transition-colors">Transfer</button>
                          <button onClick={() => openRevalue(a)} className="ml-2 text-xs px-2.5 py-1 rounded-lg bg-surface-700 text-slate-300 hover:bg-surface-600 transition-colors">Revalue</button>
                          <button onClick={() => openDispose(a)} className="ml-2 text-xs px-2.5 py-1 rounded-lg bg-red-500/15 text-red-400 hover:bg-red-500/25 transition-colors">Dispose</button>
                        </>
                      )}
                    </td>
                  </tr>
                  {expandedRow === a.id && (
                    <tr key={`${a.id}-dep`} className="bg-surface-900/50">
                      <td colSpan={11} className="px-6 py-4">
                        <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">Depreciation History (posted)</p>
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
                <input className="input" placeholder="auto if blank" value={form.asset_code} onChange={(e) => setForm({ ...form, asset_code: e.target.value })} />
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Category</label>
                <select className="input" value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })}>
                  {CATEGORIES.map((c) => <option key={c} value={c}>{c.charAt(0).toUpperCase() + c.slice(1)}</option>)}
                </select>
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Serial Number</label>
                <input className="input" placeholder="optional" value={form.serial_number} onChange={(e) => setForm({ ...form, serial_number: e.target.value })} />
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Barcode / Tag</label>
                <input className="input" placeholder="optional" value={form.barcode} onChange={(e) => setForm({ ...form, barcode: e.target.value })} />
              </div>
              <div className="col-span-2">
                <label className="text-xs text-slate-400 mb-1 block">Component of (master asset)</label>
                <select className="input" value={form.master_asset} onChange={(e) => setForm({ ...form, master_asset: e.target.value })}>
                  <option value="">None — this is a standalone / master asset</option>
                  {assets.filter((a) => a.id !== editId).map((a) => <option key={a.id} value={a.id}>{a.asset_code} — {a.name}</option>)}
                </select>
                <p className="text-[11px] text-slate-500 mt-1">Link a sub-component (e.g. a part) to a parent asset for grouped tracking.</p>
              </div>
              {!editId && (
                <div className="col-span-2">
                  <label className="text-xs text-slate-400 mb-1 block">How was it funded? *</label>
                  <select className="input" value={form.funding_source} onChange={(e) => setForm({ ...form, funding_source: e.target.value })}>
                    {FUNDING.map((f) => <option key={f.value} value={f.value}>{f.label}</option>)}
                  </select>
                  <p className="text-[11px] text-slate-500 mt-1">
                    {isTakeon
                      ? 'Take-on: posts DR Fixed Assets / CR Accumulated Dep / CR Take-On Suspense — no purchase entry.'
                      : 'Posts DR Fixed Assets (1500) / CR the funding account so the balance sheet reflects the asset.'}
                  </p>
                </div>
              )}
              <div className="col-span-2">
                <label className="text-xs text-slate-400 mb-1 block">Asset Account (optional)</label>
                <select className="input" value={form.account} onChange={(e) => setForm({ ...form, account: e.target.value })}>
                  <option value="">None (defaults to 1500 Fixed Assets)</option>
                  {assetAccounts.map((a) => <option key={a.id} value={a.id}>{a.code} — {a.name}</option>)}
                </select>
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Purchase Date</label>
                <DateInput value={form.purchase_date} onChange={(v) => setForm({ ...form, purchase_date: v })} />
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Purchase Cost *</label>
                <AmountInput className="input" value={form.purchase_cost} onChange={(v) => setForm({ ...form, purchase_cost: v })} />
              </div>
              {isTakeon && !editId && (
                <div className="col-span-2">
                  <label className="text-xs text-slate-400 mb-1 block">Accumulated Depreciation to date</label>
                  <AmountInput className="input" value={form.opening_accumulated_depreciation} onChange={(v) => setForm({ ...form, opening_accumulated_depreciation: v })} />
                </div>
              )}
              {form.category === 'land' ? (
                <div className="col-span-2 flex items-center gap-2 px-3 py-2.5 rounded-xl bg-amber-500/10 border border-amber-500/30 text-amber-400 text-xs">
                  <span className="font-semibold">ℹ Land</span> — land does not depreciate and will be excluded from depreciation runs.
                </div>
              ) : (
                <>
                  <div>
                    <label className="text-xs text-slate-400 mb-1 block">Depreciation Method</label>
                    <select className="input" value={form.depreciation_method} onChange={(e) => setForm({ ...form, depreciation_method: e.target.value })}>
                      {METHODS.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
                    </select>
                  </div>
                  <div>
                    <label className="text-xs text-slate-400 mb-1 block">Useful Life (years)</label>
                    <input type="number" min="1" className="input" value={form.useful_life_years} onChange={(e) => setForm({ ...form, useful_life_years: e.target.value })} />
                  </div>
                  {form.depreciation_method === 'reducing_balance' && (
                    <div>
                      <label className="text-xs text-slate-400 mb-1 block">RB rate % (optional)</label>
                      <input type="number" min="0" step="0.1" className="input" placeholder="derive from life" value={form.reducing_balance_rate} onChange={(e) => setForm({ ...form, reducing_balance_rate: e.target.value })} />
                    </div>
                  )}
                  {form.depreciation_method === 'units' && (
                    <div className="col-span-2">
                      <label className="text-xs text-slate-400 mb-1 block">Total estimated units of production *</label>
                      <AmountInput className="input" value={form.total_units} onChange={(v) => setForm({ ...form, total_units: v })} />
                      <p className="text-[11px] text-slate-500 mt-1">Depreciation is charged per unit used — record monthly usage from the register's ⋯ menu.</p>
                    </div>
                  )}
                  <div>
                    <label className="text-xs text-slate-400 mb-1 block">Residual Value</label>
                    <AmountInput className="input" value={form.residual_value} onChange={(v) => setForm({ ...form, residual_value: v })} />
                  </div>
                  <div>
                    <label className="text-xs text-slate-400 mb-1 block">First-period convention</label>
                    <select className="input" value={form.depreciation_convention} onChange={(e) => setForm({ ...form, depreciation_convention: e.target.value })}>
                      <option value="full_month">Full month (charge in month of purchase)</option>
                      <option value="new_month">New month (start the month after purchase)</option>
                      <option value="pro_rata">Pro-rata (by days)</option>
                    </select>
                  </div>
                </>
              )}
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

      {/* Dispose Modal */}
      {disposeAsset && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={() => setDisposeAsset(null)} />
          <div className="relative card w-full max-w-md p-6 space-y-5">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-bold text-white">Dispose {disposeAsset.asset_code}</h2>
              <button onClick={() => setDisposeAsset(null)} className="text-slate-400 hover:text-white"><X size={20} /></button>
            </div>
            <p className="text-xs text-slate-400">
              Net book value: <span className="font-mono text-white">{formatCurrency(disposeAsset.net_book_value)}</span>.
              Posts DR proceeds + DR accumulated dep / CR cost, with the gain or loss to the P&amp;L.
            </p>
            <div className="grid grid-cols-2 gap-4">
              <div className="col-span-2">
                <label className="text-xs text-slate-400 mb-1 block">Sale proceeds</label>
                <AmountInput className="input" value={disposeForm.proceeds} onChange={(v) => setDisposeForm({ ...disposeForm, proceeds: v })} />
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Disposal date</label>
                <DateInput value={disposeForm.disposal_date} onChange={(v) => setDisposeForm({ ...disposeForm, disposal_date: v })} />
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Proceeds to</label>
                <select className="input" value={disposeForm.proceeds_funding} onChange={(e) => setDisposeForm({ ...disposeForm, proceeds_funding: e.target.value })}>
                  <option value="bank">Bank</option>
                  <option value="cash">Cash</option>
                  <option value="receivable">Receivable</option>
                </select>
              </div>
            </div>
            <div className="flex gap-3">
              <button className="flex-1 py-2.5 rounded-xl border border-surface-600 text-slate-400 hover:text-white text-sm" onClick={() => setDisposeAsset(null)}>Cancel</button>
              <button className="flex-1 py-2.5 rounded-xl bg-red-500/90 hover:bg-red-500 text-white text-sm font-medium disabled:opacity-50 flex items-center justify-center" onClick={handleDispose} disabled={disposing}>
                {disposing ? <Loader2 size={16} className="animate-spin" /> : 'Dispose Asset'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Transfer Modal */}
      {transferAsset && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={() => setTransferAsset(null)} />
          <div className="relative card w-full max-w-md p-6 space-y-5">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-bold text-white">Transfer {transferAsset.asset_code}</h2>
              <button onClick={() => setTransferAsset(null)} className="text-slate-400 hover:text-white"><X size={20} /></button>
            </div>
            <p className="text-xs text-slate-400">A transfer reclassifies the asset's location, cost-centre or asset type. It does not change GL cost or depreciation.</p>
            <div className="grid grid-cols-2 gap-4">
              {assetTypes.length > 0 && (
                <div className="col-span-2">
                  <label className="text-xs text-slate-400 mb-1 block">Reclassify to asset type</label>
                  <select className="input" value={transferForm.to_asset_type} onChange={(e) => setTransferForm({ ...transferForm, to_asset_type: e.target.value })}>
                    <option value="">— unchanged —</option>
                    {assetTypes.map((t) => <option key={t.id} value={t.id}>{t.code} — {t.name}</option>)}
                  </select>
                </div>
              )}
              <div>
                <label className="text-xs text-slate-400 mb-1 block">New location</label>
                <select className="input" value={transferForm.to_location} onChange={(e) => setTransferForm({ ...transferForm, to_location: e.target.value })}>
                  <option value="">— unchanged —</option>
                  {warehouses.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
                </select>
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Cost centre</label>
                <input className="input" placeholder="e.g. Operations" value={transferForm.to_cost_centre} onChange={(e) => setTransferForm({ ...transferForm, to_cost_centre: e.target.value })} />
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Transfer date</label>
                <DateInput value={transferForm.transfer_date} onChange={(v) => setTransferForm({ ...transferForm, transfer_date: v })} />
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Reference</label>
                <input className="input" value={transferForm.reference} onChange={(e) => setTransferForm({ ...transferForm, reference: e.target.value })} />
              </div>
            </div>
            <div className="flex gap-3">
              <button className="flex-1 py-2.5 rounded-xl border border-surface-600 text-slate-400 hover:text-white text-sm" onClick={() => setTransferAsset(null)}>Cancel</button>
              <button className="btn-primary flex-1 py-2.5 justify-center disabled:opacity-50" onClick={handleTransfer} disabled={transferring}>
                {transferring ? <Loader2 size={16} className="animate-spin" /> : 'Transfer'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Revalue Modal */}
      {revalueAsset && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={() => setRevalueAsset(null)} />
          <div className="relative card w-full max-w-md p-6 space-y-5">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-bold text-white">Revalue {revalueAsset.asset_code}</h2>
              <button onClick={() => setRevalueAsset(null)} className="text-slate-400 hover:text-white"><X size={20} /></button>
            </div>
            <p className="text-xs text-slate-400">
              Current NBV: <span className="font-mono text-white">{formatCurrency(revalueAsset.net_book_value)}</span>.
              Requires revaluation to be enabled for your organisation (cost model is the default).
            </p>
            <div className="grid grid-cols-2 gap-4">
              <div className="col-span-2">
                <label className="text-xs text-slate-400 mb-1 block">New carrying value</label>
                <AmountInput className="input" value={revalueForm.new_value} onChange={(v) => setRevalueForm({ ...revalueForm, new_value: v })} />
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Revaluation date</label>
                <DateInput value={revalueForm.revaluation_date} onChange={(v) => setRevalueForm({ ...revalueForm, revaluation_date: v })} />
              </div>
            </div>
            <div className="flex gap-3">
              <button className="flex-1 py-2.5 rounded-xl border border-surface-600 text-slate-400 hover:text-white text-sm" onClick={() => setRevalueAsset(null)}>Cancel</button>
              <button className="btn-primary flex-1 py-2.5 justify-center disabled:opacity-50" onClick={handleRevalue} disabled={revaluing}>
                {revaluing ? <Loader2 size={16} className="animate-spin" /> : 'Revalue'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Record Usage Modal (Units of Production) */}
      {usageAsset && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={() => setUsageAsset(null)} />
          <div className="relative card w-full max-w-md p-6 space-y-5">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-bold text-white">Record Usage — {usageAsset.asset_code}</h2>
              <button onClick={() => setUsageAsset(null)} className="text-slate-400 hover:text-white"><X size={20} /></button>
            </div>
            <p className="text-xs text-slate-400">
              Enter units produced this period. Depreciation is charged as
              (units ÷ total est. {usageAsset.total_units ? Number(usageAsset.total_units).toLocaleString() : '—'} units) × depreciable cost, and posted to the GL.
            </p>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Year</label>
                <input type="number" className="input" value={usageForm.year} onChange={(e) => setUsageForm({ ...usageForm, year: parseInt(e.target.value) || usageForm.year })} />
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Month</label>
                <select className="input" value={usageForm.month} onChange={(e) => setUsageForm({ ...usageForm, month: parseInt(e.target.value) })}>
                  {Array.from({ length: 12 }, (_, i) => i + 1).map((m) => (
                    <option key={m} value={m}>{new Date(2000, m - 1, 1).toLocaleString('default', { month: 'long' })}</option>
                  ))}
                </select>
              </div>
              <div className="col-span-2">
                <label className="text-xs text-slate-400 mb-1 block">Units produced this period *</label>
                <AmountInput className="input" value={usageForm.units} onChange={(v) => setUsageForm({ ...usageForm, units: v })} />
              </div>
            </div>
            <div className="flex gap-3">
              <button className="flex-1 py-2.5 rounded-xl border border-surface-600 text-slate-400 hover:text-white text-sm" onClick={() => setUsageAsset(null)}>Cancel</button>
              <button className="btn-primary flex-1 py-2.5 justify-center disabled:opacity-50" onClick={handleRecordUsage} disabled={recordingUsage}>
                {recordingUsage ? <Loader2 size={16} className="animate-spin" /> : 'Record & Post'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

/**
 * General Reports hub — the reviewer's nested report tree.
 *
 * Reads the backend report registry (/reports/catalog/) and renders every report
 * grouped into the spec's categories. Selecting one dispatches /reports/r/<key>/
 * for the chosen period and renders the result generically: flat `rows` payloads
 * become a table, nested payloads fall back to a readable key/value view.
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  BarChart3, BookOpen, Boxes, ChevronDown, ChevronRight, Download,
  FileSpreadsheet, Landmark, Loader2, RefreshCw, Search, Users, UsersRound, Wallet,
} from 'lucide-react'
import toast from 'react-hot-toast'
import PeriodSelector, { type PeriodValue } from '@/components/PeriodSelector'
import { useDataRefresh } from '@/hooks/useDataRefresh'
import { bypassNextGets, reportApi } from '@/services/api'
import { saveBlobFile } from '@/lib/saveBlobFile'
import { formatCurrency } from '@/lib/utils'

interface CatalogEntry {
  key: string
  label: string
  category: string
  description: string
  needs_period: boolean
}

type ReportPayload = Record<string, unknown>

/** Category display order + icon, matching the reviewer's spec tree. */
const CATEGORY_ORDER: { name: string; icon: React.ElementType }[] = [
  { name: 'Financial Statements', icon: BarChart3 },
  { name: 'General Ledger',       icon: BookOpen },
  { name: 'Accounts Receivable',  icon: Users },
  { name: 'Accounts Payable',     icon: Wallet },
  { name: 'Inventory',            icon: Boxes },
  { name: 'Fixed Assets',         icon: Landmark },
  { name: 'Payroll & HR',         icon: UsersRound },
  { name: 'Accountant Reports',   icon: FileSpreadsheet },
]

/** Columns whose values should render as money. */
const MONEY_HINT = /amount|total|balance|cost|revenue|debit|credit|net|gross|paye|salary|value|outstanding|deduction|depreciation|subtotal|tax|pension|nhf/i

function isMoneyColumn(col: string): boolean {
  return MONEY_HINT.test(col) && !/count|quantity|hours|assets|orders|level/i.test(col)
}

function prettify(col: string): string {
  return col.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

function renderCell(col: string, value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value === 'boolean') return value ? 'Yes' : 'No'
  if (isMoneyColumn(col) && !isNaN(Number(value))) return formatCurrency(String(value))
  return String(value)
}

export default function AllReportsPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [catalog, setCatalog] = useState<CatalogEntry[]>([])
  const [catalogLoading, setCatalogLoading] = useState(true)
  const [selected, setSelected] = useState<string | null>(searchParams.get('report'))
  const [payload, setPayload] = useState<ReportPayload | null>(null)
  const [meta, setMeta] = useState<{ label: string; period_label: string } | null>(null)
  const [running, setRunning] = useState(false)
  const [exporting, setExporting] = useState<string | null>(null)
  const [period, setPeriod] = useState<PeriodValue>({ period: 'year' })
  const [query, setQuery] = useState('')
  const [openCats, setOpenCats] = useState<Record<string, boolean>>(
    () => Object.fromEntries(CATEGORY_ORDER.map((c) => [c.name, true])),
  )

  const loadCatalog = useCallback(async () => {
    setCatalogLoading(true)
    try {
      const { data } = await reportApi.catalog()
      setCatalog(data.reports ?? [])
    } catch {
      toast.error('Failed to load the report catalog')
    } finally {
      setCatalogLoading(false)
    }
  }, [])

  useEffect(() => { loadCatalog() }, [loadCatalog])

  const runReport = useCallback(async (key: string) => {
    setRunning(true)
    setPayload(null)
    try {
      const params: Record<string, string> = { period: period.period }
      if (period.date_from) params.date_from = period.date_from
      if (period.date_to) params.date_to = period.date_to
      const { data } = await reportApi.run(key, params)
      setPayload((data?.data ?? null) as ReportPayload | null)
      setMeta({ label: data?.label ?? key, period_label: data?.period_label ?? '' })
    } catch (err) {
      const apiErr = (err as { response?: { data?: { error?: unknown } } })?.response?.data?.error
      toast.error(typeof apiErr === 'string' ? apiErr : 'Failed to run this report')
      setPayload(null)
    } finally {
      setRunning(false)
    }
  }, [period])

  // Re-run whenever the selected report or the period changes.
  useEffect(() => {
    if (selected) runReport(selected)
  }, [selected, runReport])

  useDataRefresh(() => { if (selected) runReport(selected) })

  const selectReport = (key: string) => {
    setSelected(key)
    setSearchParams((prev) => { prev.set('report', key); return prev }, { replace: true })
  }

  const handleExport = async (fmt: 'excel' | 'pdf') => {
    if (!selected) return
    setExporting(fmt)
    try {
      const params: Record<string, string> = { period: period.period, format: fmt }
      if (period.date_from) params.date_from = period.date_from
      if (period.date_to) params.date_to = period.date_to
      const res = await reportApi.download(`/reports/r/${selected}/`, params)
      const ext = fmt === 'excel' ? 'xlsx' : 'pdf'
      await saveBlobFile(res.data as Blob, `${selected}.${ext}`)
      toast.success(`Exported as ${ext.toUpperCase()}`)
    } catch {
      toast.error('This report cannot be exported in that format')
    } finally {
      setExporting(null)
    }
  }

  const grouped = useMemo(() => {
    const q = query.trim().toLowerCase()
    const match = (r: CatalogEntry) =>
      !q || r.label.toLowerCase().includes(q) || r.description.toLowerCase().includes(q)
    return CATEGORY_ORDER
      .map((c) => ({ ...c, reports: catalog.filter((r) => r.category === c.name && match(r)) }))
      .filter((c) => c.reports.length > 0)
  }, [catalog, query])

  const selectedEntry = catalog.find((r) => r.key === selected) ?? null

  // Flat `rows` payloads render as a table; everything else falls back to sections.
  const rows = Array.isArray((payload as { rows?: unknown })?.rows)
    ? ((payload as { rows: Record<string, unknown>[] }).rows)
    : null
  const columns = rows && rows.length > 0 ? Object.keys(rows[0]) : []

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center gap-3">
        <div>
          <h1 className="text-2xl font-bold text-white">General Reports</h1>
          <p className="text-slate-400 text-sm">
            {catalogLoading ? 'Loading…' : `${catalog.length} reports across ${grouped.length} categories`}
          </p>
        </div>
        <div className="sm:ml-auto flex items-center gap-2 flex-wrap">
          <PeriodSelector value={period} onChange={setPeriod} />
          <button
            onClick={() => { bypassNextGets(); loadCatalog(); if (selected) runReport(selected) }}
            disabled={running || catalogLoading}
            className="btn-ghost p-2 text-slate-400 hover:text-white"
            title="Refresh"
          >
            <RefreshCw size={16} className={running || catalogLoading ? 'animate-spin' : ''} />
          </button>
        </div>
      </div>

      <div className="grid lg:grid-cols-[minmax(0,300px)_1fr] gap-4 items-start">
        {/* ── Report tree ── */}
        <div className="card p-3 space-y-2 lg:sticky lg:top-4">
          <div className="relative">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500 pointer-events-none" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search reports…"
              className="input w-full pl-8 py-2 text-sm"
            />
          </div>

          {catalogLoading ? (
            <div className="flex justify-center py-10 text-slate-500"><Loader2 size={20} className="animate-spin" /></div>
          ) : grouped.length === 0 ? (
            <p className="text-sm text-slate-500 text-center py-8">No reports match “{query}”.</p>
          ) : (
            <div className="space-y-1 max-h-[70vh] overflow-y-auto pr-1">
              {grouped.map((cat) => {
                const Icon = cat.icon
                const open = openCats[cat.name] ?? true
                return (
                  <div key={cat.name}>
                    <button
                      onClick={() => setOpenCats((p) => ({ ...p, [cat.name]: !open }))}
                      className="w-full flex items-center gap-2 px-2 py-2 rounded-lg text-xs font-semibold uppercase tracking-wider text-slate-400 hover:text-white hover:bg-surface-800 transition-colors"
                    >
                      {open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
                      <Icon size={14} />
                      <span className="flex-1 text-left">{cat.name}</span>
                      <span className="text-[10px] text-slate-600">{cat.reports.length}</span>
                    </button>
                    {open && (
                      <div className="ml-4 pl-2 border-l border-surface-700 space-y-0.5 py-0.5">
                        {cat.reports.map((r) => (
                          <button
                            key={r.key}
                            onClick={() => selectReport(r.key)}
                            title={r.description}
                            className={`w-full text-left px-2.5 py-1.5 rounded-lg text-sm transition-colors ${
                              selected === r.key
                                ? 'bg-brand-500/15 text-white font-medium border border-brand-500/40'
                                : 'text-slate-300 hover:bg-surface-800 hover:text-white border border-transparent'
                            }`}
                          >
                            {r.label}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          )}
        </div>

        {/* ── Report viewer ── */}
        <div className="card p-0 overflow-hidden min-h-[340px]">
          {!selected ? (
            <div className="flex flex-col items-center justify-center text-center py-24 px-6">
              <BarChart3 size={34} className="text-slate-600 mb-3" />
              <p className="text-slate-300 font-medium">Choose a report</p>
              <p className="text-slate-500 text-sm mt-1 max-w-sm">
                Pick any report from the list. Set the period first — it applies to whichever report you open.
              </p>
            </div>
          ) : (
            <>
              <div className="px-5 py-4 border-b border-surface-700 flex flex-wrap items-center gap-3">
                <div className="min-w-0">
                  <h2 className="text-base font-semibold text-white">{meta?.label ?? selectedEntry?.label}</h2>
                  <p className="text-xs text-slate-500 mt-0.5">
                    {selectedEntry?.description}
                    {meta?.period_label ? ` · ${meta.period_label}` : ''}
                  </p>
                </div>
                <div className="ml-auto flex items-center gap-2">
                  <button
                    onClick={() => handleExport('excel')}
                    disabled={!!exporting || running || !rows}
                    title={rows ? 'Download as Excel' : 'This report has no tabular export'}
                    className="btn-ghost text-xs flex items-center gap-1.5 disabled:opacity-40"
                  >
                    {exporting === 'excel' ? <Loader2 size={13} className="animate-spin" /> : <Download size={13} />}
                    Excel
                  </button>
                  <button
                    onClick={() => handleExport('pdf')}
                    disabled={!!exporting || running || !rows}
                    title={rows ? 'Download as PDF' : 'This report has no tabular export'}
                    className="btn-ghost text-xs flex items-center gap-1.5 disabled:opacity-40"
                  >
                    {exporting === 'pdf' ? <Loader2 size={13} className="animate-spin" /> : <Download size={13} />}
                    PDF
                  </button>
                </div>
              </div>

              {running ? (
                <div className="flex justify-center py-20 text-slate-500"><Loader2 size={24} className="animate-spin" /></div>
              ) : payload === null ? (
                <p className="text-center text-slate-500 text-sm py-20">No data returned for this period.</p>
              ) : rows ? (
                rows.length === 0 ? (
                  <p className="text-center text-slate-500 text-sm py-20">Nothing to show for this period.</p>
                ) : (
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b border-surface-700">
                          {columns.map((c) => (
                            <th key={c} className="px-4 py-3 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider whitespace-nowrap">
                              {prettify(c)}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {rows.map((r, i) => (
                          <tr key={i} className="table-row">
                            {columns.map((c) => (
                              <td
                                key={c}
                                className={`px-4 py-2.5 whitespace-nowrap ${
                                  isMoneyColumn(c) ? 'font-mono text-slate-200 text-right' : 'text-slate-300'
                                }`}
                              >
                                {renderCell(c, r[c])}
                              </td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )
              ) : (
                <NestedPayload payload={payload} />
              )}

              {/* Totals strip — surfaced from common summary keys. */}
              {payload && !running && (
                <TotalsStrip payload={payload} />
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}

/** Renders a non-tabular payload (nested sections) readably. */
function NestedPayload({ payload }: { payload: ReportPayload }) {
  const entries = Object.entries(payload).filter(
    ([k]) => !['period_start', 'period_end', 'as_of'].includes(k),
  )
  return (
    <div className="p-5 space-y-4">
      {entries.map(([key, value]) => (
        <div key={key}>
          <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-1.5">{prettify(key)}</h3>
          {Array.isArray(value) ? (
            <div className="space-y-1.5">
              {value.length === 0 && <p className="text-sm text-slate-500">None.</p>}
              {value.map((item, i) => (
                <pre key={i} className="text-xs text-slate-300 bg-surface-800 border border-surface-700 rounded-lg p-2.5 overflow-x-auto">
                  {JSON.stringify(item, null, 2)}
                </pre>
              ))}
            </div>
          ) : typeof value === 'object' && value !== null ? (
            <pre className="text-xs text-slate-300 bg-surface-800 border border-surface-700 rounded-lg p-2.5 overflow-x-auto">
              {JSON.stringify(value, null, 2)}
            </pre>
          ) : (
            <p className="text-sm text-slate-200 font-mono">{String(value)}</p>
          )}
        </div>
      ))}
    </div>
  )
}

/** Shows scalar summary values (total, totals{}) under the table. */
function TotalsStrip({ payload }: { payload: ReportPayload }) {
  const items: { label: string; value: string }[] = []
  const total = payload.total
  if (total !== undefined && total !== null && !isNaN(Number(total))) {
    items.push({ label: 'Total', value: formatCurrency(String(total)) })
  }
  const totals = payload.totals
  if (totals && typeof totals === 'object' && !Array.isArray(totals)) {
    for (const [k, v] of Object.entries(totals as Record<string, unknown>)) {
      if (v !== null && v !== undefined && !isNaN(Number(v))) {
        items.push({ label: prettify(k), value: formatCurrency(String(v)) })
      }
    }
  }
  if (items.length === 0) return null
  return (
    <div className="border-t border-surface-700 px-5 py-3 flex flex-wrap gap-x-8 gap-y-2">
      {items.map((it) => (
        <div key={it.label}>
          <p className="text-[11px] text-slate-500 uppercase tracking-wider">{it.label}</p>
          <p className="text-sm font-mono font-semibold text-white">{it.value}</p>
        </div>
      ))}
    </div>
  )
}

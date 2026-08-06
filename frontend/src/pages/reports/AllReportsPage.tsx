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
  BarChart3, ChevronDown, ChevronRight, Download,
  FileSpreadsheet, Loader2, Mail, RefreshCw, Search, X,
} from 'lucide-react'
import toast from 'react-hot-toast'
import PeriodSelector, { type PeriodValue } from '@/components/PeriodSelector'
import { useDataRefresh } from '@/hooks/useDataRefresh'
import { useAuthStore } from '@/store/authStore'
import { bypassNextGets, reportApi } from '@/services/api'
import { saveBlobFile } from '@/lib/saveBlobFile'
import { formatCurrency } from '@/lib/utils'
import { CATEGORY_ORDER, type CatalogEntry } from '@/lib/reportCategories'

// A resolver can return a plain object OR a bare array (trial_balance_report
// returns `list`, not `dict`) — the payload type has to cover both so the
// bare-array case doesn't need an `as` cast sprinkled everywhere it's used.
type ReportPayload = Record<string, unknown> | unknown[]

/** Columns whose values should render as money. */
const MONEY_HINT = /amount|total|balance|cost|revenue|debit|credit|net|gross|paye|salary|value|outstanding|deduction|depreciation|subtotal|tax|pension|nhf/i

function isMoneyColumn(col: string): boolean {
  // "gross_margin_pct"/"net_margin_pct" contain "gross"/"net" so they'd
  // otherwise match MONEY_HINT — exclude anything percent-flavoured.
  return MONEY_HINT.test(col) && !/count|quantity|hours|assets|orders|level|pct|percent/i.test(col)
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

/** Reads a numeric-ish payload value as money, or '—' if absent/not a number. */
function money(value: unknown): string {
  if (value === null || value === undefined || value === '' || isNaN(Number(value))) return '—'
  return formatCurrency(String(value))
}

/**
 * A payload is "already a table" if it's a bare array of objects, or a dict
 * whose `rows`/`items`/`groups` key holds one. Kept in sync with the same
 * key-alias step in the backend's flatten_for_export() (apps/reports/exporters.py)
 * so a report renders as a table on screen exactly when it exports as one.
 */
function extractFlatRows(payload: ReportPayload | null): Record<string, unknown>[] | null {
  if (payload === null) return null
  if (Array.isArray(payload)) {
    return payload.every((v) => typeof v === 'object' && v !== null)
      ? (payload as Record<string, unknown>[])
      : null
  }
  for (const key of ['rows', 'items', 'groups'] as const) {
    const v = (payload as Record<string, unknown>)[key]
    if (Array.isArray(v)) return v as Record<string, unknown>[]
  }
  return null
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
  const [showExportModal, setShowExportModal] = useState(false)

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

  // A payload renders as a plain table whenever it's already row-shaped: a
  // bare array (trial-balance), or a dict whose `rows`/`items`/`groups` key
  // holds a flat list of same-shaped objects. This mirrors the backend's
  // flatten_for_export() key-alias step (apps/reports/exporters.py) so the
  // screen and the Excel/PDF export agree on which reports are "tables".
  // Anything else (accounts/entries/notes/balance-sheet/P&L/tax-summary
  // shapes) is handled by <NestedSections> below instead.
  const rows = extractFlatRows(payload)
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
            onClick={() => setShowExportModal(true)}
            disabled={catalogLoading || catalog.length === 0}
            className="btn-ghost text-xs flex items-center gap-1.5 disabled:opacity-40"
            title="Export several reports at once"
          >
            <FileSpreadsheet size={14} /> Export Reports
          </button>
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

      {showExportModal && (
        <ExportReportsModal
          grouped={grouped}
          period={period}
          onClose={() => setShowExportModal(false)}
        />
      )}

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
                  {/* Export is gated on "do we have any payload at all", not on
                      the payload happening to be flat `rows` — the backend's
                      flatten_for_export() (apps/reports/exporters.py) can turn
                      every shape the registry returns into an exportable
                      table, including the nested ones rendered via
                      <NestedSections> below. */}
                  <button
                    onClick={() => handleExport('excel')}
                    disabled={!!exporting || running || payload === null}
                    title="Download as Excel"
                    className="btn-ghost text-xs flex items-center gap-1.5 disabled:opacity-40"
                  >
                    {exporting === 'excel' ? <Loader2 size={13} className="animate-spin" /> : <Download size={13} />}
                    Excel
                  </button>
                  <button
                    onClick={() => handleExport('pdf')}
                    disabled={!!exporting || running || payload === null}
                    title="Download as PDF"
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
                <NestedSections payload={payload} />
              )}

              {/* Totals strip — surfaced from common summary keys (only
                  meaningful for object-shaped payloads; a bare-array payload
                  like trial-balance has no top-level `total`/`totals` key). */}
              {payload && !running && !Array.isArray(payload) && (
                <TotalsStrip payload={payload} />
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}

// ─── Nested (non-flat-table) report rendering ────────────────────────────────
//
// A handful of registry reports don't reduce to one flat table — gl-detail and
// cash-register are grouped per account, journal-register is grouped per entry,
// balance-sheet has three sections, profit-loss/tax-summary are a handful of
// summary figures rather than a table, etc. Each shape below gets its own small,
// real (non-JSON-dump) renderer. This mirrors — and must be kept in sync with —
// the equivalent shape dispatch in the backend's flatten_for_export()
// (backend/apps/reports/exporters.py), so a report looks the same on screen as
// it does in its Excel/PDF export.

type Row = Record<string, unknown>

/** Small bordered table used by every section renderer below. */
function MiniTable({ columns, rows, moneyCols }: { columns: string[]; rows: Row[]; moneyCols?: Set<string> }) {
  if (rows.length === 0) return <p className="text-sm text-slate-500 py-2">None.</p>
  return (
    <div className="overflow-x-auto border border-surface-700 rounded-lg">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-surface-700 bg-surface-800/60">
            {columns.map((c) => (
              <th key={c} className="px-3 py-2 text-left text-[11px] font-semibold text-slate-400 uppercase tracking-wider whitespace-nowrap">
                {prettify(c)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-b border-surface-800 last:border-0">
              {columns.map((c) => (
                <td key={c} className={`px-3 py-2 whitespace-nowrap ${
                  moneyCols?.has(c) || isMoneyColumn(c) ? 'font-mono text-slate-200 text-right' : 'text-slate-300'
                }`}>
                  {renderCell(c, r[c])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** Label/value pairs rendered as a two-column strip — for reports that are
 * fundamentally a handful of summary figures (Profit & Loss, Tax Summary)
 * rather than a table of records. */
function KeyValueGrid({ pairs }: { pairs: { label: string; value: unknown }[] }) {
  return (
    <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3">
      {pairs.map(({ label, value }) => {
        const isNumeric = typeof value === 'number' || (!isNaN(Number(value)) && value !== '' && value !== null)
        // "Gross Margin Pct"/"Net Margin Pct" etc. are percentages, not money —
        // formatCurrency() would print "₦100.00" for a 100% margin otherwise.
        const isPercent = /pct|percent|%/i.test(label)
        return (
          <div key={label} className="p-3 bg-surface-800/60 border border-surface-700 rounded-lg">
            <p className="text-[11px] text-slate-500 uppercase tracking-wider">{label}</p>
            <p className="text-sm font-mono text-white mt-0.5">
              {!isNumeric ? String(value ?? '—') : isPercent ? `${value}%` : formatCurrency(String(value))}
            </p>
          </div>
        )
      })}
    </div>
  )
}

function isRecord(v: unknown): v is Row {
  return typeof v === 'object' && v !== null && !Array.isArray(v)
}

/** Renders a non-flat-table payload with a shape-specific view. Falls back to
 * a generic (still non-JSON) key/value + labelled-list rendering for any
 * shape not explicitly recognised, so nothing regresses to a raw dump. */
function NestedSections({ payload }: { payload: ReportPayload }) {
  // Defensive edge case: an array whose entries aren't all plain objects
  // (extractFlatRows already rejected it as a table) — just list the values.
  if (Array.isArray(payload)) {
    return (
      <div className="p-5">
        <ul className="list-disc list-inside text-sm text-slate-300 space-y-1">
          {payload.map((v, i) => <li key={i}>{String(v)}</li>)}
        </ul>
      </div>
    )
  }

  const data = payload as Row

  // Per-account ledger detail: gl-detail, cash-register.
  if (Array.isArray(data.accounts)) {
    const accounts = data.accounts as Row[]
    return (
      <div className="p-5 space-y-5">
        {accounts.length === 0 && <p className="text-sm text-slate-500">No accounts with activity in this period.</p>}
        {accounts.map((acct, i) => {
          const lines = (acct.lines as Row[]) ?? []
          return (
            <div key={i}>
              <div className="flex items-baseline justify-between mb-1.5">
                <h3 className="text-sm font-semibold text-white">{String(acct.account_code)} — {String(acct.account_name)}</h3>
                <p className="text-xs text-slate-500">
                  Opening {money(acct.opening_balance)} · Closing <span className="text-slate-300 font-mono">{money(acct.closing_balance)}</span>
                </p>
              </div>
              <MiniTable
                columns={['date', 'reference', 'description', 'debit', 'credit', 'balance']}
                rows={lines}
              />
            </div>
          )
        })}
      </div>
    )
  }

  // Journal register: one section per posted entry, with its lines.
  if (Array.isArray(data.entries)) {
    const entries = data.entries as Row[]
    return (
      <div className="p-5 space-y-5">
        {entries.length === 0 && <p className="text-sm text-slate-500">No journal entries in this period.</p>}
        {entries.map((entry, i) => {
          const lines = (entry.lines as Row[]) ?? []
          return (
            <div key={i}>
              <h3 className="text-sm font-semibold text-white mb-1.5">
                {String(entry.date)} · {String(entry.reference)}
                <span className="text-slate-500 font-normal ml-2">{String(entry.description ?? '')}</span>
              </h3>
              <MiniTable columns={['account_code', 'account_name', 'description', 'debit', 'credit']} rows={lines} />
            </div>
          )
        })}
      </div>
    )
  }

  // Notes to the financial statements — a short numbered list.
  if (Array.isArray(data.notes)) {
    const notes = data.notes as Row[]
    return (
      <div className="p-5 space-y-4">
        {notes.map((n, i) => (
          <div key={i}>
            <h3 className="text-sm font-semibold text-white">{String(n.number)}. {String(n.title)}</h3>
            <p className="text-sm text-slate-400 mt-0.5">{String(n.body || '—')}</p>
          </div>
        ))}
      </div>
    )
  }

  // Balance Sheet: assets / liabilities / equity sections + grand totals.
  if (Array.isArray(data.assets) && Array.isArray(data.liabilities) && Array.isArray(data.equity)) {
    const sections: [string, Row[], unknown][] = [
      ['Assets', data.assets as Row[], data.total_assets],
      ['Liabilities', data.liabilities as Row[], data.total_liabilities],
      ['Equity', data.equity as Row[], data.total_equity],
    ]
    return (
      <div className="p-5 space-y-5">
        {sections.map(([label, rows, total]) => (
          <div key={label}>
            <div className="flex items-baseline justify-between mb-1.5">
              <h3 className="text-sm font-semibold text-white">{label}</h3>
              <p className="text-xs text-slate-500">Total <span className="text-slate-300 font-mono">{money(total)}</span></p>
            </div>
            <MiniTable columns={['code', 'name', 'balance']} rows={rows} />
          </div>
        ))}
        {data.balanced === false && (
          <p className="text-xs text-amber-400">This balance sheet does not balance — check for unposted journal entries.</p>
        )}
      </div>
    )
  }

  // Profit & Loss: a nested `revenue` breakdown plus top-level summary figures.
  if (isRecord(data.revenue) && 'gross_profit' in data) {
    const revenue = data.revenue as Row
    const pairs = [
      ...Object.entries(revenue).map(([k, v]) => ({ label: `Revenue — ${prettify(k)}`, value: v })),
      ...(['cost_of_goods_sold', 'gross_profit', 'gross_margin_pct', 'operating_expenses',
           'miscellaneous_income', 'net_profit', 'net_margin_pct'] as const)
        .filter((k) => k in data)
        .map((k) => ({ label: prettify(k), value: data[k] })),
    ]
    return <div className="p-5"><KeyValueGrid pairs={pairs} /></div>
  }

  // Tax Summary: a nested `vat` breakdown plus WHT/PAYE scalars.
  if (isRecord(data.vat) && ('wht_withheld' in data || 'paye_payable' in data)) {
    const vat = data.vat as Row
    const pairs = [
      ...Object.entries(vat)
        .filter(([k]) => !['period_start', 'period_end'].includes(k))
        .map(([k, v]) => ({ label: `VAT — ${prettify(k)}`, value: v })),
      ...(['wht_withheld', 'paye_payable'] as const)
        .filter((k) => k in data)
        .map((k) => ({ label: prettify(k), value: data[k] })),
    ]
    return <div className="p-5"><KeyValueGrid pairs={pairs} /></div>
  }

  // Financial Report Pack: P&L + Balance Sheet + Trial Balance bundled — show
  // each sub-report using the same renderers as if it were selected directly.
  if (isRecord(data.profit_and_loss) && isRecord(data.balance_sheet) && Array.isArray(data.trial_balance)) {
    return (
      <div className="p-5 space-y-8">
        <section>
          <h2 className="text-sm font-bold text-white uppercase tracking-wide mb-3">Profit &amp; Loss</h2>
          <NestedSections payload={data.profit_and_loss as Row} />
        </section>
        <section>
          <h2 className="text-sm font-bold text-white uppercase tracking-wide mb-3">Balance Sheet</h2>
          <NestedSections payload={data.balance_sheet as Row} />
        </section>
        <section>
          <h2 className="text-sm font-bold text-white uppercase tracking-wide mb-3">Trial Balance</h2>
          <MiniTable columns={['code', 'name', 'type', 'balance']} rows={data.trial_balance as Row[]} />
        </section>
      </div>
    )
  }

  // Fallback: any other dict of mostly-scalar summary figures (e.g. Cash Flow,
  // Net Tax Report) — show the scalar keys as a key/value grid, and any
  // leftover nested values as a labelled sub-table, rather than a JSON dump.
  const scalarPairs = Object.entries(data)
    .filter(([k, v]) => !['period_start', 'period_end', 'as_of'].includes(k) && typeof v !== 'object')
    .map(([k, v]) => ({ label: prettify(k), value: v }))
  const nestedEntries = Object.entries(data).filter(([, v]) => typeof v === 'object' && v !== null)

  return (
    <div className="p-5 space-y-5">
      {scalarPairs.length > 0 && <KeyValueGrid pairs={scalarPairs} />}
      {nestedEntries.map(([key, value]) => (
        <div key={key}>
          <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-1.5">{prettify(key)}</h3>
          {Array.isArray(value) && value.every(isRecord) ? (
            <MiniTable columns={value.length ? Object.keys(value[0] as Row) : []} rows={value as Row[]} />
          ) : isRecord(value) ? (
            <KeyValueGrid pairs={Object.entries(value).map(([k, v]) => ({ label: prettify(k), value: v }))} />
          ) : (
            <p className="text-sm text-slate-300">{String(value)}</p>
          )}
        </div>
      ))}
      {scalarPairs.length === 0 && nestedEntries.length === 0 && (
        <p className="text-sm text-slate-500">Nothing to show for this period.</p>
      )}
    </div>
  )
}

/** Shows scalar summary values (total, totals{}) under the table. */
function TotalsStrip({ payload }: { payload: Record<string, unknown> }) {
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

// ─── Bulk export modal ────────────────────────────────────────────────────────
//
// Lets the user pick a subset (or all) of the reports in the tree, choose
// between one combined workbook or a zip of separate files, and either
// download the result or have it emailed via the org's configured SMTP.
// Hits POST /reports/export-bulk/ (ReportBulkExportView in
// backend/apps/reports/views.py), which runs every selected report through
// the same flatten_for_export() normaliser the single-report export uses.

type GroupedCategory = { name: string; icon: React.ElementType; reports: CatalogEntry[] }

function ExportReportsModal({
  grouped, period, onClose,
}: {
  grouped: GroupedCategory[]
  period: PeriodValue
  onClose: () => void
}) {
  const userEmail = useAuthStore((s) => s.user?.email) ?? ''
  const allKeys = useMemo(() => grouped.flatMap((c) => c.reports.map((r) => r.key)), [grouped])

  const [selectedKeys, setSelectedKeys] = useState<Set<string>>(() => new Set(allKeys))
  const [combine, setCombine] = useState(true)
  const [mode, setMode] = useState<'download' | 'email'>('download')
  const [emailTo, setEmailTo] = useState(userEmail)
  const [submitting, setSubmitting] = useState(false)

  const allSelected = selectedKeys.size === allKeys.length
  const toggleAll = () => setSelectedKeys(allSelected ? new Set() : new Set(allKeys))
  const toggleKey = (key: string) => setSelectedKeys((prev) => {
    const next = new Set(prev)
    if (next.has(key)) { next.delete(key) } else { next.add(key) }
    return next
  })
  const toggleCategory = (cat: GroupedCategory) => {
    const catKeys = cat.reports.map((r) => r.key)
    const allCatSelected = catKeys.every((k) => selectedKeys.has(k))
    setSelectedKeys((prev) => {
      const next = new Set(prev)
      catKeys.forEach((k) => (allCatSelected ? next.delete(k) : next.add(k)))
      return next
    })
  }

  const handleSubmit = async () => {
    if (selectedKeys.size === 0) { toast.error('Select at least one report'); return }
    if (mode === 'email' && !/^\S+@\S+\.\S+$/.test(emailTo)) { toast.error('Enter a valid email address'); return }

    setSubmitting(true)
    try {
      const body = {
        keys: Array.from(selectedKeys),
        period: period.period,
        date_from: period.date_from,
        date_to: period.date_to,
        combine,
      }
      if (mode === 'email') {
        const { data } = await reportApi.exportBulkEmail({ ...body, email_to: emailTo })
        toast.success(data?.message ?? `Sent to ${emailTo}`)
      } else {
        const res = await reportApi.exportBulkDownload(body)
        const filename = combine ? 'audity-reports.xlsx' : 'audity-reports.zip'
        await saveBlobFile(res.data as Blob, filename)
        toast.success(`Downloaded ${selectedKeys.size} report(s)`)
      }
      onClose()
    } catch (err) {
      const apiErr = (err as { response?: { data?: { error?: unknown } } })?.response?.data?.error
      toast.error(typeof apiErr === 'string' ? apiErr : 'Export failed — please try again')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/60" onClick={onClose} />
      <div className="relative card w-full max-w-lg max-h-[85vh] flex flex-col">
        <div className="px-5 py-4 border-b border-surface-700 flex items-center justify-between shrink-0">
          <h2 className="text-base font-semibold text-white">Export Reports</h2>
          <button onClick={onClose} className="text-slate-400 hover:text-white"><X size={18} /></button>
        </div>

        {/* Report checklist, grouped by category — same tree as the sidebar. */}
        <div className="p-5 overflow-y-auto space-y-4 flex-1">
          <div className="flex items-center justify-between">
            <p className="text-xs text-slate-400">{selectedKeys.size} of {allKeys.length} selected</p>
            <button onClick={toggleAll} className="text-xs text-brand-400 hover:text-brand-300 font-medium">
              {allSelected ? 'Deselect all' : 'Select all'}
            </button>
          </div>

          {grouped.map((cat) => {
            const catKeys = cat.reports.map((r) => r.key)
            const allCatSelected = catKeys.every((k) => selectedKeys.has(k))
            return (
              <div key={cat.name}>
                <label className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-slate-400 mb-1.5 cursor-pointer">
                  <input type="checkbox" checked={allCatSelected} onChange={() => toggleCategory(cat)} className="accent-brand-500" />
                  {cat.name}
                </label>
                <div className="ml-5 grid sm:grid-cols-2 gap-x-3 gap-y-1">
                  {cat.reports.map((r) => (
                    <label key={r.key} className="flex items-center gap-2 text-sm text-slate-300 cursor-pointer py-0.5">
                      <input type="checkbox" checked={selectedKeys.has(r.key)} onChange={() => toggleKey(r.key)} className="accent-brand-500" />
                      <span className="truncate">{r.label}</span>
                    </label>
                  ))}
                </div>
              </div>
            )
          })}
        </div>

        {/* Options + submit */}
        <div className="p-5 border-t border-surface-700 space-y-4 shrink-0">
          <div>
            <p className="text-xs text-slate-400 mb-1.5">File format</p>
            <div className="flex gap-2">
              <button
                onClick={() => setCombine(true)}
                className={`flex-1 px-3 py-2 rounded-lg text-xs border transition-colors ${
                  combine ? 'border-brand-500 bg-brand-500/10 text-white' : 'border-surface-700 text-slate-400'
                }`}
              >
                One workbook<br /><span className="text-[10px] text-slate-500">a sheet per report</span>
              </button>
              <button
                onClick={() => setCombine(false)}
                className={`flex-1 px-3 py-2 rounded-lg text-xs border transition-colors ${
                  !combine ? 'border-brand-500 bg-brand-500/10 text-white' : 'border-surface-700 text-slate-400'
                }`}
              >
                Separate files<br /><span className="text-[10px] text-slate-500">.zip, one file per report</span>
              </button>
            </div>
          </div>

          <div>
            <p className="text-xs text-slate-400 mb-1.5">Delivery</p>
            <div className="flex gap-2 mb-2">
              <button
                onClick={() => setMode('download')}
                className={`flex-1 px-3 py-2 rounded-lg text-xs border flex items-center justify-center gap-1.5 transition-colors ${
                  mode === 'download' ? 'border-brand-500 bg-brand-500/10 text-white' : 'border-surface-700 text-slate-400'
                }`}
              >
                <Download size={13} /> Download
              </button>
              <button
                onClick={() => setMode('email')}
                className={`flex-1 px-3 py-2 rounded-lg text-xs border flex items-center justify-center gap-1.5 transition-colors ${
                  mode === 'email' ? 'border-brand-500 bg-brand-500/10 text-white' : 'border-surface-700 text-slate-400'
                }`}
              >
                <Mail size={13} /> Email
              </button>
            </div>
            {mode === 'email' && (
              <input
                type="email"
                value={emailTo}
                onChange={(e) => setEmailTo(e.target.value)}
                placeholder="recipient@example.com"
                className="input w-full text-sm"
              />
            )}
          </div>

          <button
            onClick={handleSubmit}
            disabled={submitting || selectedKeys.size === 0}
            className="btn-primary w-full flex items-center justify-center gap-2 disabled:opacity-50"
          >
            {submitting ? <Loader2 size={15} className="animate-spin" /> : (mode === 'email' ? <Mail size={15} /> : <Download size={15} />)}
            {submitting ? 'Working…' : mode === 'email' ? `Email ${selectedKeys.size} report(s)` : `Download ${selectedKeys.size} report(s)`}
          </button>
        </div>
      </div>
    </div>
  )
}

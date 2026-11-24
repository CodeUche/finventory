/**
 * The Reports home (Option B): one tile per business question, and each question's list of reports.
 *
 * Tile figures are real numbers from endpoints that already exist, read as the server sends them
 * (decimal strings, no sums or maths here). A figure the person may not read is not shown, and a
 * figure whose request fails is dropped, so there is never a blank placeholder.
 */
import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { ChevronRight, Loader2 } from 'lucide-react'
import { reportApi } from '@/services/api'
import { formatCurrency } from '@/lib/utils'
import { useReportNeeds } from '@/hooks/useReportNeeds'
import type { PeriodValue } from '@/components/PeriodSelector'
import {
  QUICK_LINKS, type TileFigure, type VisibleEntry, type VisibleGroup,
} from '@/lib/reportGroups'
import type { Need } from '@/lib/reportGroups'
import type { PnL } from '@/types'

type Figures = Partial<Record<TileFigure, string>> & { pnl?: PnL }

/** Plain label under each tile figure. */
export const FIGURE_LABEL: Record<TileFigure, string> = {
  netProfit: 'Net profit',
  receivable: 'Owed to you now',
  payable: 'You owe suppliers now',
  cash: 'Net cash movement',
  vat: 'Estimated VAT for the period',
}

function periodParams(p: PeriodValue): Record<string, string> {
  const out: Record<string, string> = { period: p.period }
  if (p.date_from) out.date_from = p.date_from
  if (p.date_to) out.date_to = p.date_to
  return out
}

/** Fetches only the figures this person may read. A failed request just drops its figure. */
function useHomeFigures(period: PeriodValue, catalogKeys: ReadonlySet<string>, ready: boolean) {
  const can = useReportNeeds()
  const [figures, setFigures] = useState<Figures>({})
  const [loading, setLoading] = useState(true)
  const wantPnl = can('reports') && can('profitLoss')
  const wantAr = can('reports') && can('arAging')
  const wantAp = can('reports') && can('apAging')
  const wantVat = can('reports') && can('tax') && catalogKeys.has('vat-return')
  const wantCash = catalogKeys.has('cash-flow')
  const periodKey = `${period.period}|${period.date_from ?? ''}|${period.date_to ?? ''}`

  useEffect(() => {
    if (!ready) return
    let cancelled = false
    const params = periodParams(period)
    const pick = async <T,>(want: boolean, run: () => Promise<{ data: T }>): Promise<T | null> => {
      if (!want) return null
      try { return (await run()).data } catch { return null }
    }
    setLoading(true)
    Promise.all([
      pick<PnL>(wantPnl, () => reportApi.pnl(params)),
      pick<{ total_outstanding?: string }>(wantAr, () => reportApi.arAging()),
      pick<{ total_outstanding?: string }>(wantAp, () => reportApi.apAging()),
      pick<{ net_cash_flow?: string }>(wantCash, () => reportApi.cashFlow(params)),
      pick<{ net_vat_payable?: string }>(wantVat, () => reportApi.vatSummary(params)),
    ]).then(([pnl, ar, ap, cash, vat]) => {
      if (cancelled) return
      const next: Figures = {}
      if (pnl) { next.pnl = pnl; next.netProfit = pnl.net_profit }
      if (ar?.total_outstanding != null) next.receivable = ar.total_outstanding
      if (ap?.total_outstanding != null) next.payable = ap.total_outstanding
      if (cash?.net_cash_flow != null) next.cash = cash.net_cash_flow
      if (vat?.net_vat_payable != null) next.vat = vat.net_vat_payable
      setFigures(next)
      setLoading(false)
    })
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `period` is covered by periodKey
  }, [ready, periodKey, wantPnl, wantAr, wantAp, wantVat, wantCash])

  return { figures, loading }
}

/** The headline strip. Four numbers straight from the Profit & Loss report, nothing recalculated. */
function BusinessSummary({ pnl }: { pnl: PnL }) {
  const items: { label: string; value: string }[] = [
    { label: 'Net sales', value: pnl.revenue.gross_sales },
    { label: 'Gross profit', value: pnl.gross_profit },
    { label: 'Operating expenses', value: pnl.operating_expenses },
    { label: 'Net profit', value: pnl.net_profit },
  ]
  return (
    <section aria-label="Business summary" data-testid="business-summary">
      <h2 className="rp-title mb-2">Business summary</h2>
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {items.map((it) => (
          <div key={it.label} className="rp-tile">
            <p className="rp-tile-label">{it.label}</p>
            <p className="rp-tile-value">{formatCurrency(it.value)}</p>
          </div>
        ))}
      </div>
    </section>
  )
}

function QuestionTile({ vg, figure }: { vg: VisibleGroup; figure?: string }) {
  const { group, entries } = vg
  const Icon = group.icon
  return (
    <Link to={`/reports/all?group=${group.id}`} className="rp-q-tile" data-testid={`group-tile-${group.id}`}>
      <span className="rp-q-head">
        <Icon size={18} aria-hidden="true" />
        <span className="rp-q-name">{group.name}</span>
      </span>
      <span className="rp-q-blurb">{group.blurb}</span>
      {group.figure && figure !== undefined && (
        <span className="rp-q-figure">
          <span className="rp-q-value rp-nums">{formatCurrency(figure)}</span>
          <span className="rp-q-flabel">{FIGURE_LABEL[group.figure]}</span>
        </span>
      )}
      <span className="rp-q-foot">
        {entries.length} {entries.length === 1 ? 'report' : 'reports'}
        <ChevronRight size={14} aria-hidden="true" />
      </span>
    </Link>
  )
}

export function ReportsHomeView({
  groups, period, catalogKeys, catalogReady,
}: {
  groups: VisibleGroup[]
  period: PeriodValue
  catalogKeys: ReadonlySet<string>
  catalogReady: boolean
}) {
  const can = useReportNeeds()
  const { figures, loading } = useHomeFigures(period, catalogKeys, catalogReady)
  const quick = useMemo(() => QUICK_LINKS.filter((q) => q.need.every((n: Need) => can(n))), [can])

  if (!catalogReady) {
    return <div className="flex justify-center py-20 text-slate-500"><Loader2 size={22} className="animate-spin" /></div>
  }
  if (groups.length === 0) {
    return (
      <div className="card py-16 text-center" data-testid="report-no-access">
        <p className="text-slate-300 font-medium">Some reports need extra permission. Ask an owner or admin.</p>
      </div>
    )
  }
  return (
    <div className="space-y-6">
      {figures.pnl && <BusinessSummary pnl={figures.pnl} />}
      <section aria-label="Report questions">
        <h2 className="rp-title mb-2">Pick a question</h2>
        <div className="grid sm:grid-cols-2 xl:grid-cols-3 gap-3" aria-busy={loading}>
          {groups.map((vg) => (
            <QuestionTile key={vg.group.id} vg={vg} figure={vg.group.figure ? figures[vg.group.figure] : undefined} />
          ))}
        </div>
      </section>
      {quick.length > 0 && (
        <section aria-label="Quick links" data-testid="quick-links">
          <h2 className="rp-title mb-2">Quick links</h2>
          <div className="flex flex-wrap gap-2">
            {quick.map((q) => (
              <Link key={q.to} to={q.to} className="rp-chip">{q.label}</Link>
            ))}
          </div>
        </section>
      )}
    </div>
  )
}

function EntryRow({ ve }: { ve: VisibleEntry }) {
  const { entry, main, also } = ve
  return (
    <li className="rp-entry" data-testid={`report-entry-${entry.id}`}>
      <Link to={main.to} className="rp-entry-main">
        <span className="rp-entry-name">
          {entry.label}
          {entry.badge && <span className="rp-badge">{entry.badge}</span>}
        </span>
        <span className="rp-entry-blurb">{entry.blurb}</span>
      </Link>
      {also.length > 0 && (
        <span className="rp-entry-also">
          {also.map((t) => (
            <Link key={t.to + t.label} to={t.to} className="rp-chip rp-chip-sm">{t.label}</Link>
          ))}
        </span>
      )}
    </li>
  )
}

export function GroupListView({ vg }: { vg: VisibleGroup }) {
  return (
    <div className="space-y-4">
      <p className="text-sm text-slate-400">{vg.group.blurb}</p>
      <ul className="rp-entries">
        {vg.entries.map((ve) => <EntryRow key={ve.entry.id} ve={ve} />)}
      </ul>
    </div>
  )
}

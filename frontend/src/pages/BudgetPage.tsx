import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useDataRefresh } from '@/hooks/useDataRefresh'
import { Plus, X, PieChart, Loader2, ChevronDown, ChevronUp, HelpCircle, RefreshCw, BarChart3, ShieldCheck, Landmark, Briefcase, Grid3x3, LayoutList, LayoutGrid, Upload, FileText, Download } from 'lucide-react'
import toast from 'react-hot-toast'
import { budgetApi, budgetLineApi, accountingApi, bypassNextGets } from '@/services/api'
import { formatCurrency, formatAmountInput, stripCommas } from '@/lib/utils'
import { sumBudgetedAmount } from '@/lib/budgetGrid'
import AmountInput from '@/components/AmountInput'
import DateInput from '@/components/DateInput'
import BudgetGridEditor from '@/components/BudgetGridEditor'
import { EXPENSE_CATEGORIES, INCOME_CATEGORIES } from '@/lib/categories'
import { useAuthStore } from '@/store/authStore'
import { saveBlobFile } from '@/lib/saveBlobFile'
import type { Budget, Account } from '@/types'

interface BudgetForm { name: string; fiscal_year: string; period_type: string; notes: string; budget_type: string; start_date: string; end_date: string }
interface LineForm { category_name: string; custom_name: string; category_type: string; sub_category: string; period_month: string; budgeted_amount: string; forecast_amount: string; unit_price: string; quantity: string; description: string; account: string }
interface VarianceRow {
  id: string; category_name: string; category_type: 'expense' | 'revenue'; sub_category?: string
  period_month: number | null; budgeted_amount: string; forecast_amount?: string | null
  actual_amount: string; variance: string; variance_pct: number; over_budget: boolean
}

const now = new Date()
const CURRENT_YEAR = now.getFullYear()
// Prior-year budgets are permitted: an accountant loading last year's budget to
// compare against this year's is a normal thing to do, and the old hard floor at
// CURRENT_YEAR made it impossible. The bounds below exist only to stop a typo
// ("202", "20261") creating a nonsense fiscal year.
const MIN_YEAR = CURRENT_YEAR - 10
const MAX_YEAR = CURRENT_YEAR + 10
const BLANK_BUDGET: BudgetForm = { name: '', fiscal_year: String(CURRENT_YEAR), period_type: 'monthly', notes: '', budget_type: 'operational', start_date: '', end_date: '' }
const BLANK_LINE: LineForm = { category_name: '', custom_name: '', category_type: 'expense', sub_category: '', period_month: '', budgeted_amount: '', forecast_amount: '', unit_price: '', quantity: '1', description: '', account: '' }

const MONTH_NAMES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const STATUS_BADGE: Record<string, string> = { draft: 'badge-slate', active: 'badge-green', closed: 'badge-red' }
const TYPE_BADGE: Record<string, string> = { operational: 'badge-slate', capital: 'badge-blue' }

/** Best-guess GL account for a category name — simple client-side keyword
 * match (category name / account name substring, either direction). This is
 * a UI convenience only: the suggestion is always editable/overridable and
 * nothing forces it — the account field stays null unless a human confirms
 * one, on save or otherwise. */
function suggestAccount(categoryName: string, accounts: Account[]): Account | null {
  const needle = categoryName.trim().toLowerCase()
  if (!needle || needle === 'other (custom)') return null
  const words = needle.split(/\s+/).filter((w) => w.length > 2)
  for (const acc of accounts) {
    const hay = acc.name.toLowerCase()
    if (hay.includes(needle) || needle.includes(hay)) return acc
  }
  for (const acc of accounts) {
    const hay = acc.name.toLowerCase()
    if (words.some((w) => hay.includes(w))) return acc
  }
  return null
}

function isManagerOrAbove(memberRole: string | null, isSuperuser?: boolean): boolean {
  return !!isSuperuser || memberRole === 'owner' || memberRole === 'admin' || memberRole === 'manager'
}

export default function BudgetPage() {
  const { memberRole, user, organisation } = useAuthStore()
  const [budgets, setBudgets] = useState<Budget[]>([])
  const [accounts, setAccounts] = useState<Account[]>([])
  const [loading, setLoading] = useState(true)
  const [expandedBudget, setExpandedBudget] = useState<string | null>(null)

  const [showBudgetModal, setShowBudgetModal] = useState(false)
  const [budgetForm, setBudgetForm] = useState<BudgetForm>(BLANK_BUDGET)
  const [savingBudget, setSavingBudget] = useState(false)

  const [addLineBudgetId, setAddLineBudgetId] = useState<string | null>(null)
  const [lineForm, setLineForm] = useState<LineForm>(BLANK_LINE)
  const [accountTouched, setAccountTouched] = useState(false)
  const [savingLine, setSavingLine] = useState(false)

  const [activatingBudget, setActivatingBudget] = useState<string | null>(null)
  const [approvingBudget, setApprovingBudget] = useState<string | null>(null)
  const [showVarianceHelp, setShowVarianceHelp] = useState(false)
  const [gridEditorBudget, setGridEditorBudget] = useState<Budget | null>(null)
  const [viewMode, setViewMode] = useState<'list' | 'grid'>('list')

  // Phase 6 (B7): per-budget draft tax-rate input, keyed by budget id, so
  // editing one budget's rate doesn't clobber another's in-progress edit.
  const [taxRateDraft, setTaxRateDraft] = useState<Record<string, string>>({})
  const [savingTaxRate, setSavingTaxRate] = useState<string | null>(null)

  // Phase 7 (B6): per-budget line-type filter — "a filtered single view
  // instead of separate Revenue/Expense budget pages" (confirmed design).
  const [lineTypeFilter, setLineTypeFilter] = useState<Record<string, 'all' | 'revenue' | 'expense'>>({})
  // Phase 7 (B6c): which line's attachment upload is in flight.
  const [uploadingAttachment, setUploadingAttachment] = useState<string | null>(null)

  const load = async () => {
    setLoading(true)
    try {
      const bRes = await budgetApi.list()
      setBudgets(bRes.data.results ?? bRes.data)
    } catch { toast.error('Failed to load budgets') }
    finally { setLoading(false) }
  }

  const loadAccounts = async () => {
    try {
      const { data } = await accountingApi.accounts()
      setAccounts(data.results ?? data)
    } catch { /* GL account picker is optional — silently unavailable is fine */ }
  }

  useEffect(() => { load(); loadAccounts() }, [])
  useDataRefresh(load)

  const handleCreateBudget = async () => {
    if (!budgetForm.name.trim()) { toast.error('Budget name is required'); return }
    const year = parseInt(budgetForm.fiscal_year)
    if (isNaN(year) || year < MIN_YEAR || year > MAX_YEAR) {
      toast.error(`Fiscal year must be between ${MIN_YEAR} and ${MAX_YEAR}`)
      return
    }
    setSavingBudget(true)
    try {
      await budgetApi.create({
        name: budgetForm.name, fiscal_year: year, period_type: budgetForm.period_type, notes: budgetForm.notes,
        budget_type: budgetForm.budget_type,
        ...(budgetForm.start_date ? { start_date: budgetForm.start_date } : {}),
        ...(budgetForm.end_date ? { end_date: budgetForm.end_date } : {}),
      })
      toast.success('Budget created')
      setShowBudgetModal(false)
      setBudgetForm(BLANK_BUDGET)
      load()
    } catch { toast.error('Failed to create budget') }
    finally { setSavingBudget(false) }
  }

  const handleActivate = async (b: Budget) => {
    const newStatus = b.status === 'draft' ? 'active' : b.status === 'active' ? 'closed' : 'active'
    setActivatingBudget(b.id)
    try {
      await budgetApi.update(b.id, { status: newStatus })
      toast.success(`Budget ${newStatus === 'active' ? 'activated' : newStatus === 'closed' ? 'closed' : 'reopened'}`)
      load()
    } catch (err: any) {
      const msg = err?.response?.data?.detail || err?.response?.data?.status?.[0] || 'Failed to update status'
      toast.error(msg)
    } finally {
      setActivatingBudget(null)
    }
  }

  const handleApprove = async (b: Budget) => {
    setApprovingBudget(b.id)
    try {
      await budgetApi.approve(b.id)
      toast.success('Budget approved')
      // approve's URL has a UUID mid-path (/budgets/{id}/approve/, not a
      // trailing one), so the axios write-through cache's invalidation
      // heuristic (buildListUrl, keyed on a TRAILING UUID) can't match it —
      // same gap already documented and worked around for bulk_lines below
      // (BudgetGridEditor's onSaved) and for other action-suffixed
      // endpoints elsewhere in services/api.ts. Without this, the list
      // keeps serving the pre-approval snapshot (no "Approved by" badge,
      // Approve button still showing) for up to 5 minutes even though the
      // approval genuinely succeeded server-side.
      bypassNextGets()
      load()
    } catch (err: any) {
      const apiErr = err?.response?.data?.error
      const msg = typeof apiErr === 'string' ? apiErr : (apiErr?.message ?? err?.response?.data?.detail ?? 'Failed to approve budget')
      toast.error(msg)
    } finally {
      setApprovingBudget(null)
    }
  }

  const handleSaveTaxRate = async (b: Budget) => {
    const raw = taxRateDraft[b.id] ?? String(b.tax_rate ?? 0)
    const rate = parseFloat(raw)
    if (isNaN(rate)) { toast.error('Enter a valid tax rate'); return }
    setSavingTaxRate(b.id)
    try {
      await budgetApi.update(b.id, { tax_rate: rate })
      toast.success('Tax rate saved')
      load()
    } catch (err: any) {
      const apiErr = err?.response?.data?.error
      const msg = typeof apiErr === 'string' ? apiErr : (apiErr?.message ?? 'Failed to save tax rate')
      toast.error(msg)
    } finally {
      setSavingTaxRate(null)
    }
  }

  const handleUploadAttachment = async (lineId: string, file: File) => {
    setUploadingAttachment(lineId)
    try {
      await budgetLineApi.uploadAttachment(lineId, file)
      toast.success('Attachment uploaded')
      load()
    } catch (err: any) {
      const apiErr = err?.response?.data?.error
      const msg = typeof apiErr === 'string' ? apiErr : (apiErr?.message ?? 'Failed to upload attachment')
      toast.error(msg)
    } finally {
      setUploadingAttachment(null)
    }
  }

  // Phase 7 (B9/B10b): Budget Report export — a PDF (line detail + variance %,
  // same roll-up math as the header panel) and a CSV of the same rows.
  const downloadBudgetReportCSV = (budget: Budget, rows: VarianceRow[]) => {
    const header = ['Category', 'Sub-Category', 'Type', 'Month', 'Budgeted', 'Forecast', 'Actual', 'Variance', 'Variance %']
    const csvRows = rows.map((r) => [
      r.category_name, r.sub_category || '', r.category_type,
      r.period_month ? MONTH_NAMES[r.period_month - 1] : 'All',
      r.budgeted_amount, r.forecast_amount ?? '', r.actual_amount, r.variance, r.variance_pct.toFixed(1),
    ])
    const csv = [header, ...csvRows].map((row) =>
      row.map((cell) => `"${String(cell).replace(/"/g, '""')}"`).join(',')
    ).join('\n')
    saveBlobFile(new Blob([csv], { type: 'text/csv' }), `budget-report-${budget.name.replace(/\s+/g, '-')}-${budget.fiscal_year}.csv`)
  }

  const downloadBudgetReportPDF = async (budget: Budget, rows: VarianceRow[]) => {
    const { jsPDF } = await import('jspdf')
    const { default: autoTable } = await import('jspdf-autotable')
    const { applyDocHeader, buildTableStyle, addDocFooter, pdfMoney, COLORS, TYPE, resolveOrgLogo } = await import('@/lib/pdfUtils')

    const doc = new jsPDF({ unit: 'mm', format: 'a4', orientation: 'landscape' })
    doc.setLineHeightFactor(1.15)
    const pageW = doc.internal.pageSize.getWidth()

    const toRgb = (hex?: string): [number, number, number] => {
      const m = /^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex ?? '')
      if (!m) return [249, 115, 22]
      return [parseInt(m[1], 16), parseInt(m[2], 16), parseInt(m[3], 16)]
    }
    const BRAND = toRgb(organisation?.brand_color) as [number, number, number]
    const DARK = COLORS.DARK
    const MUTED = COLORS.MUTED
    const LIGHT = COLORS.LIGHT
    const RULE = COLORS.RULE
    const tmpl = organisation?.invoice_template ?? 'classic'
    const logoData: string | null = await resolveOrgLogo(organisation?.logo)
    const pdfFont = 'helvetica'
    const displayName = organisation?.show_company_name_on_pdf === false
      ? '' : (organisation?.invoice_company_name?.trim() || organisation?.name || 'Audity')

    let y = applyDocHeader(doc, {
      tmpl, pageW, BRAND, DARK, MUTED,
      landscape: true,
      logoData,
      displayName,
      orgAddress: organisation?.address,
      orgEmail: organisation?.email,
      orgPhone: organisation?.phone,
      pdfFont,
      showCompanyName: organisation?.show_company_name_on_pdf !== false,
      docTitle: 'BUDGET REPORT',
      metaRows: [
        ['Budget', budget.name],
        ['Fiscal Year', String(budget.fiscal_year)],
        ['Generated', new Date().toISOString().split('T')[0]],
      ],
    })

    // ── Roll-up KPI cards — same math as the on-screen panel ──────────────
    const totalIncome = sumBudgetedAmount(budget.lines.filter((l) => l.category_type === 'revenue'))
    const totalExpense = sumBudgetedAmount(budget.lines.filter((l) => l.category_type === 'expense'))
    const expectedProfit = totalIncome - totalExpense
    const taxRate = parseFloat(String(budget.tax_rate ?? 0)) || 0
    const tax = expectedProfit * (taxRate / 100)
    const budgetAmount = expectedProfit - tax
    const kpis = [
      { label: 'Total Income (A)', value: pdfMoney(totalIncome), color: DARK },
      { label: 'Total Expense (B)', value: pdfMoney(totalExpense), color: DARK },
      { label: 'Expected Profit (C)', value: pdfMoney(expectedProfit), color: expectedProfit < 0 ? COLORS.RED : COLORS.GREEN },
      { label: `Tax (D, ${taxRate}%)`, value: pdfMoney(tax), color: DARK },
      { label: 'Budget Amount (E)', value: pdfMoney(budgetAmount), color: DARK },
    ] as const
    const kpiW = (pageW - 20) / kpis.length
    kpis.forEach((k, i) => {
      const kx = 10 + i * kpiW
      doc.setFillColor(...LIGHT); doc.setDrawColor(...RULE); doc.setLineWidth(0.25)
      doc.roundedRect(kx, y, kpiW - 2, 22, 2, 2, 'FD')
      doc.setFontSize(TYPE.SMALL.size); doc.setFont(pdfFont, 'normal'); doc.setTextColor(...MUTED)
      doc.text(k.label.toUpperCase(), kx + (kpiW - 2) / 2, y + 7, { align: 'center' })
      doc.setFontSize(TYPE.H2.size); doc.setFont(pdfFont, 'bold'); doc.setTextColor(...k.color)
      doc.text(k.value, kx + (kpiW - 2) / 2, y + 16, { align: 'center' })
    })
    y += 26

    const body = rows.map((r) => [
      r.category_name, r.sub_category || '—', r.category_type,
      r.period_month ? MONTH_NAMES[r.period_month - 1] : 'All',
      pdfMoney(parseFloat(r.budgeted_amount)),
      r.forecast_amount ? pdfMoney(parseFloat(r.forecast_amount)) : '—',
      pdfMoney(parseFloat(r.actual_amount)),
      pdfMoney(parseFloat(r.variance)),
      `${r.variance_pct.toFixed(1)}%`,
    ])
    const overBudgetRows = rows.map((r, i) => (r.over_budget ? i : -1)).filter((i) => i >= 0)

    autoTable(doc, {
      ...buildTableStyle(BRAND, pdfFont, { landscape: true }),
      startY: y,
      head: [['Category', 'Sub-Category', 'Type', 'Month', 'Budgeted', 'Forecast', 'Actual', 'Variance', 'Variance %']],
      body,
      didParseCell: (data: any) => {
        if (data.section === 'body' && overBudgetRows.includes(data.row.index) && (data.column.index === 7 || data.column.index === 8)) {
          data.cell.styles.textColor = COLORS.RED
        }
      },
    })

    addDocFooter(doc, {
      orgName: organisation?.name ?? 'Company',
      docTitle: 'BUDGET REPORT',
      docRef: `${budget.name} (${budget.fiscal_year})`,
      BRAND,
      pdfFont,
      landscape: true,
    })

    await saveBlobFile(doc.output('blob'), `budget-report-${budget.name.replace(/\s+/g, '-')}-${budget.fiscal_year}.pdf`)
  }

  const [downloadingReport, setDownloadingReport] = useState<string | null>(null)
  const handleDownloadReport = async (budget: Budget, format: 'pdf' | 'csv') => {
    setDownloadingReport(budget.id)
    try {
      const { data } = await budgetApi.variance(budget.id)
      const rows = data as VarianceRow[]
      if (format === 'csv') downloadBudgetReportCSV(budget, rows)
      else await downloadBudgetReportPDF(budget, rows)
    } catch {
      toast.error('Failed to generate budget report')
    } finally {
      setDownloadingReport(null)
    }
  }

  // Resolve the final category_name (use custom if "Other" selected)
  const resolvedCategoryName = () => {
    if (lineForm.category_name === 'Other (Custom)') return lineForm.custom_name.trim()
    return lineForm.category_name
  }

  const handleCategoryChange = (value: string) => {
    // Auto-suggest a GL account when the category changes — but only if the
    // user hasn't manually picked one for this line yet. Always editable,
    // never forced: this just pre-fills the select.
    const next: LineForm = { ...lineForm, category_name: value, custom_name: '' }
    if (!accountTouched) {
      const suggestion = suggestAccount(value, accounts)
      next.account = suggestion?.id ?? ''
    }
    setLineForm(next)
  }

  const handleAddLine = async () => {
    if (!addLineBudgetId) return
    const catName = resolvedCategoryName()
    if (!catName) { toast.error('Enter or select a category'); return }
    if (!lineForm.budgeted_amount) { toast.error('Enter a budgeted amount'); return }
    setSavingLine(true)
    try {
      await budgetApi.addLine(addLineBudgetId, {
        category_name: catName,
        category_type: lineForm.category_type,
        sub_category: lineForm.sub_category,
        period_month: lineForm.period_month ? parseInt(lineForm.period_month) : null,
        budgeted_amount: parseFloat(stripCommas(lineForm.budgeted_amount)),
        ...(lineForm.forecast_amount ? { forecast_amount: parseFloat(stripCommas(lineForm.forecast_amount)) } : {}),
        ...(lineForm.unit_price ? { unit_price: parseFloat(stripCommas(lineForm.unit_price)) } : {}),
        quantity: parseFloat(lineForm.quantity) || 1,
        description: lineForm.description,
        ...(lineForm.account ? { account: lineForm.account } : {}),
      })
      toast.success('Budget line added')
      setAddLineBudgetId(null)
      setLineForm(BLANK_LINE)
      setAccountTouched(false)
      // add_line's URL has a UUID mid-path (/budgets/{id}/add_line/, not a
      // trailing one), so the axios write-through cache's invalidation
      // heuristic can't match it — same gap already documented and worked
      // around for bulk_lines/approve elsewhere in this file.
      bypassNextGets()
      load()
    } catch { toast.error('Failed to add budget line') }
    finally { setSavingLine(false) }
  }

  const categoryOptions = lineForm.category_type === 'revenue' ? INCOME_CATEGORIES : EXPENSE_CATEGORIES

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white">Budgets</h1>
          <p className="text-slate-400 text-sm">{budgets.length} budgets</p>
        </div>
        <div className="flex items-center gap-2 sm:ml-auto">
          <button onClick={() => { bypassNextGets(); load() }} disabled={loading} className="btn-ghost p-2 text-slate-400 hover:text-white" title="Refresh">
            <RefreshCw size={16} className={loading ? 'animate-spin' : ''} />
          </button>
          <div className="flex items-center rounded-lg border border-surface-700 overflow-hidden">
            <button
              onClick={() => setViewMode('list')}
              title="List view"
              className={`p-2 transition-colors ${viewMode === 'list' ? 'bg-brand-500/20 text-brand-400' : 'text-slate-500 hover:text-white'}`}
            >
              <LayoutList size={16} />
            </button>
            <button
              onClick={() => setViewMode('grid')}
              title="Grid view"
              className={`p-2 transition-colors ${viewMode === 'grid' ? 'bg-brand-500/20 text-brand-400' : 'text-slate-500 hover:text-white'}`}
            >
              <LayoutGrid size={16} />
            </button>
          </div>
          <Link to="/budgets/monitoring" className="btn-ghost inline-flex items-center gap-2 text-sm">
            <BarChart3 size={16} /> Monitoring
          </Link>
          <button className="btn-primary" onClick={() => setShowBudgetModal(true)}>
            <Plus size={16} /> New Budget
          </button>
        </div>
      </div>

      {/* What is variance? help card */}
      <div className="bg-blue-500/10 border border-blue-500/20 rounded-xl px-4 py-3">
        <button
          onClick={() => setShowVarianceHelp(!showVarianceHelp)}
          className="flex items-center gap-2 text-blue-400 text-sm font-medium w-full text-left"
        >
          <HelpCircle size={16} />
          What is a Budget Line and what does Variance mean?
          {showVarianceHelp ? <ChevronUp size={14} className="ml-auto" /> : <ChevronDown size={14} className="ml-auto" />}
        </button>
        {showVarianceHelp && (
          <div className="mt-3 space-y-2 text-sm text-slate-300">
            <p><strong className="text-white">Budget Line:</strong> A single planned spending (or income) target for a specific category. For example: "₦500,000 for Salaries in January". Think of it like a spending promise you make to yourself for your business.</p>
            <p><strong className="text-white">Variance:</strong> The difference between what you planned to spend and what you actually spent. A <span className="text-emerald-400">green/positive variance</span> means you spent less than planned (good!). A <span className="text-red-400">red/negative variance</span> means you exceeded your budget (over budget — needs attention).</p>
            <p><strong className="text-white">Actual Amount:</strong> You do <em>not</em> enter actual amounts manually. They are automatically pulled from your recorded expenses and income in the <strong>Expenses &amp; Income</strong> section that match the budget line's category (or that you explicitly link to this budget). Record your real transactions there, then open <Link to="/budgets/monitoring" className="text-brand-400 hover:underline">Monitoring</Link> to see how you're tracking.</p>
          </div>
        )}
      </div>

      {/* Budget list */}
      {loading ? (
        <div className="space-y-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="card p-5 animate-pulse">
              <div className="h-5 bg-surface-700 rounded w-48 mb-2" />
              <div className="h-3 bg-surface-700 rounded w-32" />
            </div>
          ))}
        </div>
      ) : budgets.length === 0 ? (
        <div className="card p-12 text-center">
          <PieChart size={36} className="mx-auto mb-3 text-slate-600" />
          <p className="text-slate-400 font-medium">No budgets yet</p>
          <p className="text-slate-500 text-sm mt-1 mb-4">Create your first budget to plan and track your business spending</p>
          <button onClick={() => setShowBudgetModal(true)} className="btn-primary mt-2 inline-flex items-center gap-2 text-sm">
            <Plus size={14} /> Create First Budget
          </button>
        </div>
      ) : viewMode === 'grid' ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {budgets.map((b) => (
            <button
              key={b.id}
              onClick={() => { setViewMode('list'); setExpandedBudget(b.id) }}
              className="card p-5 text-left hover:border-surface-500 transition-colors"
            >
              <div className="flex items-start justify-between gap-2 mb-2">
                <p className="text-white font-semibold leading-tight">{b.name}</p>
                <span className={STATUS_BADGE[b.status] ?? 'badge-slate'}>{b.status}</span>
              </div>
              <div className="flex items-center gap-2 flex-wrap mb-3">
                <span className={`${TYPE_BADGE[b.budget_type] ?? 'badge-slate'} inline-flex items-center gap-1`}>
                  {b.budget_type === 'capital' ? <Landmark size={11} /> : <Briefcase size={11} />}
                  {b.budget_type === 'capital' ? 'Capital' : 'Operational'}
                </span>
                <span className="text-slate-500 text-xs">{b.fiscal_year} · {b.period_type}</span>
              </div>
              <p className="text-2xl font-mono text-white mb-1">{formatCurrency(sumBudgetedAmount(b.lines))}</p>
              <p className="text-slate-500 text-xs mb-2">{b.lines.length} line{b.lines.length !== 1 ? 's' : ''} budgeted</p>
              {b.approved_by ? (
                <p className="text-emerald-400/80 text-xs flex items-center gap-1">
                  <ShieldCheck size={11} /> Approved by {b.approved_by_name || 'a manager'}
                </p>
              ) : (
                <p className="text-slate-600 text-xs">Not yet approved</p>
              )}
            </button>
          ))}
        </div>
      ) : (
        <div className="space-y-4">
          {budgets.map((b) => (
            <div key={b.id} className="card overflow-hidden">
              <div className="p-5 flex items-center justify-between flex-wrap gap-3">
                <div className="flex items-center gap-4">
                  <button onClick={() => setExpandedBudget(expandedBudget === b.id ? null : b.id)} className="text-slate-400 hover:text-white">
                    {expandedBudget === b.id ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
                  </button>
                  <div>
                    <div className="flex items-center gap-2 flex-wrap">
                      <p className="text-white font-semibold">{b.name}</p>
                      <span className={`${TYPE_BADGE[b.budget_type] ?? 'badge-slate'} inline-flex items-center gap-1`}>
                        {b.budget_type === 'capital' ? <Landmark size={11} /> : <Briefcase size={11} />}
                        {b.budget_type === 'capital' ? 'Capital' : 'Operational'}
                      </span>
                    </div>
                    <p className="text-slate-500 text-xs">{b.fiscal_year} · {b.period_type} · {b.lines.length} line{b.lines.length !== 1 ? 's' : ''}</p>
                    {b.approved_by && (
                      <p className="text-emerald-400/80 text-xs mt-0.5 flex items-center gap-1">
                        <ShieldCheck size={11} /> Approved by {b.approved_by_name || 'a manager'}
                      </p>
                    )}
                  </div>
                </div>
                <div className="flex items-center gap-2 flex-wrap">
                  <span className={STATUS_BADGE[b.status] ?? 'badge-slate'}>{b.status}</span>
                  <button onClick={() => { setAddLineBudgetId(b.id); setLineForm(BLANK_LINE); setAccountTouched(false) }} className="text-xs px-2.5 py-1 rounded-lg bg-brand-500/15 text-brand-400 hover:bg-brand-500/25 transition-colors">
                    + Line
                  </button>
                  <button
                    onClick={() => setGridEditorBudget(b)}
                    className="text-xs px-2.5 py-1 rounded-lg bg-surface-700 text-slate-300 hover:bg-surface-600 transition-colors inline-flex items-center gap-1"
                    title="Build/edit this budget's lines in a 12-month grid"
                  >
                    <Grid3x3 size={11} /> Monthly Grid
                  </button>
                  <button
                    onClick={() => handleDownloadReport(b, 'pdf')}
                    disabled={downloadingReport === b.id}
                    className="text-xs px-2.5 py-1 rounded-lg bg-surface-700 text-slate-300 hover:bg-surface-600 transition-colors inline-flex items-center gap-1 disabled:opacity-50"
                    title="Download this budget's variance report as a PDF"
                  >
                    {downloadingReport === b.id ? <Loader2 size={11} className="animate-spin" /> : <Download size={11} />} Report (PDF)
                  </button>
                  <button
                    onClick={() => handleDownloadReport(b, 'csv')}
                    disabled={downloadingReport === b.id}
                    className="text-xs px-2.5 py-1 rounded-lg bg-surface-700 text-slate-300 hover:bg-surface-600 transition-colors inline-flex items-center gap-1 disabled:opacity-50"
                    title="Download this budget's variance report as a CSV"
                  >
                    <Download size={11} /> CSV
                  </button>
                  {!b.approved_by && b.status !== 'closed' && isManagerOrAbove(memberRole, user?.is_superuser) && (
                    <button
                      onClick={() => handleApprove(b)}
                      disabled={approvingBudget === b.id}
                      className="text-xs px-2.5 py-1 rounded-lg bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500/20 transition-colors flex items-center gap-1 disabled:opacity-50"
                    >
                      {approvingBudget === b.id ? <Loader2 size={11} className="animate-spin" /> : <ShieldCheck size={11} />}
                      Approve
                    </button>
                  )}
                  <button
                    onClick={() => handleActivate(b)}
                    disabled={activatingBudget === b.id}
                    className={`text-xs px-2.5 py-1 rounded-lg transition-colors flex items-center gap-1 disabled:opacity-50 ${b.status === 'active' ? 'bg-red-500/10 text-red-400 hover:bg-red-500/20' : 'bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500/20'}`}
                  >
                    {activatingBudget === b.id ? <Loader2 size={11} className="animate-spin" /> : null}
                    {b.status === 'active' ? 'Close' : b.status === 'draft' ? 'Activate' : 'Reopen'}
                  </button>
                </div>
              </div>

              {expandedBudget === b.id && (
                <div className="border-t border-surface-700">
                  {(() => {
                    // Phase 6 (B7): a simple two-bucket roll-up — every
                    // revenue line vs every expense line (COGS lumped in
                    // with expense here, unlike the grid editor's 5-row P&L
                    // breakdown; this is deliberately the lighter summary).
                    const totalIncome = sumBudgetedAmount(b.lines.filter((l) => l.category_type === 'revenue'))
                    const totalExpense = sumBudgetedAmount(b.lines.filter((l) => l.category_type === 'expense'))
                    const expectedProfit = totalIncome - totalExpense
                    const taxRate = parseFloat(taxRateDraft[b.id] ?? String(b.tax_rate ?? 0)) || 0
                    const tax = expectedProfit * (taxRate / 100)
                    const budgetAmount = expectedProfit - tax
                    return (
                      <div className="p-4 bg-surface-800/30 border-b border-surface-700">
                        <div className="grid grid-cols-2 sm:grid-cols-5 gap-4">
                          <div>
                            <p className="text-xs text-slate-500">Total Income (A)</p>
                            <p className="font-mono text-sm text-white">{formatCurrency(totalIncome)}</p>
                          </div>
                          <div>
                            <p className="text-xs text-slate-500">Total Expense (B)</p>
                            <p className="font-mono text-sm text-white">{formatCurrency(totalExpense)}</p>
                          </div>
                          <div>
                            <p className="text-xs text-slate-500">Expected Profit (C = A−B)</p>
                            <p className={`font-mono text-sm ${expectedProfit < 0 ? 'text-red-400' : 'text-emerald-400'}`}>{formatCurrency(expectedProfit)}</p>
                          </div>
                          <div>
                            <p className="text-xs text-slate-500 mb-1">Tax (D = C × rate)</p>
                            <div className="flex items-center gap-1">
                              <input
                                type="text"
                                inputMode="decimal"
                                className="input py-1 text-xs w-16"
                                value={taxRateDraft[b.id] ?? String(b.tax_rate ?? 0)}
                                onChange={(e) => setTaxRateDraft((prev) => ({ ...prev, [b.id]: e.target.value }))}
                              />
                              <span className="text-xs text-slate-500">%</span>
                              <button
                                onClick={() => handleSaveTaxRate(b)}
                                disabled={savingTaxRate === b.id}
                                className="text-xs px-1.5 py-1 rounded bg-brand-500/15 text-brand-400 hover:bg-brand-500/25 disabled:opacity-50"
                              >
                                {savingTaxRate === b.id ? <Loader2 size={11} className="animate-spin" /> : 'Save'}
                              </button>
                            </div>
                            <p className="font-mono text-xs text-slate-400 mt-1">{formatCurrency(tax)}</p>
                          </div>
                          <div>
                            <p className="text-xs text-slate-500">Budget Amount (E = C−D)</p>
                            <p className="font-mono text-sm text-white font-semibold">{formatCurrency(budgetAmount)}</p>
                          </div>
                        </div>
                      </div>
                    )
                  })()}
                  {b.lines.length === 0 ? (
                    <div className="p-6 text-center text-slate-500 text-sm">
                      No budget lines yet.{' '}
                      <button onClick={() => { setAddLineBudgetId(b.id); setLineForm(BLANK_LINE); setAccountTouched(false) }} className="text-brand-400 hover:underline">Add a line</button>
                    </div>
                  ) : (() => {
                    const activeFilter = lineTypeFilter[b.id] ?? 'all'
                    const filteredLines = b.lines.filter((l) => activeFilter === 'all' || l.category_type === activeFilter)
                    return (
                    <>
                      <div className="flex items-center gap-1 px-4 pt-3">
                        {(['all', 'revenue', 'expense'] as const).map((f) => (
                          <button
                            key={f}
                            onClick={() => setLineTypeFilter((prev) => ({ ...prev, [b.id]: f }))}
                            className={`text-xs px-2.5 py-1 rounded-lg transition-colors ${activeFilter === f ? 'bg-brand-500/20 text-brand-400' : 'text-slate-500 hover:text-slate-300'}`}
                          >
                            {f === 'all' ? 'All' : f === 'revenue' ? 'Revenue' : 'Expense'}
                          </button>
                        ))}
                      </div>
                      <table className="w-full text-sm">
                        <thead>
                          <tr className="border-b border-surface-700 bg-surface-800/50">
                            {['Category', 'Sub-Category', 'Account', 'Type', 'Month', 'Budgeted', 'Forecast', ''].map((h) => (
                              <th key={h} className="px-4 py-2.5 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider">{h}</th>
                            ))}
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-surface-700">
                          {filteredLines.map((line) => (
                            <tr key={line.id} className="table-row">
                              <td className="px-4 py-3 text-slate-300">{line.category_name || 'Uncategorized'}</td>
                              <td className="px-4 py-3 text-slate-500">{line.sub_category || '—'}</td>
                              <td className="px-4 py-3 text-slate-500">
                                {line.account_name ? `${line.account_code ? line.account_code + ' · ' : ''}${line.account_name}` : '—'}
                              </td>
                              <td className="px-4 py-3"><span className={line.category_type === 'revenue' ? 'badge-green' : 'badge-red'}>{line.category_type}</span></td>
                              <td className="px-4 py-3 text-slate-400">{line.period_month ? MONTH_NAMES[line.period_month - 1] : 'All'}</td>
                              <td className="px-4 py-3 font-mono text-white">{formatCurrency(line.budgeted_amount)}</td>
                              <td className="px-4 py-3 font-mono text-slate-400">{line.forecast_amount ? formatCurrency(line.forecast_amount) : '—'}</td>
                              <td className="px-4 py-3">
                                {line.attachment ? (
                                  <a href={line.attachment} target="_blank" rel="noreferrer" className="text-brand-400 hover:underline text-xs inline-flex items-center gap-1">
                                    <FileText size={12} /> View
                                  </a>
                                ) : (
                                  <label className="text-slate-500 hover:text-white cursor-pointer inline-flex items-center gap-1" title="Attach a supporting document">
                                    {uploadingAttachment === line.id ? <Loader2 size={13} className="animate-spin" /> : <Upload size={13} />}
                                    <input
                                      type="file"
                                      className="hidden"
                                      disabled={uploadingAttachment === line.id}
                                      onChange={(e) => { const f = e.target.files?.[0]; if (f) handleUploadAttachment(line.id, f) }}
                                    />
                                  </label>
                                )}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </>
                    )
                  })()}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* New Budget Modal */}
      {showBudgetModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={() => setShowBudgetModal(false)} />
          <div className="relative card w-full max-w-md p-6 space-y-5 max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-bold text-white">New Budget</h2>
              <button onClick={() => setShowBudgetModal(false)} className="text-slate-400 hover:text-white"><X size={20} /></button>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="col-span-2">
                <label className="text-xs text-slate-400 mb-1 block">Budget Name *</label>
                <input className="input" placeholder="e.g. 2026 Operating Budget" value={budgetForm.name} onChange={(e) => setBudgetForm({ ...budgetForm, name: e.target.value })} />
              </div>
              <div className="col-span-2">
                <label className="text-xs text-slate-400 mb-1 block">Budget Type</label>
                <div className="grid grid-cols-2 gap-2">
                  {[
                    { v: 'operational', label: 'Operational', icon: Briefcase, hint: 'Day-to-day running costs' },
                    { v: 'capital', label: 'Capital', icon: Landmark, hint: 'Equipment, property, big purchases' },
                  ].map(({ v, label, icon: Icon, hint }) => (
                    <button
                      key={v} type="button"
                      onClick={() => setBudgetForm({ ...budgetForm, budget_type: v })}
                      className={`p-3 rounded-xl border text-left transition-all ${budgetForm.budget_type === v ? 'bg-brand-500/15 border-brand-500' : 'border-surface-600 hover:border-surface-500'}`}
                    >
                      <span className={`flex items-center gap-1.5 text-sm font-medium ${budgetForm.budget_type === v ? 'text-white' : 'text-slate-300'}`}>
                        <Icon size={14} /> {label}
                      </span>
                      <span className="text-xs text-slate-500 block mt-0.5">{hint}</span>
                    </button>
                  ))}
                </div>
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Fiscal Year *</label>
                <input
                  type="number"
                  className="input"
                  min={MIN_YEAR}
                  max={MAX_YEAR}
                  value={budgetForm.fiscal_year}
                  onChange={(e) => setBudgetForm({ ...budgetForm, fiscal_year: e.target.value })}
                />
                <p className="text-xs text-slate-600 mt-1">{MIN_YEAR}–{MAX_YEAR}. Prior years are allowed so you can load a historic budget for comparison.</p>
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Period Type</label>
                <select className="input" value={budgetForm.period_type} onChange={(e) => setBudgetForm({ ...budgetForm, period_type: e.target.value })}>
                  <option value="daily">Daily</option>
                  <option value="weekly">Weekly</option>
                  <option value="monthly">Monthly</option>
                  <option value="quarterly">Quarterly</option>
                  <option value="annual">Annual</option>
                </select>
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Start Date <span className="text-slate-600 font-normal">(optional)</span></label>
                <DateInput value={budgetForm.start_date} onChange={(v) => setBudgetForm({ ...budgetForm, start_date: v })} />
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">End Date <span className="text-slate-600 font-normal">(optional)</span></label>
                <DateInput value={budgetForm.end_date} onChange={(v) => setBudgetForm({ ...budgetForm, end_date: v })} min={budgetForm.start_date || undefined} />
              </div>
              <div className="col-span-2">
                <label className="text-xs text-slate-400 mb-1 block">Notes</label>
                <textarea className="input resize-none" rows={2} value={budgetForm.notes} onChange={(e) => setBudgetForm({ ...budgetForm, notes: e.target.value })} />
              </div>
            </div>
            <div className="flex gap-3">
              <button className="flex-1 py-2.5 rounded-xl border border-surface-600 text-slate-400 hover:text-white hover:border-surface-500 transition-colors text-sm" onClick={() => setShowBudgetModal(false)}>Cancel</button>
              <button className="btn-primary flex-1 py-2.5 justify-center disabled:opacity-50" onClick={handleCreateBudget} disabled={savingBudget}>
                {savingBudget ? <Loader2 size={16} className="animate-spin" /> : 'Create Budget'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Add Budget Line Modal */}
      {addLineBudgetId && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={() => setAddLineBudgetId(null)} />
          <div className="relative card w-full max-w-md p-6 space-y-5 max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-bold text-white">Add Budget Line</h2>
              <button onClick={() => setAddLineBudgetId(null)} className="text-slate-400 hover:text-white"><X size={20} /></button>
            </div>
            <p className="text-xs text-slate-500 -mt-2">A budget line is one planned spending or income target for a specific category.</p>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Type *</label>
                <select className="input" value={lineForm.category_type} onChange={(e) => { setLineForm({ ...lineForm, category_type: e.target.value, category_name: '' }); setAccountTouched(false) }}>
                  <option value="expense">Expense (Money Out)</option>
                  <option value="revenue">Revenue (Money In)</option>
                </select>
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Month (leave blank for full year)</label>
                <select className="input" value={lineForm.period_month} onChange={(e) => setLineForm({ ...lineForm, period_month: e.target.value })}>
                  <option value="">All Periods / Full Year</option>
                  {MONTH_NAMES.map((m, i) => <option key={i} value={String(i + 1)}>{m}</option>)}
                </select>
              </div>
              <div className="col-span-2">
                <label className="text-xs text-slate-400 mb-1 block">Category *</label>
                <select
                  className="input"
                  value={lineForm.category_name}
                  onChange={(e) => handleCategoryChange(e.target.value)}
                >
                  <option value="">— Select a category —</option>
                  {categoryOptions.map((c) => <option key={c} value={c}>{c}</option>)}
                </select>
              </div>
              {lineForm.category_name === 'Other (Custom)' && (
                <div className="col-span-2">
                  <label className="text-xs text-slate-400 mb-1 block">Custom Category Name *</label>
                  <input
                    className="input"
                    placeholder="e.g. Vehicle Maintenance, Packaging Materials…"
                    value={lineForm.custom_name}
                    onChange={(e) => setLineForm({ ...lineForm, custom_name: e.target.value })}
                  />
                </div>
              )}
              <div className="col-span-2">
                <label className="text-xs text-slate-400 mb-1 block">Sub-Category <span className="text-slate-600 font-normal">(optional — a finer split within {lineForm.category_type})</span></label>
                <input
                  className="input"
                  placeholder="e.g. Online Sales, Fuel…"
                  value={lineForm.sub_category}
                  onChange={(e) => setLineForm({ ...lineForm, sub_category: e.target.value })}
                />
              </div>
              <div className="col-span-2">
                <label className="text-xs text-slate-400 mb-1 block">
                  GL Account <span className="text-slate-600 font-normal">(optional — links this line to your Chart of Accounts)</span>
                </label>
                <select
                  className="input"
                  value={lineForm.account}
                  onChange={(e) => { setLineForm({ ...lineForm, account: e.target.value }); setAccountTouched(true) }}
                >
                  <option value="">— No account link —</option>
                  {accounts.map((a) => (
                    <option key={a.id} value={a.id}>{a.code} · {a.name}</option>
                  ))}
                </select>
                {lineForm.account && !accountTouched && (
                  <p className="text-xs text-slate-500 mt-1">Suggested based on the category — change it if this isn't right.</p>
                )}
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Unit Price</label>
                <AmountInput
                  className="input"
                  placeholder="e.g. 5,000"
                  value={lineForm.unit_price}
                  onChange={(up) => {
                    const qty = parseFloat(lineForm.quantity) || 1
                    const total = parseFloat(stripCommas(up)) * qty
                    setLineForm({ ...lineForm, unit_price: up, budgeted_amount: total > 0 ? formatAmountInput(String(total)) : lineForm.budgeted_amount })
                  }}
                />
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Quantity</label>
                <input
                  type="number"
                  min="1"
                  className="input"
                  placeholder="1"
                  value={lineForm.quantity}
                  onChange={(e) => {
                    const qty = parseFloat(e.target.value) || 1
                    const up = parseFloat(stripCommas(lineForm.unit_price)) || 0
                    const total = up * qty
                    setLineForm({ ...lineForm, quantity: e.target.value, budgeted_amount: total > 0 ? formatAmountInput(String(total)) : lineForm.budgeted_amount })
                  }}
                />
              </div>
              <div className="col-span-2">
                <label className="text-xs text-slate-400 mb-1 block">Budgeted Amount *</label>
                <AmountInput
                  className="input"
                  placeholder="e.g. 500,000"
                  value={lineForm.budgeted_amount}
                  onChange={(v) => setLineForm({ ...lineForm, budgeted_amount: v })}
                />
                {lineForm.unit_price && lineForm.quantity && (
                  <p className="text-xs text-slate-500 mt-1">
                    {formatAmountInput(lineForm.unit_price)} × {lineForm.quantity} = calculated above
                  </p>
                )}
              </div>
              <div className="col-span-2">
                <label className="text-xs text-slate-400 mb-1 block">Forecast Amount <span className="text-slate-600 font-normal">(optional — a forward-looking estimate, separate from the committed budget)</span></label>
                <AmountInput
                  className="input"
                  placeholder="e.g. 550,000"
                  value={lineForm.forecast_amount}
                  onChange={(v) => setLineForm({ ...lineForm, forecast_amount: v })}
                />
              </div>
              <div className="col-span-2">
                <label className="text-xs text-slate-400 mb-1 block">Description <span className="text-slate-600 font-normal">(optional)</span></label>
                <input
                  className="input"
                  placeholder="Brief note about this budget line"
                  value={lineForm.description}
                  onChange={(e) => setLineForm({ ...lineForm, description: e.target.value })}
                />
              </div>
            </div>
            <div className="flex gap-3">
              <button className="flex-1 py-2.5 rounded-xl border border-surface-600 text-slate-400 hover:text-white hover:border-surface-500 transition-colors text-sm" onClick={() => setAddLineBudgetId(null)}>Cancel</button>
              <button className="btn-primary flex-1 py-2.5 justify-center disabled:opacity-50" onClick={handleAddLine} disabled={savingLine}>
                {savingLine ? <Loader2 size={16} className="animate-spin" /> : 'Add Line'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Monthly Grid Editor — alternative bulk entry mode alongside the
          single-line Add Budget Line modal above, which is untouched. */}
      {gridEditorBudget && (
        <BudgetGridEditor
          budget={gridEditorBudget}
          accounts={accounts}
          onClose={() => setGridEditorBudget(null)}
          onSaved={() => {
            // bulk_lines' URL has a UUID mid-path (/budgets/{id}/bulk_lines/,
            // not a trailing one), so the axios write-through cache's
            // invalidation heuristic (buildListUrl, keyed on a TRAILING
            // UUID) can't match it and falls back to invalidating
            // /budgets/{id}/ instead of the actual /budgets/ list — the same
            // gap already documented for other action-suffixed endpoints in
            // services/api.ts. bypassNextGets() sidesteps it the same way
            // the header's manual Refresh button already does, so the list
            // reflects the save immediately instead of up to 5 minutes stale.
            setGridEditorBudget(null)
            bypassNextGets()
            load()
          }}
        />
      )}
    </div>
  )
}

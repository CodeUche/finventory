import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

const m = vi.hoisted(() => ({
  catalog: vi.fn(), run: vi.fn(), pnl: vi.fn(), arAging: vi.fn(), apAging: vi.fn(), cashFlow: vi.fn(), vatSummary: vi.fn(),
}))

vi.mock('@/services/api', () => ({
  bypassNextGets: vi.fn(),
  reportApi: {
    catalog: m.catalog, run: m.run, download: vi.fn(), pnl: m.pnl, arAging: m.arAging, apAging: m.apAging,
    cashFlow: m.cashFlow, vatSummary: m.vatSummary,
  },
}))
vi.mock('react-hot-toast', () => ({ default: { error: vi.fn(), success: vi.fn() } }))
vi.mock('@/hooks/useDataRefresh', () => ({ useDataRefresh: () => {} }))
vi.mock('@/components/PeriodSelector', () => ({ default: () => <div data-testid="period-bar" /> }))

import AllReportsPage from '@/pages/reports/AllReportsPage'
import { useAuthStore } from '@/store/authStore'

const entry = (key: string, label = key) => ({ key, label, category: 'x', description: '', needs_period: true })
const PNL = {
  revenue: { gross_sales: '1200000.00', tax_collected: '0', discounts: '0' },
  cost_of_goods_sold: '700000.00', gross_profit: '500000.00', gross_margin_pct: '41.67',
  operating_expenses: '290000.00', miscellaneous_income: '0', net_profit: '210000.00', net_margin_pct: '17.50',
}

function setUser(role: string, perms: Record<string, string>) {
  useAuthStore.setState({
    memberRole: role, modulePermissions: perms as never, planModules: null, user: { is_superuser: false } as never,
  })
}
const renderAt = (url: string) =>
  render(<MemoryRouter initialEntries={[url]}><AllReportsPage /></MemoryRouter>)

describe('Reports home', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    m.run.mockResolvedValue({ data: { data: { rows: [] }, label: 'x', period_label: '' } })
    m.pnl.mockResolvedValue({ data: PNL })
    m.arAging.mockResolvedValue({ data: { total_outstanding: '640000.00' } })
    m.apAging.mockResolvedValue({ data: { total_outstanding: '310000.00' } })
    m.cashFlow.mockResolvedValue({ data: { net_cash_flow: '95000.00' } })
    m.vatSummary.mockResolvedValue({ data: { net_vat_payable: '45000.00' } })
  })

  it('the owner sees a tile per question, the business summary and real figures from the existing endpoints', async () => {
    setUser('owner', {})
    m.catalog.mockResolvedValue({ data: { reports: ['profit-loss', 'cash-flow', 'vat-return', 'balance-sheet'].map((k) => entry(k)) } })
    renderAt('/reports/all')
    expect(await screen.findByTestId('group-tile-how')).toBeTruthy()
    expect(screen.getByTestId('group-tile-books')).toBeTruthy()
    expect(screen.getByTestId('group-tile-owe')).toBeTruthy()   // Aged Receivables is a screen target
    await waitFor(() => expect(screen.getByTestId('business-summary')).toBeTruthy())
    expect(screen.getByTestId('business-summary').textContent).toContain('210,000.00')
    expect(screen.getByTestId('group-tile-how').textContent).toContain('210,000.00')
    expect(screen.getByTestId('group-tile-cash').textContent).toContain('95,000.00')
    expect(screen.getByTestId('group-tile-tax').textContent).toContain('45,000.00')
    expect(screen.getByTestId('quick-links').textContent).toContain('Balance Sheet')
    expect(screen.getByTestId('period-bar')).toBeTruthy()
  })

  it('a Reports-only member gets no summary, no gated figures and no gated requests', async () => {
    setUser('staff', { reports: 'view' })
    m.catalog.mockResolvedValue({ data: { reports: [entry('sales-by-customer'), entry('cash-flow')] } })
    renderAt('/reports/all')
    expect(await screen.findByTestId('group-tile-how')).toBeTruthy()
    await waitFor(() => expect(m.cashFlow).toHaveBeenCalled())
    expect(screen.queryByTestId('business-summary')).toBeNull()
    expect(screen.queryByTestId('group-tile-books')).toBeNull()
    expect(screen.queryByTestId('group-tile-people')).toBeNull()
    expect(screen.queryByTestId('group-tile-tax')).toBeNull()
    expect(m.pnl).not.toHaveBeenCalled()
    expect(m.arAging).not.toHaveBeenCalled()
    expect(m.apAging).not.toHaveBeenCalled()
    expect(m.vatSummary).not.toHaveBeenCalled()
    // the only figure shown is the one this member may read, and no tile shows an empty figure
    expect(screen.getByTestId('group-tile-cash').textContent).toContain('95,000.00')
    expect(screen.getByTestId('group-tile-how').textContent).not.toMatch(/₦/)
  })

  it('drops a figure whose request fails instead of showing a blank', async () => {
    setUser('owner', {})
    m.catalog.mockResolvedValue({ data: { reports: [entry('cash-flow')] } })
    m.pnl.mockRejectedValue(new Error('nope'))
    renderAt('/reports/all')
    await screen.findByTestId('group-tile-how')
    await waitFor(() => expect(m.pnl).toHaveBeenCalled())
    expect(screen.queryByTestId('business-summary')).toBeNull()
    expect(screen.getByTestId('group-tile-how').textContent).not.toMatch(/₦/)
  })

  it('a member with nothing to read sees the plain permission note, not an empty page of tiles', async () => {
    setUser('staff', {})
    m.catalog.mockResolvedValue({ data: { reports: [] } })
    renderAt('/reports/all')
    expect(await screen.findByTestId('report-no-access')).toHaveTextContent('Some reports need extra permission. Ask an owner or admin.')
  })

  it('?group= opens that question\'s list, with the main link and the "also" links', async () => {
    setUser('owner', {})
    m.catalog.mockResolvedValue({ data: { reports: [entry('balance-sheet'), entry('trial-balance'), entry('gl-detail')] } })
    renderAt('/reports/all?group=books')
    const bs = await screen.findByTestId('report-entry-balance-sheet')
    expect(bs.querySelector('a.rp-entry-main')?.getAttribute('href')).toBe('/reports/balance-sheet')
    expect(bs.textContent).toContain('Table view')
    expect(screen.getByTestId('report-entry-general-ledger').textContent).toContain('Transaction report')
  })

  it('the old ?report= link still runs that report', async () => {
    setUser('owner', {})
    m.catalog.mockResolvedValue({ data: { reports: [entry('trial-balance', 'Trial Balance')] } })
    renderAt('/reports/all?report=trial-balance')
    await waitFor(() => expect(m.run).toHaveBeenCalledWith('trial-balance', expect.anything()))
    expect(screen.queryByTestId('group-tile-books')).toBeNull()
  })

  it('the old gl-tax-summary link opens Tax Summary instead of the permission note', async () => {
    setUser('owner', {})
    m.catalog.mockResolvedValue({ data: { reports: [entry('tax-summary', 'Tax Summary Report')] } })
    renderAt('/reports/all?report=gl-tax-summary')
    await waitFor(() => expect(m.run).toHaveBeenCalledWith('tax-summary', expect.anything()))
    expect(screen.queryByTestId('report-no-access')).toBeNull()
  })
})

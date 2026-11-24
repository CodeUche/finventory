import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

const { catalogMock, runMock, toastError } = vi.hoisted(() => ({
  catalogMock: vi.fn(),
  runMock: vi.fn(),
  toastError: vi.fn(),
}))

vi.mock('@/services/api', () => ({
  bypassNextGets: vi.fn(),
  reportApi: { catalog: catalogMock, run: runMock, download: vi.fn() },
}))
vi.mock('react-hot-toast', () => ({
  default: { error: toastError, success: vi.fn() },
}))
vi.mock('@/hooks/useDataRefresh', () => ({ useDataRefresh: () => {} }))
vi.mock('@/components/PeriodSelector', () => ({ default: () => null }))

import AllReportsPage from '@/pages/reports/AllReportsPage'

const entry = (key: string, category: string) => ({
  key, label: key, category, description: '', needs_period: true,
})

function renderAt(report: string) {
  return render(
    <MemoryRouter initialEntries={[`/reports/all?report=${report}`]}>
      <AllReportsPage />
    </MemoryRouter>,
  )
}

describe('AllReportsPage deep link to a report the person cannot run', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    catalogMock.mockResolvedValue({
      data: { reports: [entry('profit-loss', 'Financial Statements')] },
    })
    runMock.mockResolvedValue({ data: { data: { rows: [] }, label: 'x', period_label: '' } })
  })

  it('shows a plain message, does not call the report and shows no error toast', async () => {
    renderAt('employee-list')
    expect(await screen.findByTestId('report-no-access')).toHaveTextContent(
      'Some reports need extra permission. Ask an owner or admin.',
    )
    expect(runMock).not.toHaveBeenCalled()
    expect(toastError).not.toHaveBeenCalled()
  })

  it('still runs a report that is in the catalog', async () => {
    renderAt('profit-loss')
    await waitFor(() => expect(runMock).toHaveBeenCalledTimes(1))
    expect(screen.queryByTestId('report-no-access')).toBeNull()
  })

  it('hides groups that have no allowed reports', async () => {
    renderAt('profit-loss')
    await screen.findAllByText('profit-loss')
    expect(screen.queryByText('People and payroll')).toBeNull()
  })
})

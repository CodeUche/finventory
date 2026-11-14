import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

vi.mock('@/services/api', () => ({
  taxApi: {
    vatComparison: vi.fn().mockResolvedValue({
      data: {
        rows: [{
          period_start: '2025-11-01', period_end: '2025-11-30',
          reports_page_showed: '0', tax_page_showed: '0', now: '-750',
          difference_from_reports_page: '-750', difference_from_tax_page: '-750',
          different: true, why: ['Credit notes are deducted in the month they are issued.'],
        }],
      },
    }),
  },
}))

import VatChangeNotice from '@/components/VatChangeNotice'

describe('VatChangeNotice', () => {
  it('explains the change, shows the comparison and never says owe or overpaid', async () => {
    const { container } = render(<VatChangeNotice />)
    await waitFor(() => expect(screen.getByText('VAT figures have changed')).toBeTruthy())
    fireEvent.click(screen.getByText(/Show the comparison/))
    expect(screen.getByText('Reports page showed')).toBeTruthy()
    expect(screen.getByText(/Credit notes are deducted/)).toBeTruthy()
    expect(screen.getByText(/do not change anything yourself/)).toBeTruthy()
    const text = container.textContent ?? ''
    expect(/you owe|overpaid/i.test(text)).toBe(false)
  })
})

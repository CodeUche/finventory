import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import YearFilter, { yearToDateParams } from '@/components/YearFilter'

describe('yearToDateParams', () => {
  it('returns empty object for null (current year)', () => {
    expect(yearToDateParams(null)).toEqual({})
  })

  it('returns correct date range for a given year', () => {
    expect(yearToDateParams(2025)).toEqual({
      date_from: '2025-01-01',
      date_to: '2025-12-31',
    })
  })
})

describe('YearFilter component', () => {
  it('renders Current label when no year is selected', () => {
    render(<YearFilter selectedYear={null} onChange={() => {}} />)
    expect(screen.getByRole('button')).toHaveTextContent('Current')
  })

  it('renders archive label when a year is selected', () => {
    render(<YearFilter selectedYear={2024} onChange={() => {}} />)
    expect(screen.getByRole('button')).toHaveTextContent('2024 Archive')
  })

  it('opens dropdown on click', () => {
    const currentYear = new Date().getFullYear()
    render(<YearFilter selectedYear={null} onChange={() => {}} yearsBack={3} />)
    fireEvent.click(screen.getByRole('button'))
    expect(screen.getByText(`Current (${currentYear})`)).toBeInTheDocument()
  })

  it('calls onChange with null when Current is clicked', () => {
    const onChange = vi.fn()
    render(<YearFilter selectedYear={2024} onChange={onChange} yearsBack={3} />)
    fireEvent.click(screen.getByRole('button')) // open
    const currentYear = new Date().getFullYear()
    fireEvent.click(screen.getByText(`Current (${currentYear})`))
    expect(onChange).toHaveBeenCalledWith(null)
  })

  it('calls onChange with year when archive year is clicked', () => {
    const onChange = vi.fn()
    const currentYear = new Date().getFullYear()
    render(<YearFilter selectedYear={null} onChange={onChange} yearsBack={3} />)
    fireEvent.click(screen.getByRole('button')) // open
    fireEvent.click(screen.getByText(`${currentYear - 1} Archive`))
    expect(onChange).toHaveBeenCalledWith(currentYear - 1)
  })
})

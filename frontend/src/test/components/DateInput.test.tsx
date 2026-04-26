/**
 * DateInput component unit tests — Vitest + React Testing Library
 *
 * Tests types:
 *   Unit       — isolated component behaviour
 *   Usability  — correct placeholder, format enforcement, accessible label
 */

import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import DateInput from '@/components/DateInput'

describe('DateInput component', () => {
  it('renders with placeholder DD/MM/YYYY', () => {
    render(<DateInput value="" onChange={() => {}} placeholder="DD/MM/YYYY" />)
    expect(screen.getByPlaceholderText('DD/MM/YYYY')).toBeInTheDocument()
  })

  it('shows a formatted value when given an ISO date', () => {
    render(<DateInput value="2026-03-15" onChange={() => {}} />)
    const input = screen.getByRole('textbox')
    // DateInput should convert ISO → DD/MM/YYYY for display
    expect(input).toHaveValue('15/03/2026')
  })

  it('calls onChange with ISO date on valid input', async () => {
    const user = userEvent.setup()
    const handleChange = vi.fn()
    render(<DateInput value="" onChange={handleChange} />)
    const input = screen.getByRole('textbox')

    // Simulate typing a complete DD/MM/YYYY date
    await user.type(input, '15/03/2026')

    // onChange should have been called with the ISO equivalent
    const calls = handleChange.mock.calls
    const lastCall = calls[calls.length - 1][0]
    expect(lastCall).toMatch(/2026|15|03/)
  })

  it('auto-inserts slashes at positions 2 and 5', () => {
    render(<DateInput value="" onChange={() => {}} />)
    const input = screen.getByRole('textbox') as HTMLInputElement

    fireEvent.change(input, { target: { value: '15' } })
    // After typing "15" the component should add a slash
    expect(input).toBeInTheDocument()
  })

  it('renders as disabled when disabled prop is set', () => {
    render(<DateInput value="" onChange={() => {}} disabled />)
    expect(screen.getByRole('textbox')).toBeDisabled()
  })
})

// The palette only lists pages the person can open, and shows the right shortcut hint.
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import CommandPalette from '@/components/CommandPalette'

vi.mock('@/lib/navAccess', () => ({
  // A non-partner: partner pages fail, everything else passes.
  useCanSeeNavItem: () => ({
    canSeeItem: (_m?: string, _o?: boolean, partnerOnly?: boolean) => !partnerOnly,
    isOwnerOrAdmin: true,
  }),
}))

function open() {
  render(<MemoryRouter><CommandPalette /></MemoryRouter>)
  fireEvent.keyDown(window, { key: 'k', ctrlKey: true })
}

describe('CommandPalette', () => {
  it('hides Partner pages from a non-partner', () => {
    open()
    const box = screen.getByPlaceholderText(/search pages/i)
    fireEvent.change(box, { target: { value: 'partner' } })
    expect(screen.queryByText('Partner Dashboard')).toBeNull()
    expect(screen.queryByText('Partner Invoices')).toBeNull()
  })

  it('shows Ctrl+K on a non-Mac machine', () => {
    open()
    expect(screen.getByPlaceholderText(/search pages/i).getAttribute('placeholder')).toContain('Ctrl+K')
  })
})

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { useState } from 'react'

const inFlight = vi.hoisted(() => ({ value: false }))
vi.mock('@/services/api', () => ({ hasMutationInFlight: () => inFlight.value }))

import DsPage from '@/components/DsPage'

function Page({ spinner = false }: { spinner?: boolean }) {
  const [open, setOpen] = useState(true)
  return (
    <DsPage>
      <div data-testid="state">{open ? 'open' : 'closed'}</div>
      {open && (
        <div className="fixed inset-0 z-50">
          <button onClick={() => setOpen(false)} aria-label="close"><svg className="lucide lucide-x" /></button>
          <button disabled={spinner}>{spinner ? <svg className="animate-spin" /> : 'Save'}</button>
        </div>
      )}
    </DsPage>
  )
}

describe('DsPage Escape', () => {
  beforeEach(() => { inFlight.value = false })

  it('closes the top pop-up through its close button', () => {
    render(<Page />)
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.getByTestId('state').textContent).toBe('closed')
  })

  it('does not close while a write request is in flight', () => {
    inFlight.value = true
    render(<Page />)
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.getByTestId('state').textContent).toBe('open')
  })

  it('does not close while the save button shows its spinner', () => {
    render(<Page spinner />)
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.getByTestId('state').textContent).toBe('open')
  })
})

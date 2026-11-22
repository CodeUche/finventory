import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { act, useState } from 'react'
import { createRoot, type Root } from 'react-dom/client'

const inFlight = vi.hoisted(() => ({ value: false }))
vi.mock('@/services/api', () => ({
  hasMutationInFlight: () => inFlight.value,
  isAppOffline: () => false,
  subscribeConnectivity: () => () => undefined,
}))

import DsPage from '@/components/DsPage'

// React needs this flag to treat act() as a test environment.
;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

function Page({ spinner = false }: { spinner?: boolean }) {
  const [open, setOpen] = useState(true)
  return (
    <DsPage>
      <div id="state">{open ? 'open' : 'closed'}</div>
      {open && (
        <div className="fixed inset-0 z-50">
          <button onClick={() => setOpen(false)}><svg className="lucide lucide-x" /></button>
          <button disabled={spinner}>{spinner ? <svg className="animate-spin" /> : 'Save'}</button>
        </div>
      )}
    </DsPage>
  )
}

describe('DsPage Escape', () => {
  let host: HTMLDivElement
  let root: Root
  const mount = (spinner = false) => { act(() => { root.render(<Page spinner={spinner} />) }) }
  const pressEscape = () => { act(() => { document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })) }) }
  const state = () => host.querySelector('#state')?.textContent

  beforeEach(() => {
    inFlight.value = false
    host = document.createElement('div')
    document.body.appendChild(host)
    root = createRoot(host)
  })
  afterEach(() => { act(() => root.unmount()); host.remove() })

  it('closes the top pop-up through its close button', () => {
    mount(); pressEscape()
    expect(state()).toBe('closed')
  })

  it('does not close while a write request is in flight', () => {
    inFlight.value = true
    mount(); pressEscape()
    expect(state()).toBe('open')
  })

  it('does not close while the save button shows its spinner', () => {
    mount(true); pressEscape()
    expect(state()).toBe('open')
  })
})

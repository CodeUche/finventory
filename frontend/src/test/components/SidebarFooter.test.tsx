import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'
import SidebarFooter, { FOOTER_KEY } from '@/components/layout/SidebarFooter'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

let host: HTMLDivElement
let root: Root

function show(props: { isSuperuser: boolean; rail?: boolean; onSignOut?: () => void }) {
  act(() => {
    root.render(
      <MemoryRouter>
        <SidebarFooter isSuperuser={props.isSuperuser} rail={props.rail ?? false} onSignOut={props.onSignOut ?? (() => {})} />
      </MemoryRouter>,
    )
  })
}
const q = (sel: string) => host.querySelector<HTMLElement>(sel)

beforeEach(() => {
  localStorage.clear()
  host = document.createElement('div')
  document.body.appendChild(host)
  root = createRoot(host)
})
afterEach(() => {
  act(() => root.unmount())
  host.remove()
  vi.restoreAllMocks()
})

describe('SidebarFooter', () => {
  it('starts expanded with text rows named Platform Admin and Sign Out', () => {
    show({ isSuperuser: true })
    expect(host.textContent).toContain('Platform Admin')
    expect(host.textContent).toContain('Sign Out')
    expect(q('[data-foot]')?.dataset.foot).toBe('full')
  })

  it('shows Platform Admin only for superusers', () => {
    show({ isSuperuser: false })
    expect(host.textContent).not.toContain('Platform Admin')
    expect(q('a[href="/platform-admin"]')).toBeNull()
    expect(host.textContent).toContain('Sign Out')
    show({ isSuperuser: true })
    expect(q('a[href="/platform-admin"]')).not.toBeNull()
  })

  it('collapses to icon-only buttons with accessible names, and expands again', () => {
    show({ isSuperuser: true })
    act(() => { q('.sh-foot-handle')!.click() })
    expect(q('[data-foot]')?.dataset.foot).toBe('icons')
    expect(host.textContent).not.toContain('Sign Out')
    expect(q('[aria-label="Platform admin"]')).not.toBeNull()
    expect(q('[aria-label="Sign out"]')?.getAttribute('title')).toBe('Sign out')
    expect(q('.sh-foot-handle')?.getAttribute('aria-expanded')).toBe('false')
    act(() => { q('.sh-foot-handle')!.click() })
    expect(q('[data-foot]')?.dataset.foot).toBe('full')
    expect(host.textContent).toContain('Sign Out')
  })

  it('remembers the choice on this device', () => {
    show({ isSuperuser: false })
    act(() => { q('.sh-foot-handle')!.click() })
    expect(localStorage.getItem(FOOTER_KEY)).toBe('0')
    act(() => root.unmount())
    root = createRoot(host)
    show({ isSuperuser: false })
    expect(q('[data-foot]')?.dataset.foot).toBe('icons')
  })

  it('still works when storage is blocked', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('blocked') })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('blocked') })
    show({ isSuperuser: false })
    expect(q('[data-foot]')?.dataset.foot).toBe('full')
    act(() => { q('.sh-foot-handle')!.click() })
    expect(q('[data-foot]')?.dataset.foot).toBe('icons')
  })

  it('is icon-only with no handle when the whole sidebar is folded', () => {
    show({ isSuperuser: true, rail: true })
    expect(q('[data-foot]')?.dataset.foot).toBe('icons')
    expect(q('.sh-foot-handle')).toBeNull()
    expect(q('[aria-label="Sign out"]')).not.toBeNull()
  })

  it('signs out when the button is pressed', () => {
    const out = vi.fn()
    show({ isSuperuser: false, onSignOut: out })
    act(() => { q('.sh-foot-danger')!.click() })
    expect(out).toHaveBeenCalledTimes(1)
  })
})

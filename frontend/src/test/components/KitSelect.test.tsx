import { describe, it, expect, vi, afterEach } from 'vitest'
import { act, useState } from 'react'
import { createRoot, type Root } from 'react-dom/client'

vi.mock('@/services/api', () => ({ hasMutationInFlight: () => false }))

import {
  SelectEnhancer, findTypeahead, stepEnabled, readOptions, commitSelectValue, SEARCH_THRESHOLD,
  type KitOption,
} from '@/components/KitSelect'
import { handleEscape, _resetEscapeLayers } from '@/lib/escapeStack'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const opt = (label: string, disabled = false): KitOption => ({ value: label.toLowerCase(), label, disabled })

describe('KitSelect helpers', () => {
  it('type-ahead jumps to the next label with that start, wrapping round', () => {
    const o = [opt('Apple'), opt('Avocado'), opt('Banana')]
    expect(findTypeahead(o, 'a', 0)).toBe(1)
    expect(findTypeahead(o, 'a', 1)).toBe(0)
    expect(findTypeahead(o, 'ban', 0)).toBe(2)
    expect(findTypeahead(o, 'z', 0)).toBe(-1)
  })

  it('arrow steps skip disabled items and stay inside the list', () => {
    const o = [opt('A'), opt('B', true), opt('C')]
    expect(stepEnabled(o, 0, 1)).toBe(2)
    expect(stepEnabled(o, 2, 1)).toBe(2)
    expect(stepEnabled(o, 2, -1)).toBe(0)
    expect(stepEnabled(o, 0, -1)).toBe(0)
  })
})

describe('SelectEnhancer', () => {
  let host: HTMLDivElement
  let root: Root

  function Harness({ count = 3, onChange }: { count?: number; onChange: (v: string) => void }) {
    const [v, setV] = useState('v0')
    return (
      <div>
        <select
          data-testid="s"
          className="input"
          value={v}
          onChange={(e) => { setV(e.target.value); onChange(e.target.value) }}
        >
          {Array.from({ length: count }, (_, i) => (
            <option key={i} value={`v${i}`} disabled={i === 1 && count === 3}>{`Item ${i}`}</option>
          ))}
        </select>
        <span id="out">{v}</span>
      </div>
    )
  }

  function mount(count: number, onChange: (v: string) => void) {
    host = document.createElement('div')
    document.body.appendChild(host)
    root = createRoot(host)
    act(() => { root.render(<><Harness count={count} onChange={onChange} /><SelectEnhancer /></>) })
  }
  afterEach(() => { act(() => root.unmount()); host.remove(); _resetEscapeLayers() })

  const select = () => host.querySelector('select') as HTMLSelectElement
  const panel = () => document.querySelector('[data-kit-select-panel]') as HTMLElement | null
  const out = () => host.querySelector('#out')?.textContent
  const press = (key: string, target: Element = document.activeElement ?? document.body) => {
    act(() => { target.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true })) })
  }
  const clickSelect = () => {
    act(() => {
      select().dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true, button: 0 }))
    })
  }

  it('opens the kit list instead of the browser list, and picking fires one normal change', () => {
    const seen: string[] = []
    mount(3, (v) => seen.push(v))
    clickSelect()
    expect(panel()).not.toBeNull()
    const items = Array.from(document.querySelectorAll('[role="option"]'))
    expect(items.map((i) => i.textContent)).toEqual(['Item 0', 'Item 1', 'Item 2'])
    expect(items[1].getAttribute('aria-disabled')).toBe('true')
    act(() => { (items[1] as HTMLElement).click() }) // disabled: ignored
    expect(seen).toEqual([])
    act(() => { (items[2] as HTMLElement).click() })
    expect(seen).toEqual(['v2'])
    expect(out()).toBe('v2')
    expect(select().value).toBe('v2')
    expect(panel()).toBeNull()
  })

  it('keyboard: Enter opens, arrows move over disabled items, Enter picks', () => {
    const seen: string[] = []
    mount(3, (v) => seen.push(v))
    select().focus()
    press('Enter', select())
    expect(panel()).not.toBeNull()
    const p = panel() as HTMLElement
    const list = p.querySelector('[role="listbox"]') as HTMLElement
    press('ArrowDown', list) // skips the disabled item 1
    press('Enter', list)
    expect(seen).toEqual(['v2'])
  })

  it('typing letters jumps to a matching item (type-ahead)', () => {
    const seen: string[] = []
    mount(3, (v) => seen.push(v))
    clickSelect()
    const list = (panel() as HTMLElement).querySelector('[role="listbox"]') as HTMLElement
    press('I', list); press('t', list); press('e', list); press('m', list); press(' ', list)
    press('2', list)
    press('Enter', list)
    expect(seen).toEqual(['v2'])
  })

  it('a long list gets a search box that filters', () => {
    const seen: string[] = []
    mount(SEARCH_THRESHOLD + 5, (v) => seen.push(v))
    clickSelect()
    const input = (panel() as HTMLElement).querySelector('input') as HTMLInputElement
    expect(input).not.toBeNull()
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!
    act(() => { setter.call(input, 'Item 12'); input.dispatchEvent(new Event('input', { bubbles: true })) })
    const items = Array.from(document.querySelectorAll('[role="option"]'))
    expect(items.map((i) => i.textContent)).toEqual(['Item 12'])
    press('Enter', input)
    expect(seen).toEqual(['v12'])
  })

  it('Escape closes only the list, and a second Escape is then free for the pop-up', () => {
    mount(3, () => undefined)
    clickSelect()
    expect(panel()).not.toBeNull()
    act(() => { expect(handleEscape()).toBe(true) })
    expect(panel()).toBeNull()
    expect(handleEscape()).toBe(false)
  })

  it('a click outside closes the list without changing the value', () => {
    const seen: string[] = []
    mount(3, (v) => seen.push(v))
    clickSelect()
    act(() => { document.body.dispatchEvent(new MouseEvent('mousedown', { bubbles: true })) })
    expect(panel()).toBeNull()
    expect(seen).toEqual([])
    expect(out()).toBe('v0')
  })

  it('reads option groups and commits only real changes', () => {
    mount(3, () => undefined)
    expect(readOptions(select()).map((o) => o.label)).toEqual(['Item 0', 'Item 1', 'Item 2'])
    const fn = vi.fn()
    select().addEventListener('change', fn)
    commitSelectValue(select(), 'v0') // same value: nothing fires
    expect(fn).not.toHaveBeenCalled()
  })
})

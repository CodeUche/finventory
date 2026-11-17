/**
 * Kit dropdown list.
 *
 * The browser's own <select> list cannot be styled: it shows the operating system's look,
 * and in dark mode it can open white-on-white. This file replaces only the OPEN LIST.
 * The closed control stays a real <select> (so forms, labels, values and onChange handlers
 * are untouched), drawn in the kit look by ds.css.
 *
 *  - <SelectEnhancer/> is mounted once. It catches a click / Enter / Space / arrow key on any
 *    <select>, stops the browser list, and shows the kit list under it instead.
 *  - Choosing an item sets the select's value the way the browser does and fires the same
 *    `input` and `change` events, so the page's `value` / `onChange(e)` code runs unchanged.
 *  - <Select/> is a drop-in for a plain <select> (same props, same events).
 *
 * Touch phones keep the native list (it is a good, readable full-screen picker there).
 */
import {
  forwardRef, useCallback, useEffect, useId, useLayoutEffect, useMemo, useRef, useState,
  type SelectHTMLAttributes,
} from 'react'
import { createPortal } from 'react-dom'
import { Check, Search } from 'lucide-react'
import { useEscapeLayer } from '@/lib/escapeStack'

export interface KitOption {
  value: string
  label: string
  disabled: boolean
  group?: string
}

/** Searchable once the list is longer than this many items. */
export const SEARCH_THRESHOLD = 10

/** Reads the options of a real <select> (including option groups). */
export function readOptions(select: HTMLSelectElement): KitOption[] {
  const out: KitOption[] = []
  Array.from(select.querySelectorAll('option')).forEach((o) => {
    const grp = o.parentElement instanceof HTMLOptGroupElement ? o.parentElement : null
    out.push({
      value: o.value,
      label: (o.textContent ?? '').trim() || o.value,
      disabled: o.disabled || !!grp?.disabled,
      group: grp?.label || undefined,
    })
  })
  return out
}

/** Sets a select's value exactly like a user pick would, firing input + change once. */
export function commitSelectValue(select: HTMLSelectElement, value: string): void {
  if (select.value === value) return
  // React tracks the value on the element itself; go through the native setter so its
  // change detection sees a real change.
  const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value')?.set
  if (setter) setter.call(select, value)
  else select.value = value
  select.dispatchEvent(new Event('input', { bubbles: true }))
  select.dispatchEvent(new Event('change', { bubbles: true }))
}

/** Index of the next option (after `from`) whose label starts with `text`; wraps. -1 if none. */
export function findTypeahead(options: KitOption[], text: string, from: number): number {
  const t = text.toLowerCase()
  if (!t) return -1
  const n = options.length
  // A single letter cycles through items; a longer word searches from the current one.
  const start = t.length === 1 ? from + 1 : Math.max(from, 0)
  for (let k = 0; k < n; k++) {
    const i = (start + k) % n
    if (!options[i].disabled && options[i].label.toLowerCase().startsWith(t)) return i
  }
  return -1
}

/** Next enabled index in a direction, staying inside the list. */
export function stepEnabled(options: KitOption[], from: number, dir: 1 | -1): number {
  let i = from
  for (let k = 0; k < options.length; k++) {
    i += dir
    if (i < 0 || i >= options.length) return from
    if (!options[i].disabled) return i
  }
  return from
}

interface ListProps {
  options: KitOption[]
  value: string
  anchor: HTMLElement
  onPick: (value: string) => void
  onClose: () => void
}

/** The open list: opaque kit panel, keyboard accessible, searchable when long. */
export function KitListbox({ options, value, anchor, onPick, onClose }: ListProps) {
  const searchable = options.length > SEARCH_THRESHOLD
  const [query, setQuery] = useState('')
  const [rect, setRect] = useState(() => anchor.getBoundingClientRect())
  const listId = useId()
  const panelRef = useRef<HTMLDivElement>(null)
  const typed = useRef({ text: '', at: 0 })

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase()
    return q ? options.filter((o) => o.label.toLowerCase().includes(q)) : options
  }, [options, query])

  const [active, setActive] = useState(() => {
    const i = options.findIndex((o) => o.value === value && !o.disabled)
    return i >= 0 ? i : options.findIndex((o) => !o.disabled)
  })
  // When the filter changes, point at the first match.
  useEffect(() => {
    if (!query) return
    setActive(shown.findIndex((o) => !o.disabled))
  }, [query, shown])

  useEscapeLayer(true, onClose)

  // Keep the list glued to its control (page scroll, window resize, modal scroll).
  useLayoutEffect(() => {
    const update = () => setRect(anchor.getBoundingClientRect())
    update()
    window.addEventListener('resize', update)
    window.addEventListener('scroll', update, true)
    return () => { window.removeEventListener('resize', update); window.removeEventListener('scroll', update, true) }
  }, [anchor])

  // Close on a click outside.
  useEffect(() => {
    const down = (e: MouseEvent) => {
      const t = e.target as Node
      if (panelRef.current?.contains(t) || anchor.contains(t)) return
      onClose()
    }
    document.addEventListener('mousedown', down, true)
    return () => document.removeEventListener('mousedown', down, true)
  }, [anchor, onClose])

  // Focus: the search box when there is one, otherwise the list itself.
  useEffect(() => {
    const el = panelRef.current?.querySelector<HTMLElement>(searchable ? 'input' : '[role="listbox"]')
    el?.focus({ preventScroll: true })
  }, [searchable])

  // Keep the active row in view.
  useEffect(() => {
    panelRef.current?.querySelector<HTMLElement>('[data-active="true"]')?.scrollIntoView?.({ block: 'nearest' })
  }, [active, shown])

  const below = window.innerHeight - rect.bottom
  const above = rect.top
  const openUp = below < 220 && above > below
  const maxHeight = Math.max(160, Math.min(320, (openUp ? above : below) - 12))
  const width = Math.max(rect.width, 176)
  const left = Math.min(Math.max(8, rect.left), Math.max(8, window.innerWidth - width - 8))
  const style: React.CSSProperties = {
    left, width, maxHeight,
    ...(openUp ? { bottom: window.innerHeight - rect.top + 4 } : { top: rect.bottom + 4 }),
  }

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); setActive((a) => stepEnabled(shown, a, 1)) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setActive((a) => stepEnabled(shown, a, -1)) }
    else if (e.key === 'Home') { e.preventDefault(); setActive(shown.findIndex((o) => !o.disabled)) }
    else if (e.key === 'End') {
      e.preventDefault()
      for (let i = shown.length - 1; i >= 0; i--) if (!shown[i].disabled) { setActive(i); break }
    }
    else if (e.key === 'Enter' || (e.key === ' ' && !searchable)) {
      e.preventDefault()
      const o = shown[active]
      if (o && !o.disabled) onPick(o.value)
    }
    else if (e.key === 'Tab') onClose()
    else if (!searchable && e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
      // Type-ahead: letters typed within a second build one word.
      const now = Date.now()
      const text = now - typed.current.at > 1000 ? e.key : typed.current.text + e.key
      typed.current = { text, at: now }
      const i = findTypeahead(shown, text, active)
      if (i >= 0) setActive(i)
    }
  }

  let lastGroup: string | undefined
  return createPortal(
    <div
      ref={panelRef}
      className="kit-select-panel"
      style={style}
      onKeyDown={onKeyDown}
      data-kit-select-panel=""
    >
      {searchable && (
        <div className="kit-select-search">
          <Search size={14} aria-hidden />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search"
            aria-label="Search the list"
            aria-controls={listId}
            autoComplete="off"
          />
        </div>
      )}
      <div
        id={listId}
        role="listbox"
        tabIndex={searchable ? -1 : 0}
        aria-activedescendant={shown[active] ? `${listId}-${active}` : undefined}
        className="kit-select-list"
      >
        {shown.length === 0 && <div className="kit-select-empty">No matches</div>}
        {shown.map((o, i) => {
          const header = o.group && o.group !== lastGroup ? o.group : null
          lastGroup = o.group
          return (
            <div key={`${o.value}-${i}`}>
              {header && <div className="kit-select-group">{header}</div>}
              <div
                id={`${listId}-${i}`}
                role="option"
                aria-selected={o.value === value}
                aria-disabled={o.disabled || undefined}
                data-active={i === active}
                className="kit-select-option"
                onMouseMove={() => { if (!o.disabled && i !== active) setActive(i) }}
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => { if (!o.disabled) onPick(o.value) }}
              >
                <span className="kit-select-option-label">{o.label || ' '}</span>
                {o.value === value && <Check size={14} aria-hidden />}
              </div>
            </div>
          )
        })}
      </div>
    </div>,
    document.body,
  )
}

/** Phones and tablets keep the native picker. */
function usesNativePicker(): boolean {
  return typeof window.matchMedia === 'function' && window.matchMedia('(pointer: coarse)').matches
}

function enhanceable(t: EventTarget | null): HTMLSelectElement | null {
  if (!(t instanceof HTMLSelectElement)) return null
  if (t.disabled || t.multiple || t.size > 1 || t.dataset.nativeSelect !== undefined) return null
  return t
}

/** Mount once near the app root. */
export function SelectEnhancer() {
  const [target, setTarget] = useState<HTMLSelectElement | null>(null)

  const close = useCallback(() => {
    setTarget((t) => { t?.focus({ preventScroll: true }); return null })
  }, [])

  useEffect(() => {
    const onMouseDown = (e: MouseEvent) => {
      const sel = enhanceable(e.target)
      if (!sel || e.button !== 0 || usesNativePicker()) return
      e.preventDefault() // stops the browser list from opening
      sel.focus({ preventScroll: true })
      setTarget((cur) => (cur === sel ? null : sel))
    }
    const onKeyDown = (e: KeyboardEvent) => {
      const sel = enhanceable(e.target)
      if (!sel || usesNativePicker()) return
      const opens =
        e.key === 'Enter' || e.key === ' ' || e.key === 'F4' ||
        (e.altKey && (e.key === 'ArrowDown' || e.key === 'ArrowUp'))
      if (!opens) return
      e.preventDefault()
      setTarget(sel)
    }
    document.addEventListener('mousedown', onMouseDown, true)
    document.addEventListener('keydown', onKeyDown, true)
    return () => {
      document.removeEventListener('mousedown', onMouseDown, true)
      document.removeEventListener('keydown', onKeyDown, true)
    }
  }, [])

  // If the control disappears (page change, pop-up closed) while open, drop the list.
  useEffect(() => {
    if (!target) return
    const t = window.setInterval(() => { if (!target.isConnected) setTarget(null) }, 400)
    return () => window.clearInterval(t)
  }, [target])

  if (!target) return null
  return (
    <KitListbox
      options={readOptions(target)}
      value={target.value}
      anchor={target}
      onClose={close}
      onPick={(v) => {
        commitSelectValue(target, v)
        setTarget(null)
        target.focus({ preventScroll: true })
      }}
    />
  )
}

/**
 * Drop-in for a plain <select>. Same props, same value / onChange(e) behaviour; the kit list
 * comes from <SelectEnhancer/>. Use it in new code so the intent is visible in the page.
 */
export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(
  function Select({ className = '', ...rest }, ref) {
    return <select ref={ref} className={`input ${className}`.trim()} {...rest} />
  },
)

export default Select

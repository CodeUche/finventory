/**
 * One Escape key handler for the whole app.
 *
 * Two kinds of layers can be open:
 *  1. Registered layers: components that call useEscapeLayer (the dropdown list, the confirm
 *     dialog, the chat panel, the search palette). The newest registered layer closes first.
 *  2. Pop-ups and drawers that only exist as markup (a `fixed inset-0` cover). We find the
 *     top-most one on screen and press its own close control, so the page's own close logic
 *     (clearing a form, asking about unsaved changes) runs exactly as when the user clicks it.
 *
 * Only ONE layer closes per key press. Nothing closes while a save is running.
 */
import { useEffect, useLayoutEffect, useRef } from 'react'
import { hasMutationInFlight } from '@/services/api'

interface Layer { id: number; close: () => void }
const layers: Layer[] = []
let nextId = 1

/** Register a layer; the returned function removes it. The newest layer closes first. */
export function registerEscapeLayer(close: () => void): () => void {
  const layer: Layer = { id: nextId++, close }
  layers.push(layer)
  return () => {
    const i = layers.indexOf(layer)
    if (i >= 0) layers.splice(i, 1)
  }
}

/** While `active` is true, Escape calls `close` (when this is the top-most layer). */
export function useEscapeLayer(active: boolean, close: () => void): void {
  const ref = useRef(close)
  // Written after each render (not during it) so the layer always calls the newest `close`.
  useLayoutEffect(() => { ref.current = close })
  useEffect(() => {
    if (!active) return
    return registerEscapeLayer(() => ref.current())
  }, [active])
}

const OVERLAY_SELECTOR = '.fixed.inset-0, [data-drawer="open"], [data-escape-layer]'

function isShown(el: HTMLElement): boolean {
  const cs = window.getComputedStyle(el)
  return cs.display !== 'none' && cs.visibility !== 'hidden'
}

function zOf(el: HTMLElement): number {
  const z = parseInt(window.getComputedStyle(el).zIndex, 10)
  return Number.isNaN(z) ? 0 : z
}

/** Top-most visible pop-up / drawer cover, or null. */
export function findTopOverlay(doc: Document = document): HTMLElement | null {
  const all = Array.from(doc.querySelectorAll<HTMLElement>(OVERLAY_SELECTOR)).filter((el) => {
    if (el.closest('[data-no-escape]')) return false
    // A cover that lets clicks through, or the phone menu backdrop, is not a pop-up.
    if (el.classList.contains('pointer-events-none') || el.classList.contains('lg:hidden')) return false
    return isShown(el)
  })
  let best: HTMLElement | null = null
  let bestZ = -Infinity
  for (const el of all) {
    const z = zOf(el)
    if (z >= bestZ) { best = el; bestZ = z } // later in the page wins a tie
  }
  // Something opened INSIDE the top cover (a dropdown's click-catcher in a pop-up) is above it,
  // whatever its z-index says.
  while (best) {
    const inner: HTMLElement[] = all.filter((el) => el !== best && best!.contains(el))
    if (!inner.length) break
    best = inner[inner.length - 1]
  }
  return best
}

/** True for a cover with real content (a pop-up), false for an empty click-catcher. */
export function hasContent(el: HTMLElement): boolean {
  return el.childElementCount > 0 || (el.textContent ?? '').trim().length > 0
}

const CLOSE_TEXT = /^(cancel|close|dismiss)$/i

/** The control that closes this pop-up, or null when the cover is not meant to be closed. */
export function findCloser(overlay: HTMLElement): HTMLElement | null {
  const explicit = overlay.querySelector<HTMLElement>('[data-escape-close]:not(:disabled)')
  if (explicit) return explicit
  const buttons = Array.from(overlay.querySelectorAll<HTMLButtonElement>('button:not(:disabled)'))

  // The panel is the biggest child that is not the dim backdrop.
  const panels = Array.from(overlay.children).filter(
    (c): c is HTMLElement => c instanceof HTMLElement && !c.classList.contains('absolute'),
  )
  const area = (e: HTMLElement) => { const r = e.getBoundingClientRect(); return r.width * r.height }
  const panel = panels.sort((a, b) => area(b) - area(a))[0] ?? overlay
  const panelTop = panel.getBoundingClientRect().top

  // An X counts as "the close button" only when it sits in the header, so a row's own
  // remove-X further down is never pressed by mistake.
  const xs = buttons
    .filter((b) => b.querySelector('svg.lucide-x') && !(b.textContent ?? '').trim())
    .filter((b) => b.getBoundingClientRect().top - panelTop <= 90)
    .sort((a, b) => a.getBoundingClientRect().top - b.getBoundingClientRect().top)
  if (xs[0]) return xs[0]

  const labelled = buttons.find((b) => /^close\b/i.test(b.getAttribute('aria-label') ?? ''))
  if (labelled) return labelled
  const texty = buttons.find((b) => CLOSE_TEXT.test((b.textContent ?? '').trim()))
  if (texty) return texty
  const backdrop = overlay.querySelector<HTMLElement>(':scope > .absolute.inset-0')
  if (backdrop) return backdrop
  // An empty cover is a click-catcher behind an open dropdown: clicking it closes the dropdown.
  if (!hasContent(overlay)) return overlay
  return null
}

/**
 * Handles one Escape key press. Returns true when something was closed.
 * Exported so it can be tested without a real keyboard.
 */
export function handleEscape(doc: Document = document): boolean {
  const top = layers[layers.length - 1]
  if (top) { top.close(); return true }

  // A save is running (a write request not yet answered): never close under it.
  if (hasMutationInFlight()) return false
  const overlay = findTopOverlay(doc)
  if (!overlay) return false
  if (overlay.querySelector('button:disabled .animate-spin')) return false
  const closer = findCloser(overlay)
  if (!closer) return false
  closer.click()
  return true
}

let installs = 0
let listener: ((e: KeyboardEvent) => void) | null = null

/** Starts the one document-level listener (safe to call many times; counted). */
export function installGlobalEscape(): () => void {
  installs += 1
  if (!listener) {
    listener = (e: KeyboardEvent) => {
      if (e.key !== 'Escape' || e.defaultPrevented) return
      if (handleEscape()) e.preventDefault()
    }
    document.addEventListener('keydown', listener)
  }
  return () => {
    installs -= 1
    if (installs <= 0 && listener) {
      document.removeEventListener('keydown', listener)
      listener = null
      installs = 0
    }
  }
}

/** For tests: forget every registered layer. */
export function _resetEscapeLayers(): void { layers.length = 0 }

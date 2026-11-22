/**
 * Keeps toast messages and the support bubble clear of what is on screen.
 *
 * One watcher publishes, on <html> / <body>:
 *  - --toast-left / --toast-right : the free strip of the screen for toasts. Toasts sit at the
 *    bottom, centred in the page area (beside the sidebar), and step aside for an open
 *    slide-over (data-drawer="open") and for the register's basket on the right.
 *  - --toast-bottom : normally 20px; raised above the support bubble on narrow screens and on
 *    the register, so a toast never covers the bubble.
 *  - body[data-popup-open] : set while a pop-up or slide-over is open. Toasts then move to the
 *    top of the screen (above the pop-up, which keeps a free band there) and the support
 *    bubble hides, so neither covers a pop-up's header or buttons.
 */
import { findTopOverlay, hasContent } from '@/lib/escapeStack'
import { tagAllPopups } from '@/lib/popupEnhance'

let started = false
const listeners = new Set<(open: boolean) => void>()
let popupOpen = false

export function isPopupOpen(): boolean { return popupOpen }

/** Calls back when a pop-up opens or closes. Returns an unsubscribe function. */
export function subscribePopupOpen(fn: (open: boolean) => void): () => void {
  listeners.add(fn)
  return () => { listeners.delete(fn) }
}

function panelWidth(el: HTMLElement): number {
  // Full-screen wrappers (inset-0 + justify-end) hold the real panel as the last child.
  const panel = el.classList.contains('inset-0') ? (el.lastElementChild as HTMLElement | null) ?? el : el
  return Math.round(panel.getBoundingClientRect().width)
}

export function startDrawerToastOffset(): void {
  if (started || typeof document === 'undefined') return
  started = true
  const root = document.documentElement

  const apply = () => {
    const vw = window.innerWidth
    const wide = vw >= 1024

    // A slide-over takes the right edge; toasts stay clear of it.
    const drawers = Array.from(document.querySelectorAll<HTMLElement>('[data-drawer="open"]'))
    let right = 16
    if (drawers.length) {
      const width = Math.max(...drawers.map(panelWidth))
      // On a phone the panel is the whole screen: nothing to dodge.
      right = width >= vw - 40 ? 16 : width + 16
    }

    // Centre the toast in the page area, not under the sidebar.
    const main = document.querySelector('main')
    const left = wide && main ? Math.max(16, Math.round(main.getBoundingClientRect().left) + 16) : 16

    // The register keeps its basket (and tender buttons) on the right, and the support bubble
    // sits beside it: toasts stay in the product area and ride above the bubble row.
    const onRegister = window.location.pathname === '/pos/register'
    if (onRegister && wide) right = Math.max(right, 392)
    const raise = onRegister || !wide

    root.style.setProperty('--toast-left', `${left}px`)
    root.style.setProperty('--toast-right', `${right}px`)
    root.style.setProperty('--toast-bottom', raise ? '76px' : '20px')

    tagAllPopups(document)
    // An empty click-catcher behind a dropdown is not a pop-up: toasts and the chat bubble stay.
    const top = findTopOverlay(document)
    const open = !!top && (hasContent(top) || !!top.closest('.fixed.inset-0:not(:empty)'))
    if (open !== popupOpen) {
      popupOpen = open
      if (open) document.body.setAttribute('data-popup-open', '')
      else document.body.removeAttribute('data-popup-open')
      listeners.forEach((fn) => fn(open))
    }
  }

  let queued = false
  const schedule = () => {
    if (queued) return
    queued = true
    requestAnimationFrame(() => { queued = false; apply() })
  }

  const resizeObserver = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(schedule) : null
  const watch = () => {
    resizeObserver?.disconnect()
    document.querySelectorAll<HTMLElement>('[data-drawer="open"]').forEach((d) => resizeObserver?.observe(d))
    const main = document.querySelector('main')
    if (main) resizeObserver?.observe(main)
    schedule()
  }
  new MutationObserver(watch).observe(document.body, { childList: true, subtree: true })
  window.addEventListener('resize', schedule)
  window.addEventListener('popstate', schedule)
  watch()
}

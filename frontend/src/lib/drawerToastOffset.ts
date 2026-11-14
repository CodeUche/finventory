/**
 * Keeps toast messages clear of an open slide-over (invoice detail, account drawer,
 * offboarding). Each drawer carries data-drawer="open"; we measure the real panel and
 * publish its width as --toast-right on <html>, and remove it when the drawer closes.
 */
let started = false

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
    const drawers = Array.from(document.querySelectorAll<HTMLElement>('[data-drawer="open"]'))
    if (drawers.length === 0) { root.style.removeProperty('--toast-right'); return }
    const width = Math.max(...drawers.map(panelWidth))
    // On a phone the panel is the whole screen: nothing to dodge.
    root.style.setProperty('--toast-right', width >= window.innerWidth - 40 ? '16px' : `${width + 16}px`)
  }

  const resizeObserver = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(apply) : null
  const watch = () => {
    resizeObserver?.disconnect()
    document.querySelectorAll<HTMLElement>('[data-drawer="open"]').forEach((d) => resizeObserver?.observe(d))
    apply()
  }
  new MutationObserver(watch).observe(document.body, { childList: true, subtree: true })
  window.addEventListener('resize', apply)
  watch()
}

/**
 * Small, attribute-only helpers that let ds.css give EVERY pop-up the designer's look without
 * editing each page. Nothing here changes behaviour or React state: it only sets data-* hints.
 *
 *  - Cancel / Close buttons inside a pop-up get data-kit-role="cancel" (drawn as the outlined
 *    navy button, never a text link or the old grey button).
 *  - A pop-up whose content is taller than the screen gets data-kit-scrolls on its panel, and its
 *    header and footer row are marked so they stay in view while the middle scrolls.
 */
const PANEL_SELECTOR = ':scope > :not(.absolute):not([data-kit-skip])'
const CANCEL_TEXT = /^(cancel|close|back|no|not now|dismiss)$/i

function textOf(el: Element): string {
  return (el.textContent ?? '').replace(/\s+/g, ' ').trim()
}

/** The visible box of a pop-up: its biggest child that is not the dim backdrop. */
export function panelOf(overlay: HTMLElement): HTMLElement | null {
  const kids = Array.from(overlay.querySelectorAll<HTMLElement>(PANEL_SELECTOR))
  if (!kids.length) return null
  const area = (e: HTMLElement) => { const r = e.getBoundingClientRect(); return r.width * r.height }
  return kids.sort((a, b) => area(b) - area(a))[0]
}

function hasHeading(el: Element): boolean {
  return !!el.querySelector('h1, h2, h3, h4') || !!el.querySelector('svg.lucide-x')
}

export function tagPopup(overlay: HTMLElement): void {
  // Cancel / close buttons.
  overlay.querySelectorAll<HTMLButtonElement>('button').forEach((b) => {
    if (b.dataset.kitRole) return
    if (CANCEL_TEXT.test(textOf(b))) b.dataset.kitRole = 'cancel'
  })

  const panel = panelOf(overlay)
  if (!panel) return
  const cs = window.getComputedStyle(panel)
  const scrolls = panel.scrollHeight > panel.clientHeight + 1 && /(auto|scroll)/.test(cs.overflowY)
  if (!scrolls) {
    panel.removeAttribute('data-kit-scrolls')
    return
  }
  panel.setAttribute('data-kit-scrolls', '')
  panel.style.setProperty('--kit-pad-top', cs.paddingTop)
  panel.style.setProperty('--kit-pad-bottom', cs.paddingBottom)

  // Step into a single wrapper (a form, or one div) so the header and footer are found.
  let root: HTMLElement = panel
  while (root.children.length === 1 && /^(FORM|DIV)$/.test(root.firstElementChild!.tagName)) {
    root = root.firstElementChild as HTMLElement
  }
  const first = root.firstElementChild as HTMLElement | null
  const last = root.lastElementChild as HTMLElement | null
  if (first && hasHeading(first) && !first.querySelector('input, select, textarea, table')) {
    first.setAttribute('data-kit-header', '')
  }
  if (last && last !== first && last.querySelector('button') && !last.querySelector('input, select, textarea, table')) {
    last.setAttribute('data-kit-footer', '')
  }
}

/** Tags every pop-up currently on screen. */
export function tagAllPopups(doc: Document = document): void {
  doc.querySelectorAll<HTMLElement>('.fixed.inset-0').forEach((el) => {
    if (el.childElementCount === 0) return // an invisible click-catcher, not a pop-up
    tagPopup(el)
  })
}

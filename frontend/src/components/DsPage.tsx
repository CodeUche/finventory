/**
 * DsPage — wraps a page in the designer's look. Pages keep their own markup
 * and logic; the `.ds` scope (src/styles/ds.css) restyles their buttons,
 * inputs, tables, cards and badges to the new design. Pages that are not yet
 * designed are simply not wrapped, so they keep their current look.
 */
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { hasMutationInFlight } from '@/services/api'
import '@/styles/ds.css'

// Listens to the same window events the app uses for connectivity (the browser's own, plus the
// ones services/api.ts dispatches when the network is unreachable but the browser still says online).
// It does not toast or sync, so it is safe next to useNetworkStatus.
function useIsOffline() {
  const [offline, setOffline] = useState(() => typeof navigator !== 'undefined' && !navigator.onLine)
  useEffect(() => {
    const off = () => setOffline(true)
    const on = () => setOffline(false)
    window.addEventListener('offline', off)
    window.addEventListener('online', on)
    return () => { window.removeEventListener('offline', off); window.removeEventListener('online', on) }
  }, [])
  return offline
}

// Escape closes the top-most pop-up on a designed page, once, for every page. It presses the
// pop-up's own close control (the X, or a Cancel/Close button), so a page's own close logic
// (clearing a form, asking about unsaved changes) runs exactly as when the user clicks it.
// It does nothing while a save is running (a write request is still in flight, or a disabled button shows a spinner), while a
// confirm dialog is on top, or when another handler already used the key.
function useEscapeClosesPopup(root: React.RefObject<HTMLDivElement | null>) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape' || e.defaultPrevented) return
      if (document.querySelector('[role="dialog"]')) return
      // A save is running (any write request not yet answered): never close under it.
      if (hasMutationInFlight()) return
      const overlays = root.current?.querySelectorAll<HTMLElement>('.fixed.inset-0')
      const top = overlays && overlays[overlays.length - 1]
      if (!top) return
      if (top.querySelector('button:disabled .animate-spin')) return
      const buttons = Array.from(top.querySelectorAll<HTMLButtonElement>('button:not(:disabled)'))
      const closer =
        buttons.find((b) => b.querySelector('svg.lucide-x')) ??
        buttons.find((b) => /^(cancel|close)$/i.test(b.textContent?.trim() ?? ''))
      if (closer) closer.click()
      else top.querySelector<HTMLElement>('.absolute.inset-0')?.click()
      e.preventDefault()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [root])
}

export default function DsPage({ children }: { children: ReactNode }) {
  const offline = useIsOffline()
  const rootRef = useRef<HTMLDivElement>(null)
  useEscapeClosesPopup(rootRef)
  return (
    <div className="ds" ref={rootRef}>
      {offline && (
        <div role="status" className="ds-offline-note">
          You are offline. Figures and lists below are the last saved copy and may be out of date.
          They refresh by themselves when the connection returns.
        </div>
      )}
      {children}
    </div>
  )
}

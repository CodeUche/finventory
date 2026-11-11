/**
 * DsPage — wraps a page in the designer's look. Pages keep their own markup
 * and logic; the `.ds` scope (src/styles/ds.css) restyles their buttons,
 * inputs, tables, cards and badges to the new design. Pages that are not yet
 * designed are simply not wrapped, so they keep their current look.
 */
import { useEffect, useState, type ReactNode } from 'react'
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

export default function DsPage({ children }: { children: ReactNode }) {
  const offline = useIsOffline()
  return (
    <div className="ds">
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

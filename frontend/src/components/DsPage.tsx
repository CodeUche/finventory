/**
 * DsPage — wraps a page in the designer's look. Pages keep their own markup
 * and logic; the `.ds` scope (src/styles/ds.css) restyles their buttons,
 * inputs, tables, cards and badges to the new design. Pages that are not yet
 * designed are simply not wrapped, so they keep their current look.
 */
import { useEffect, type ReactNode } from 'react'
import { installGlobalEscape } from '@/lib/escapeStack'
import '@/styles/ds.css'

// The offline notice lives in ONE place: the banner at the top of the page (AppLayout). DsPage no
// longer adds a second amber box under it.
//
// Escape closing pop-ups is one app-wide handler (lib/escapeStack.ts). It is started here as well
// as in main.tsx so a designed page works the same in isolation (tests, previews).
export default function DsPage({ children }: { children: ReactNode }) {
  useEffect(() => installGlobalEscape(), [])
  return <div className="ds">{children}</div>
}

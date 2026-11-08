/**
 * DsPage — wraps a page in the designer's look. Pages keep their own markup
 * and logic; the `.ds` scope (src/styles/ds.css) restyles their buttons,
 * inputs, tables, cards and badges to the new design. Pages that are not yet
 * designed are simply not wrapped, so they keep their current look.
 */
import type { ReactNode } from 'react'
import '@/styles/ds.css'

export default function DsPage({ children }: { children: ReactNode }) {
  return <div className="ds">{children}</div>
}

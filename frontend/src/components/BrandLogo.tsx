/**
 * BrandLogo — the Audity diamond + wordmark, drawn in code so it follows the
 * theme (white wordmark in dark, near-black in light). Same artwork as the
 * auth screens' logo (see AuthShell), sized for the app's top bar.
 *
 * `iconOnly` renders just the diamond (used when the sidebar is collapsed).
 */
import { useId } from 'react'

export default function BrandLogo({ iconOnly = false, className = '' }: { iconOnly?: boolean; className?: string }) {
  // Unique gradient ids: the logo can render more than once on a page.
  const id = useId().replace(/:/g, '')
  return (
    <div className={`brand-logo ${className}`} role="img" aria-label="Audity — Accounting, Compliance, ERP">
      <svg className="brand-logo-mark" viewBox="0 0 80 96" aria-hidden="true">
        <defs>
          <linearGradient id={`f1-${id}`} x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="#5A77F5" /><stop offset="1" stopColor="#2F45D8" />
          </linearGradient>
          <linearGradient id={`f2-${id}`} x1="1" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="#3D5CF0" /><stop offset="1" stopColor="#2536B8" />
          </linearGradient>
          <linearGradient id={`f3-${id}`} x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="#2B3FC0" /><stop offset="1" stopColor="#141E78" />
          </linearGradient>
          <linearGradient id={`f4-${id}`} x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="#2A3CC4" /><stop offset="1" stopColor="#1A2690" />
          </linearGradient>
          <radialGradient id={`glow-${id}`}>
            <stop offset="0" stopColor="#fff" stopOpacity=".95" /><stop offset="1" stopColor="#9FB2FF" stopOpacity="0" />
          </radialGradient>
        </defs>
        <polygon points="40,0 0,48 40,48" fill={`url(#f1-${id})`} />
        <polygon points="40,0 80,48 40,48" fill={`url(#f2-${id})`} />
        <polygon points="0,48 40,96 40,48" fill={`url(#f3-${id})`} />
        <polygon points="80,48 40,96 40,48" fill={`url(#f4-${id})`} />
        <circle cx="40" cy="48" r="6" fill={`url(#glow-${id})`} />
      </svg>
      {!iconOnly && (
        <div className="brand-logo-word">
          <span className="brand-logo-name">AUDITY</span>
          <span className="brand-logo-tag">ACCOUNTING · COMPLIANCE · ERP</span>
        </div>
      )}
    </div>
  )
}

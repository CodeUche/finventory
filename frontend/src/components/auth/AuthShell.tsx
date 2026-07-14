/**
 * AuthShell — shared chrome for all auth pages (login, register, staff login,
 * MFA, verification screens). Renders the "Compass" background graphic, the
 * editorial left panel (real Audity diamond logo + headline), a theme toggle,
 * and a right-hand slot for the page's form card.
 *
 * Fully theme-aware: styling lives in src/styles/auth.css and keys off the
 * html.light / html.dark class managed by useTheme.
 */
import { useEffect, useState, type ReactNode } from 'react'
import { Moon, Sun } from 'lucide-react'
import AudityLogo from '@/components/AudityLogo'
import { getStoredTheme, setTheme, type Theme } from '@/hooks/useTheme'
import '@/styles/auth.css'

function ThemeToggle() {
  const [theme, setLocal] = useState<Theme>(getStoredTheme)
  useEffect(() => {
    const handler = (e: Event) => setLocal((e as CustomEvent<Theme>).detail)
    window.addEventListener('themechange', handler)
    return () => window.removeEventListener('themechange', handler)
  }, [])
  return (
    <button
      type="button"
      className="au-theme"
      onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
      aria-label={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
    >
      {theme === 'dark' ? <Sun size={15} /> : <Moon size={15} />}
      <span>{theme === 'dark' ? 'Light' : 'Dark'}</span>
    </button>
  )
}

interface Props {
  children: ReactNode
  /** Headline shown on the editorial panel. Defaults to the brand line. */
  headline?: ReactNode
  lead?: string
}

export default function AuthShell({ children, headline, lead }: Props) {
  return (
    <div className="audity-auth">
      {/* ---- Compass background graphic ---- */}
      <div className="au-canvas" aria-hidden="true">
        <svg className="au-bg au-compass" viewBox="0 0 1440 900" preserveAspectRatio="xMidYMid slice" fill="none" xmlns="http://www.w3.org/2000/svg">
          <g transform="translate(1040 450)" opacity="0.5">
            <g className="au-line" strokeWidth="1">
              <path d="M0 -81 L70 0 L0 81 L-70 0 Z" />
              <path d="M0 -162 L140 0 L0 162 L-140 0 Z" />
              <path d="M0 -244 L210 0 L0 244 L-210 0 Z" />
              <path d="M0 -325 L280 0 L0 325 L-280 0 Z" />
              <path d="M0 -406 L350 0 L0 406 L-350 0 Z" opacity="0.6" />
            </g>
            <g className="au-line" strokeWidth="1" strokeDasharray="2 7" opacity="0.7">
              <line x1="0" y1="-440" x2="0" y2="440" />
              <line x1="-400" y1="0" x2="400" y2="0" />
            </g>
            <g className="au-line" strokeWidth="1.4">
              <line x1="0" y1="-406" x2="0" y2="-386" />
              <line x1="0" y1="406" x2="0" y2="386" />
              <line x1="-350" y1="0" x2="-330" y2="0" />
              <line x1="350" y1="0" x2="330" y2="0" />
            </g>
            <path d="M0 -325 L18 -300 L-18 -300 Z" className="au-gold-f" opacity="0.8" />
            <circle r="22" className="au-gold" strokeWidth="1.2" opacity="0.7" />
            <circle r="5" className="au-gold-f" />
          </g>
        </svg>
      </div>

      <ThemeToggle />

      <div className="au-stage">
        <div className="au-left">
          <AudityLogo variant="horizontal" className="au-logo" />
          <h1 className="au-display">
            {headline ?? (<>Numbers you can <em>finally</em> trust.</>)}
          </h1>
          <p className="au-lead">
            {lead ?? 'Every sale, bill and journal entry — reconciled automatically and audit-ready, the moment it happens.'}
          </p>
          <div className="au-trust"><span className="au-dot" /> Trusted by growing businesses across Africa.</div>
        </div>

        <main className="au-right">{children}</main>
      </div>

      <footer style={{ position: 'relative', zIndex: 1, textAlign: 'center', padding: '8px 20px 28px', fontSize: 12.5 }}>
        <a href="/legal/terms" target="_blank" rel="noopener" className="au-link" style={{ margin: '0 10px' }}>Terms</a>
        <a href="/legal/privacy" target="_blank" rel="noopener" className="au-link" style={{ margin: '0 10px' }}>Privacy</a>
        <a href="/legal/dpa" target="_blank" rel="noopener" className="au-link" style={{ margin: '0 10px' }}>Data Processing</a>
      </footer>
    </div>
  )
}

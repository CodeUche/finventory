/**
 * AuthShell — shared chrome for all auth pages (login, register, staff login,
 * MFA, verification screens). Follows the Audity design system: photo
 * background, brand panel on the left (logo, headline), and on the right an
 * optional heading + Sign in / Sign up tabs above the glass form card.
 *
 * Fully theme-aware: styling lives in src/styles/auth.css and keys off the
 * html.light / html.dark class managed by useTheme.
 */
import { useEffect, useId, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { Moon, Sun } from 'lucide-react'
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
      {theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />}
      <span>{theme === 'dark' ? 'Light' : 'Dark'}</span>
    </button>
  )
}

/** Audity diamond + wordmark, drawn in code so it follows the theme. */
function AuthLogo({ className }: { className?: string }) {
  // Unique gradient ids: the logo renders twice, and a hidden copy would otherwise win the id lookup.
  const id = useId().replace(/:/g, '')
  return (
    <div className={`au-brand ${className ?? ''}`} role="img" aria-label="Audity — Accounting, Compliance, ERP">
      <svg className="au-diamond" viewBox="0 0 80 96" aria-hidden="true">
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
      <div className="au-wordmark">
        <span className="au-name">AUDITY</span>
        <span className="au-tag">ACCOUNTING · COMPLIANCE · ERP</span>
      </div>
    </div>
  )
}

interface Props {
  children: ReactNode
  /** Headline shown on the brand panel. Defaults to the brand line. */
  headline?: ReactNode
  lead?: string
  /** Heading above the card (design: "Welcome Back!" / "Get Started!"). */
  title?: string
  subtitle?: ReactNode
  /** Shows the Sign in / Sign up tabs, with this one active. */
  tab?: 'in' | 'up'
}

export default function AuthShell({ children, headline, lead, title, subtitle, tab }: Props) {
  return (
    <div className="audity-auth">
      <ThemeToggle />

      <div className="au-stage">
        <div className="au-left">
          <AuthLogo className="au-logo" />
          <div className="au-copy">
            <h1 className="au-display">
              {headline ?? (<>Every number tells the <em>truth</em>.</>)}
            </h1>
            <p className="au-lead">
              {lead ?? 'Accounting that keeps up with your business. Every figure backed by certainty.'}
            </p>
            <p className="au-trust">. . .For businesses built to last.</p>
          </div>
        </div>

        <main className="au-right">
          <AuthLogo className="au-logo-sm" />
          {title && (
            <header className="au-head">
              <h2>{title}</h2>
              {subtitle && <p>{subtitle}</p>}
            </header>
          )}
          {tab && (
            <nav className="au-tabs" aria-label="Sign in or sign up">
              <Link to="/login" className={tab === 'in' ? 'on' : ''} aria-current={tab === 'in' ? 'page' : undefined}>Sign in</Link>
              <span className="au-tabs-bar" aria-hidden="true" />
              <Link to="/register" className={tab === 'up' ? 'on' : ''} aria-current={tab === 'up' ? 'page' : undefined}>Sign up</Link>
            </nav>
          )}
          {children}
        </main>
      </div>

      <footer className="au-footer">
        <a href="/legal/terms" target="_blank" rel="noopener" className="au-link">Terms</a>
        <a href="/legal/privacy" target="_blank" rel="noopener" className="au-link">Privacy</a>
        <a href="/legal/dpa" target="_blank" rel="noopener" className="au-link">Data Processing</a>
      </footer>
    </div>
  )
}

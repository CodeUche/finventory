/**
 * Shared chrome for the public legal document pages (Terms, Privacy, DPA).
 * Theme-aware via the global html.light class. Linked from the registration
 * clickwrap checkbox and the re-acceptance gate.
 */
import { useNavigate, Link } from 'react-router-dom'
import { ArrowLeft } from 'lucide-react'
import type { ReactNode } from 'react'

const DOCS = [
  { to: '/legal/terms', label: 'Terms & Conditions' },
  { to: '/legal/privacy', label: 'Privacy Policy' },
  { to: '/legal/dpa', label: 'Data Processing Agreement' },
]

export default function LegalShell({ title, children }: { title: string; children: ReactNode }) {
  const navigate = useNavigate()
  return (
    <div className="min-h-screen bg-surface-950 text-slate-200">
      <header className="sticky top-0 z-10 border-b border-surface-700 bg-surface-900/90 backdrop-blur">
        <div className="max-w-4xl mx-auto px-5 py-3.5 flex items-center gap-4">
          <button
            onClick={() => (window.history.length > 1 ? navigate(-1) : navigate('/login'))}
            className="flex items-center gap-1.5 text-sm text-slate-400 hover:text-white transition-colors"
          >
            <ArrowLeft size={16} /> Back
          </button>
          <img src="/audity-logo-dark.svg" alt="Audity" className="h-6 w-auto ml-auto opacity-90" />
        </div>
      </header>

      <main className="max-w-4xl mx-auto px-5 py-10">
        <h1 className="text-2xl sm:text-3xl font-bold text-white mb-1">{title}</h1>
        <p className="text-sm text-slate-500 mb-8">
          Audity Technologies Limited · Last updated: 13 July 2026
        </p>

        <article className="legal-content">{children}</article>

        <nav className="mt-12 pt-6 border-t border-surface-700 flex flex-wrap gap-x-6 gap-y-2 text-sm">
          {DOCS.filter((d) => d.label !== title).map((d) => (
            <Link key={d.to} to={d.to} className="text-brand-400 hover:text-brand-300 font-medium">
              {d.label} →
            </Link>
          ))}
          <span className="text-slate-600 ml-auto">© Audity Technologies Limited · RC 9395403</span>
        </nav>
      </main>
    </div>
  )
}

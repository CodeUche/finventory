import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Search, ChevronRight } from 'lucide-react'
import { navGroups } from '@/components/layout/Sidebar'

interface Cmd { name: string; href: string; group: string; icon: React.ElementType }

/**
 * ⌘K / Ctrl+K command palette. Flattens the sidebar nav into a searchable,
 * keyboard-driven launcher — essential once the accountant-first nav gets deep.
 * Route guards still enforce access, so this stays a thin convenience layer.
 */
export default function CommandPalette() {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)
  const navigate = useNavigate()

  const commands = useMemo<Cmd[]>(() => {
    const out: Cmd[] = []
    for (const g of navGroups) {
      for (const it of g.items) {
        out.push({ name: it.name, href: it.href, group: g.label ?? 'General', icon: it.icon })
      }
    }
    return out
  }, [])

  const results = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return commands.slice(0, 20)
    return commands
      .filter((c) => c.name.toLowerCase().includes(q) || c.group.toLowerCase().includes(q))
      .slice(0, 20)
  }, [query, commands])

  // Global shortcut
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setOpen((o) => !o)
      } else if (e.key === 'Escape') {
        setOpen(false)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  useEffect(() => {
    if (open) { setQuery(''); setActive(0); setTimeout(() => inputRef.current?.focus(), 30) }
  }, [open])
  useEffect(() => { setActive(0) }, [query])

  if (!open) return null

  const go = (href: string) => { setOpen(false); navigate(href) }

  const onListKey = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); setActive((a) => Math.min(a + 1, results.length - 1)) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)) }
    else if (e.key === 'Enter' && results[active]) { e.preventDefault(); go(results[active].href) }
  }

  return (
    <div className="fixed inset-0 z-[100] flex items-start justify-center pt-[15vh] bg-black/60"
      onClick={() => setOpen(false)}>
      <div className="w-full max-w-lg mx-4 bg-surface-900 border border-surface-700 rounded-xl shadow-2xl overflow-hidden"
        onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-2 px-4 py-3 border-b border-surface-700">
          <Search size={16} className="text-slate-400" />
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={onListKey}
            placeholder="Search pages… (⌘K)"
            className="flex-1 bg-transparent text-sm text-white outline-none placeholder:text-slate-500"
          />
          <kbd className="text-[10px] text-slate-500 border border-surface-600 rounded px-1.5 py-0.5">ESC</kbd>
        </div>
        <div className="max-h-80 overflow-y-auto py-1">
          {results.length === 0 ? (
            <div className="px-4 py-6 text-center text-sm text-slate-500">No matches</div>
          ) : results.map((c, i) => {
            const Icon = c.icon
            return (
              <button
                key={`${c.href}-${c.name}`}
                onMouseEnter={() => setActive(i)}
                onClick={() => go(c.href)}
                className={`w-full flex items-center gap-3 px-4 py-2 text-left text-sm ${i === active ? 'bg-brand-600/20 text-white' : 'text-slate-300'}`}
              >
                <Icon size={15} className="text-slate-400 shrink-0" />
                <span className="flex-1">{c.name}</span>
                <span className="text-[10px] text-slate-500 uppercase tracking-wide">{c.group}</span>
                {i === active && <ChevronRight size={13} className="text-slate-500" />}
              </button>
            )
          })}
        </div>
      </div>
    </div>
  )
}

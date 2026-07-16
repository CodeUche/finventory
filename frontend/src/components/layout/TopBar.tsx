import { Menu, Search, X, Package, Receipt, Users, Sun, Moon, LogOut } from 'lucide-react'
import { useState, useEffect, useRef, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import toast from 'react-hot-toast'
import { useAuthStore } from '@/store/authStore'
import { orgApi, inventoryApi, salesApi, customerApi, authApi } from '@/services/api'
import { setActiveCurrency, formatCurrency } from '@/lib/utils'
import NotificationBell from '@/components/NotificationBell'
import { SyncStatusBadge } from '@/components/SyncStatusBadge'
import { getStoredTheme, setTheme, type Theme } from '@/hooks/useTheme'

const CURRENCIES = [
  'NGN', 'USD', 'EUR', 'GBP', 'GHS', 'KES', 'ZAR', 'XOF', 'XAF',
  'EGP', 'MAD', 'TZS', 'UGX', 'RWF', 'ZMW', 'BWP',
]

interface SearchResult {
  type: 'product' | 'invoice' | 'customer'
  id: string
  primary: string
  secondary: string
  href: string
}

interface TopBarProps {
  onMenuClick: () => void
}

export default function TopBar({ onMenuClick }: TopBarProps) {
  const { organisation, updateOrganisation, tokens, logout } = useAuthStore()
  const navigate = useNavigate()
  const [currentTheme, setCurrentTheme] = useState<Theme>(getStoredTheme)

  const toggleTheme = () => {
    const next: Theme = currentTheme === 'dark' ? 'light' : 'dark'
    setTheme(next)
    setCurrentTheme(next)
  }

  const handleLogout = async () => {
    try {
      if (tokens?.refresh) await authApi.logout(tokens.refresh)
    } finally {
      logout()
      navigate('/login')
    }
  }

  const [query, setQuery] = useState('')
  const [results, setResults] = useState<SearchResult[]>([])
  const [searching, setSearching] = useState(false)
  const [showDrop, setShowDrop] = useState(false)
  const [activeIndex, setActiveIndex] = useState(-1)
  const inputRef = useRef<HTMLInputElement>(null)
  const dropRef = useRef<HTMLDivElement>(null)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const handleCurrencyChange = async (newCurrency: string) => {
    if (!organisation || newCurrency === organisation.currency) return
    try {
      await orgApi.update(organisation.id, { currency: newCurrency })
      updateOrganisation({ currency: newCurrency })
      setActiveCurrency(newCurrency)
      toast.success(`Currency changed to ${newCurrency}`)
    } catch (err: unknown) {
      const apiErr = (err as { response?: { data?: { error?: { message?: string } | string } } })?.response?.data?.error
      const msg = typeof apiErr === 'string' ? apiErr : (apiErr?.message ?? 'Failed to update currency')
      toast.error(msg)
    }
  }

  const runSearch = useCallback(async (q: string) => {
    if (!q.trim()) { setResults([]); return }
    setSearching(true)
    try {
      const [prodRes, invRes, custRes] = await Promise.allSettled([
        inventoryApi.products({ search: q, page_size: 5 }),
        salesApi.invoices({ search: q, page_size: 5 }),
        customerApi.list({ search: q, page_size: 5 }),
      ])

      const out: SearchResult[] = []

      if (prodRes.status === 'fulfilled') {
        const items = prodRes.value.data.results ?? prodRes.value.data
        items.slice(0, 4).forEach((p: any) => out.push({
          type: 'product',
          id: p.id,
          primary: p.name,
          secondary: `SKU: ${p.sku}`,
          href: '/inventory/products',
        }))
      }

      if (invRes.status === 'fulfilled') {
        const items = invRes.value.data.results ?? invRes.value.data
        items.slice(0, 4).forEach((inv: any) => out.push({
          type: 'invoice',
          id: inv.id,
          primary: inv.invoice_number,
          secondary: `${inv.customer_name ?? 'Walk-in'} · ${formatCurrency(inv.total_amount)}`,
          href: '/sales',
        }))
      }

      if (custRes.status === 'fulfilled') {
        const items = custRes.value.data.results ?? custRes.value.data
        items.slice(0, 4).forEach((c: any) => out.push({
          type: 'customer',
          id: c.id,
          primary: c.name,
          secondary: c.email ?? c.phone ?? '',
          href: '/customers',
        }))
      }

      setResults(out)
      setActiveIndex(-1)
      setShowDrop(true)
    } catch {
      // silently fail
    } finally {
      setSearching(false)
    }
  }, [])

  useEffect(() => {
    if (timerRef.current) clearTimeout(timerRef.current)
    if (!query.trim()) {
      setResults([])
      setShowDrop(false)
      return
    }
    timerRef.current = setTimeout(() => runSearch(query), 350)
    return () => { if (timerRef.current) clearTimeout(timerRef.current) }
  }, [query, runSearch])

  // Close on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (
        dropRef.current && !dropRef.current.contains(e.target as Node) &&
        inputRef.current && !inputRef.current.contains(e.target as Node)
      ) {
        setShowDrop(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  const handleSelect = (r: SearchResult) => {
    setQuery('')
    setShowDrop(false)
    setActiveIndex(-1)
    navigate(r.href)
  }

  const clearSearch = () => {
    setQuery('')
    setResults([])
    setShowDrop(false)
    setActiveIndex(-1)
    inputRef.current?.focus()
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (!showDrop || results.length === 0) return
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setActiveIndex((prev) => Math.min(prev + 1, results.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActiveIndex((prev) => Math.max(prev - 1, 0))
    } else if (e.key === 'Enter' && activeIndex >= 0) {
      e.preventDefault()
      handleSelect(results[activeIndex])
    } else if (e.key === 'Escape') {
      setShowDrop(false)
      setActiveIndex(-1)
    }
  }

  const iconFor = (type: SearchResult['type']) => {
    if (type === 'product') return <Package size={13} className="text-brand-400" />
    if (type === 'invoice') return <Receipt size={13} className="text-emerald-400" />
    return <Users size={13} className="text-purple-400" />
  }

  const labelFor = (type: SearchResult['type']) => {
    if (type === 'product') return 'Product'
    if (type === 'invoice') return 'Invoice'
    return 'Customer'
  }

  /** Splits `text` at every occurrence of `q` and wraps matches in a highlight span. */
  const highlight = (text: string, q: string) => {
    if (!q.trim()) return <span>{text}</span>
    const escaped = q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    const parts = text.split(new RegExp(`(${escaped})`, 'gi'))
    const lower = q.toLowerCase()
    return (
      <>
        {parts.map((part, i) =>
          part.toLowerCase() === lower ? (
            <mark key={i} className="bg-brand-500/30 text-brand-300 rounded px-0.5 not-italic font-semibold">
              {part}
            </mark>
          ) : (
            <span key={i}>{part}</span>
          )
        )}
      </>
    )
  }

  return (
    /* relative z-40: the TopBar must sit ABOVE page content so its dropdowns
       (notifications, search) fully cover page elements and their click-away
       overlays actually receive outside clicks. Modals (z-50) still win. */
    <header className="relative z-40 h-16 flex items-center gap-4 px-4 lg:px-6 border-b border-surface-700 bg-surface-900/50 backdrop-blur-sm shrink-0">
      <button onClick={onMenuClick} aria-label="Open menu" className="btn-ghost lg:hidden p-2">
        <Menu size={20} />
      </button>

      {/* Search bar */}
      <div className="flex-1 max-w-md relative">
        <div className="relative">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500 pointer-events-none" />
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onFocus={() => { if (results.length > 0) setShowDrop(true) }}
            onKeyDown={handleKeyDown}
            placeholder="Search products, invoices, customers..."
            className="w-full bg-surface-800 border border-surface-700 rounded-xl pl-9 pr-8 py-2 text-sm text-slate-300 placeholder:text-slate-500 focus:outline-none focus:border-brand-500 focus:ring-1 focus:ring-brand-500/30 transition-all"
          />
          {query && (
            <button onClick={clearSearch} className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300 transition-colors">
              <X size={14} />
            </button>
          )}
        </div>

        {/* Search dropdown */}
        {showDrop && (
          <div ref={dropRef} className="absolute top-full left-0 right-0 mt-2 bg-surface-800 border border-surface-700 rounded-xl shadow-2xl z-50 overflow-hidden">
            {searching ? (
              <div className="px-4 py-3 text-xs text-slate-500">Searching…</div>
            ) : results.length === 0 ? (
              <div className="px-4 py-3 text-xs text-slate-500">No results for "{query}"</div>
            ) : (
              <ul>
                {results.map((r, idx) => {
                  const isActive = idx === activeIndex
                  return (
                    <li key={`${r.type}-${r.id}`}>
                      <button
                        onClick={() => handleSelect(r)}
                        onMouseEnter={() => setActiveIndex(idx)}
                        className={[
                          'w-full flex items-center gap-3 px-4 py-2.5 transition-colors text-left',
                          isActive ? 'bg-brand-500/15 border-l-2 border-brand-500' : 'hover:bg-surface-700/60 border-l-2 border-transparent',
                        ].join(' ')}
                      >
                        <div className={[
                          'w-6 h-6 rounded-md flex items-center justify-center shrink-0 transition-colors',
                          isActive ? 'bg-brand-500/20' : 'bg-surface-700',
                        ].join(' ')}>
                          {iconFor(r.type)}
                        </div>
                        <div className="flex-1 min-w-0">
                          <p className="text-sm text-white truncate">{highlight(r.primary, query)}</p>
                          <p className="text-xs text-slate-500 truncate">{highlight(r.secondary, query)}</p>
                        </div>
                        <span className={[
                          'text-[10px] font-medium uppercase tracking-wider shrink-0',
                          isActive ? 'text-brand-400' : 'text-slate-600',
                        ].join(' ')}>
                          {labelFor(r.type)}
                        </span>
                      </button>
                    </li>
                  )
                })}
              </ul>
            )}
          </div>
        )}
      </div>

      <div className="flex items-center gap-3 ml-auto">
        {/* Theme toggle */}
        <button
          onClick={toggleTheme}
          className="btn-ghost p-2"
          aria-label="Toggle theme"
          title={currentTheme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
        >
          {currentTheme === 'dark' ? <Sun size={17} /> : <Moon size={17} />}
        </button>

        {/* Offline sync queue status (hidden when the queue is empty) */}
        <SyncStatusBadge />

        {/* Real-time notifications bell */}
        <NotificationBell />

        {/* Sign out shortcut */}
        <button
          onClick={handleLogout}
          className="btn-ghost p-2 text-slate-400 hover:text-red-400 transition-colors"
          aria-label="Sign out"
          title="Sign out"
        >
          <LogOut size={17} />
        </button>

        {/* Currency selector */}
        {organisation && (
          <div className="hidden sm:flex items-center gap-2 px-2 py-1.5 bg-surface-800 border border-surface-700 rounded-xl">
            <span className="text-xs text-slate-400">Currency</span>
            <select
              value={organisation.currency}
              onChange={(e) => handleCurrencyChange(e.target.value)}
              className="bg-transparent text-xs font-mono font-bold text-brand-400 border-none outline-none cursor-pointer"
            >
              {CURRENCIES.map((c) => (
                <option key={c} value={c} className="bg-surface-800 text-white">{c}</option>
              ))}
              {/* Keep current currency selectable even if not in list */}
              {!CURRENCIES.includes(organisation.currency) && (
                <option value={organisation.currency} className="bg-surface-800 text-white">{organisation.currency}</option>
              )}
            </select>
          </div>
        )}
      </div>
    </header>
  )
}

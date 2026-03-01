import { Menu, Search } from 'lucide-react'
import toast from 'react-hot-toast'
import { useAuthStore } from '@/store/authStore'
import { orgApi } from '@/services/api'
import { setActiveCurrency } from '@/lib/utils'
import NotificationBell from '@/components/NotificationBell'

const CURRENCIES = [
  'NGN', 'USD', 'EUR', 'GBP', 'GHS', 'KES', 'ZAR', 'XOF', 'XAF',
  'EGP', 'MAD', 'TZS', 'UGX', 'RWF', 'ZMW', 'BWP',
]

interface TopBarProps {
  onMenuClick: () => void
}

export default function TopBar({ onMenuClick }: TopBarProps) {
  const { organisation, updateOrganisation } = useAuthStore()

  const handleCurrencyChange = async (newCurrency: string) => {
    if (!organisation || newCurrency === organisation.currency) return
    try {
      await orgApi.update(organisation.id, { currency: newCurrency })
      updateOrganisation({ currency: newCurrency })
      setActiveCurrency(newCurrency)
      toast.success(`Currency changed to ${newCurrency}`)
    } catch {
      toast.error('Failed to update currency')
    }
  }

  return (
    <header className="h-16 flex items-center gap-4 px-4 lg:px-6 border-b border-surface-700 bg-surface-900/50 backdrop-blur-sm shrink-0">
      <button onClick={onMenuClick} className="btn-ghost lg:hidden p-2">
        <Menu size={20} />
      </button>

      {/* Search bar */}
      <div className="flex-1 max-w-md">
        <div className="relative">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
          <input
            type="text"
            placeholder="Search products, invoices, customers..."
            className="w-full bg-surface-800 border border-surface-700 rounded-xl pl-9 pr-4 py-2 text-sm text-slate-300 placeholder:text-slate-500 focus:outline-none focus:border-brand-500 focus:ring-1 focus:ring-brand-500/30 transition-all"
          />
        </div>
      </div>

      <div className="flex items-center gap-3 ml-auto">
        {/* Real-time notifications bell */}
        <NotificationBell />

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

import { useEffect, useState } from 'react'
import { Outlet, useNavigate } from 'react-router-dom'
import Sidebar from './Sidebar'
import TopBar from './TopBar'
import Breadcrumb from '@/components/Breadcrumb'
import { useInactivityTimeout } from '@/hooks/useInactivityTimeout'
import { useAuthStore } from '@/store/authStore'
import { setActiveCurrency } from '@/lib/utils'
import { useNetworkStatus } from '@/hooks/useNetworkStatus'
import { orgApi, subscriptionApi } from '@/services/api'
import { Briefcase, LogOut, WifiOff } from 'lucide-react'
import type { AccessLevel, ModuleKey, ModulePermission, Organisation } from '@/types'
import SubscriptionPaywall from '@/components/SubscriptionPaywall'
import SupportChat from '@/components/SupportChat'
import { FEATURES } from '@/lib/featureFlags'

export default function AppLayout() {
  const [sidebarOpen, setSidebarOpen] = useState(false)
  useInactivityTimeout()
  const online = useNetworkStatus()
  const navigate = useNavigate()
  const organisation = useAuthStore((s) => s.organisation)
  const organisations = useAuthStore((s) => s.organisations)
  const setOrganisation = useAuthStore((s) => s.setOrganisation)
  const setMembership = useAuthStore((s) => s.setMembership)
  const setPlanModules = useAuthStore((s) => s.setPlanModules)
  const setPlanTaxEngine = useAuthStore((s) => s.setPlanTaxEngine)
  const setPlanName = useAuthStore((s) => s.setPlanName)
  const setSubscriptionExpired = useAuthStore((s) => s.setSubscriptionExpired)
  const subscriptionExpired = useAuthStore((s) => s.subscriptionExpired)
  const user = useAuthStore((s) => s.user)
  const [subscriptionData, setSubscriptionData] = useState<any>(null)

  // Keep formatCurrency in sync with the org's currency setting
  useEffect(() => {
    if (organisation?.currency) setActiveCurrency(organisation.currency)
  }, [organisation?.currency])

  // Always refresh org data from the API on mount so that fields added since
  // last login (e.g. invoice_template) are never stale in the persisted store.
  useEffect(() => {
    if (!organisation?.id) return
    orgApi.list().then(({ data }) => {
      const orgs: any[] = data.results ?? data
      const fresh = orgs.find((o: any) => o.id === organisation.id) ?? orgs[0]
      if (fresh) setOrganisation(fresh)
    }).catch(() => { /* non-fatal — use persisted org */ })
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [organisation?.id])

  // Load the current user's role + module permissions from the API
  useEffect(() => {
    if (!organisation?.id) return
    orgApi.myMembership(organisation.id).then(({ data }) => {
      const perms: Partial<Record<ModuleKey, AccessLevel>> = {}
      ;(data.module_permissions as ModulePermission[]).forEach((p) => {
        perms[p.module] = p.access_level
      })
      setMembership(data.role as string, perms)
    }).catch(() => {
      // If membership fails to load, default to minimum access (viewer, no module permissions).
      // This prevents non-owners from seeing all items when the call errors.
      if (!user?.is_superuser) setMembership('viewer', {})
    })
  }, [organisation?.id, setMembership])

  // Load the active subscription plan's module list for sidebar gating.
  // Superusers bypass all plan restrictions (planModules stays null).
  // Also detect expired subscriptions and show the paywall.
  useEffect(() => {
    if (!organisation?.id || user?.is_superuser) return
    subscriptionApi.current().then(({ data }) => {
      const modules: string[] | null = data?.plan?.features?.modules ?? null
      setPlanModules(modules)
      setPlanTaxEngine(data?.plan?.features?.tax_engine ?? null)
      setPlanName(data?.plan?.name?.toLowerCase() ?? null)
      if (data?.is_expired && !user?.is_superuser) {
        setSubscriptionExpired(true)
        setSubscriptionData(data)
      } else {
        setSubscriptionExpired(false)
      }
    }).catch(() => { setPlanModules(null); setPlanTaxEngine(null); setPlanName(null) })
  }, [organisation?.id, user?.is_superuser, setPlanModules, setPlanTaxEngine, setPlanName, setSubscriptionExpired])

  const handlePaywallDismiss = () => {
    setSubscriptionExpired(false)
    setSubscriptionData(null)
    // Re-fetch subscription to refresh state
    if (organisation?.id && !user?.is_superuser) {
      subscriptionApi.current().then(({ data }) => {
        const modules: string[] | null = data?.plan?.features?.modules ?? null
        setPlanModules(modules)
        setPlanTaxEngine(data?.plan?.features?.tax_engine ?? null)
        setPlanName(data?.plan?.name?.toLowerCase() ?? null)
        if (data?.is_expired) {
          setSubscriptionExpired(true)
          setSubscriptionData(data)
        }
      }).catch(() => { /* non-fatal */ })
    }
  }

  return (
    <div className="flex h-screen bg-surface-950 overflow-hidden">
      {/* Mobile overlay */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 z-20 bg-black/60 backdrop-blur-sm lg:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      {/* Sidebar */}
      <Sidebar open={sidebarOpen} onClose={() => setSidebarOpen(false)} />

      {/* Main content */}
      <div className="flex flex-col flex-1 min-w-0 overflow-hidden">
        <TopBar onMenuClick={() => setSidebarOpen(true)} />
        {/* Offline banner */}
        {!online && (
          <div className="flex items-center gap-2 px-4 py-2 bg-amber-500/15 border-b border-amber-500/30 text-amber-400 text-xs font-medium">
            <WifiOff size={13} />
            You&apos;re offline — read-only mode. Changes will be queued and synced automatically when reconnected.
          </div>
        )}
        {/* Client view amber banner — hidden until PARTNER_CHANNEL feature is enabled */}
        {FEATURES.PARTNER_CHANNEL && organisation?.managing_firm_name && (
          <div className="flex items-center justify-between px-4 py-2 bg-amber-500/15 border-b border-amber-500/30 text-amber-400 text-xs font-medium">
            <span className="flex items-center gap-1.5">
              <Briefcase size={13} />
              Managing client books: <strong className="text-amber-300 ml-1">{organisation.name}</strong>
              <span className="text-amber-500">&nbsp;·&nbsp;</span>
              Managed by {organisation.managing_firm_name}
            </span>
            <button
              onClick={async () => {
                try {
                  const { data } = await orgApi.list()
                  const orgs: Organisation[] = data.results ?? data
                  const own = orgs.find((o) => !o.managing_firm_name)
                  if (own) { setOrganisation(own); navigate('/dashboard') }
                } catch {
                  // fallback: try in-memory list
                  const own = organisations.find((o) => !o.managing_firm_name)
                  if (own) { setOrganisation(own); navigate('/dashboard') }
                }
              }}
              className="flex items-center gap-1 hover:text-white transition-colors ml-4"
            >
              <LogOut size={12} /> Exit Client View
            </button>
          </div>
        )}
        {/* Breadcrumb trail */}
        <div className="px-4 lg:px-6 pt-3 pb-0">
          <Breadcrumb />
        </div>
        <main className="flex-1 overflow-y-auto p-4 lg:p-6 animate-fade-in">
          <Outlet />
        </main>
      </div>

      {/* Subscription paywall overlay */}
      {subscriptionExpired && !user?.is_superuser && (
        <SubscriptionPaywall subscription={subscriptionData} onDismiss={handlePaywallDismiss} />
      )}

      {/* Floating support chat */}
      <SupportChat />
    </div>
  )
}

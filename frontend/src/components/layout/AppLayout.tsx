import { useEffect, useState } from 'react'
import { Outlet, useNavigate } from 'react-router-dom'
import Sidebar from './Sidebar'
import TopBar from './TopBar'
import Breadcrumb from '@/components/Breadcrumb'
import { useInactivityTimeout } from '@/hooks/useInactivityTimeout'
import { useAuthStore } from '@/store/authStore'
import { setActiveCurrency } from '@/lib/utils'
import { useNetworkStatus } from '@/hooks/useNetworkStatus'
import { api, orgApi, subscriptionApi } from '@/services/api'
import { Briefcase, LogOut, WifiOff } from 'lucide-react'
import { offlineCache, timeAgo } from '@/lib/offlineCache'
import type { AccessLevel, ModuleKey, ModulePermission, Organisation } from '@/types'
import SubscriptionPaywall from '@/components/SubscriptionPaywall'
import SupportChat from '@/components/SupportChat'
import { FEATURES } from '@/lib/featureFlags'

export default function AppLayout() {
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [cacheAge, setCacheAge] = useState<string | null>(null)
  // True once the org-list fetch has completed (success or failure).
  // Used to gate <Outlet /> so module pages never fire their initial fetch
  // while organisation?.id is still null (which happens for superusers who
  // have no personal orgs — orgApi.list() must resolve first so we can pick
  // orgs[0] as the active org before child pages mount).
  // Lazy-initialised to true when org is already set (regular users) so they
  // see no spinner at all.
  const [orgListLoaded, setOrgListLoaded] = useState(
    () => !!useAuthStore.getState().organisation?.id,
  )
  // Incremented by the Refresh button (via audity:app-refresh) to force re-run of
  // org/membership/plan effects without requiring an internet toggle.
  const [_appRefreshTick, setAppRefreshTick] = useState(0)
  useInactivityTimeout()
  const online = useNetworkStatus()

  useEffect(() => {
    const handler = () => setAppRefreshTick((t) => t + 1)
    window.addEventListener('audity:app-refresh', handler)
    return () => window.removeEventListener('audity:app-refresh', handler)
  }, [])

  // When going offline, resolve the cache age to show in the banner
  useEffect(() => {
    if (!online) {
      offlineCache.oldestCachedAt().then((ts) => {
        setCacheAge(ts ? timeAgo(ts) : null)
      })
    } else {
      setCacheAge(null)
    }
  }, [online])
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

  // Always refresh org data from the API on mount, and again when connectivity is
  // restored after a cold-start failure.
  //
  // IMPORTANT: `online` is included in deps so that if the Railway backend was
  // cold-starting when the app launched (causing orgApi.list() to time out and
  // _signalOffline() to fire), this effect re-runs the moment the background
  // connectivity probe signals recovery.  Without this, organisation stays null,
  // the membership + subscription effects never fire, and the sidebar shows no
  // modules even after the backend becomes reachable.
  //
  // The fresh-cache gate in api.ts makes subsequent re-runs cheap: if the response
  // is < 5 min old it is served from IndexedDB without hitting the network.
  useEffect(() => {
    if (!user) return  // not authenticated yet
    if (!online && organisation) return  // offline + already have org — skip, use persisted state
    orgApi.list().then(({ data }) => {
      const orgs: any[] = data.results ?? data
      if (!orgs.length) {
        // No orgs returned (pure platform-admin superuser with no active orgs).
        // Mark loaded so the <Outlet /> gate lifts — platform-admin and other
        // superuser-only pages don't require an org context.
        setOrgListLoaded(true)
        return
      }
      // Re-select the previously active org if we still have access to it,
      // otherwise fall back to the first org in the list.
      const fresh = orgs.find((o: any) => o.id === organisation?.id) ?? orgs[0]
      // Never downgrade onboarding_completed from true to false — the backend may
      // not have persisted the flag yet (race with markOnboardingComplete), and
      // overwriting with false would immediately kick the user back to /onboarding.
      const merged = (organisation?.onboarding_completed && !fresh.onboarding_completed)
        ? { ...fresh, onboarding_completed: true }
        : fresh
      setOrganisation(merged)
      api.defaults.headers.common['X-Organisation-ID'] = fresh.id
      setOrgListLoaded(true)
    }).catch(() => {
      // Non-fatal — use persisted org if available.
      // Always lift the gate so modules aren't stuck on a spinner if the
      // org-list request fails (e.g. cold-start timeout on Railway).
      setOrgListLoaded(true)
    })
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user?.id, online, _appRefreshTick])

  // Load the current user's role + module permissions from the API.
  // Superusers get owner-level access without an API call — they may not have a
  // membership in the currently selected org (which could belong to another user).
  // `online` is in deps so this retries when connectivity is restored after a
  // cold-start timeout (same reasoning as the org-list effect above).
  useEffect(() => {
    if (!organisation?.id) return
    if (user?.is_superuser) {
      setMembership('owner', {})
      // Superusers skip the membership API call so dispatch manually here —
      // useDataRefresh handlers on all pages need this event to re-fetch after
      // a cold-start recovery (when `online` toggled and re-ran this effect).
      window.dispatchEvent(new CustomEvent('audity:data-changed'))
      return
    }
    orgApi.myMembership(organisation.id).then(({ data }) => {
      // Guard: offline empty fallback returns { results: [] } — ignore it so we
      // don't overwrite a valid role or crash on undefined.module_permissions.
      if (!data?.role) return
      const perms: Partial<Record<ModuleKey, AccessLevel>> = {}
      ;((data.module_permissions ?? []) as ModulePermission[]).forEach((p) => {
        perms[p.module] = p.access_level
      })
      setMembership(data.role as string, perms)
      // Org + membership confirmed ready — tell every page to re-fetch its data.
      // This covers two cases:
      //   1. Cold-start recovery: `online` toggled true, this effect re-ran after a
      //      previous failure.  Pages that loaded with empty data now get fresh data.
      //   2. Normal first load: pages that mounted before membership resolved now
      //      get their initial data (second fetch is served from fresh cache, so cheap).
      window.dispatchEvent(new CustomEvent('audity:data-changed'))
    }).catch((err) => {
      // Only lock down to viewer on a real auth/permission error (HTTP response present)
      // AND only if no role has been loaded yet. Preserving an existing role (e.g. 'owner')
      // prevents a transient API error from stripping a user's access mid-session.
      // Network failures keep the last-known role so the app stays usable offline.
      const isNetworkErr = !err?.response
      const currentRole = useAuthStore.getState().memberRole
      if (!user?.is_superuser && !isNetworkErr && currentRole === null) {
        setMembership('viewer', {})
      }
    })
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [organisation?.id, setMembership, online, _appRefreshTick])

  // Load the active subscription plan's module list for sidebar gating.
  // Superusers bypass all plan restrictions (planModules stays null).
  // Also detect expired subscriptions and show the paywall.
  // `online` is in deps so this retries when connectivity is restored after a
  // cold-start timeout (same reasoning as the org-list effect above).
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
    }).catch((err) => {
      // Network error: keep existing plan state so plan-gated features stay accessible offline
      if (err?.response) { setPlanModules(null); setPlanTaxEngine(null); setPlanName(null) }
    })
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [organisation?.id, user?.is_superuser, setPlanModules, setPlanTaxEngine, setPlanName, setSubscriptionExpired, online, _appRefreshTick])

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
            <WifiOff size={13} className="shrink-0" />
            <span>
              You&apos;re offline.{' '}
              {cacheAge
                ? <>Showing cached data from <strong>{cacheAge}</strong>. </>
                : 'Cached data will appear as you navigate. '}
              New entries are queued and sync automatically when reconnected.
            </span>
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
          {/* Gate: hold child pages until org context is resolved so their
              initial fetches never fire with a null X-Organisation-ID header.
              This prevents the "Failed to load xyz" flash for superusers who
              have no personal orgs and must wait for orgApi.list() to pick
              orgs[0] as the active context.  Regular users always have
              organisation?.id set at login so orgListLoaded is initialised
              true and they see no spinner here. */}
          {(orgListLoaded || organisation?.id) ? (
            <Outlet />
          ) : (
            <div className="flex-1 flex items-center justify-center py-32">
              <div className="w-7 h-7 border-2 border-brand-500 border-t-transparent rounded-full animate-spin" />
            </div>
          )}
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

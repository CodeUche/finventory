import { create } from 'zustand'
import { persist, createJSONStorage } from 'zustand/middleware'
import type { User, AuthTokens, Organisation, AccessLevel, ModuleKey } from '@/types'

export const REMEMBER_FLAG_KEY = 'audity-remember-me'
// Purge any legacy plaintext password that may have been stored by older builds
localStorage.removeItem('audity-saved-creds')

// Media data URLs are stored in a SEPARATE key so they survive logout() and the
// startup guard in main.tsx (both wipe 'finventory-auth' but never this key).
const MEDIA_KEY = 'audity-media'
function readMediaCache(): { logoDataUrl?: string | null; stampDataUrl?: string | null; avatarDataUrl?: string | null } {
  try { return JSON.parse(localStorage.getItem(MEDIA_KEY) ?? '{}') } catch { return {} }
}
function writeMediaCache(patch: Partial<{ logoDataUrl: string | null; stampDataUrl: string | null; avatarDataUrl: string | null }>) {
  try {
    const cur = readMediaCache()
    const next: Record<string, string | null> = { ...cur }
    for (const [k, v] of Object.entries(patch)) {
      if (v == null) delete next[k]; else next[k] = v
    }
    localStorage.setItem(MEDIA_KEY, JSON.stringify(next))
  } catch { /* storage quota — skip */ }
}

interface AuthState {
  user: User | null
  tokens: AuthTokens | null
  organisation: Organisation | null
  organisations: Organisation[]
  isAuthenticated: boolean
  // True once finishLogin has completed the org fetch and committed state.
  // ProtectedRoute shows a spinner while false so it never redirects to
  // /onboarding based on a transient null organisation during login.
  orgInitialized: boolean
  rememberMe: boolean
  // Current user's role in the active organisation
  memberRole: string | null
  // module_key → access_level for non-admin users
  modulePermissions: Partial<Record<ModuleKey, AccessLevel>>
  // Modules allowed by the active subscription plan; null = no restriction
  planModules: string[] | null
  // Tax engine tier for the active plan: 'vat_only' | 'advanced' | null (null = unrestricted)
  planTaxEngine: string | null
  // Lowercase plan name: 'starter' | 'professional' | 'business' | null
  planName: string | null
  // Whether the current subscription is expired
  subscriptionExpired: boolean
  // Persisted base-64 data URLs for logo, stamp, and avatar — set when user uploads in Settings.
  // Avoids re-fetching from the server (which may be ephemeral on Railway without S3).
  logoDataUrl: string | null
  stampDataUrl: string | null
  avatarDataUrl: string | null

  // Atomic login commit — sets user, tokens, org, and isAuthenticated in a single
  // Zustand set() call so ProtectedRoute never sees isAuthenticated=true with
  // organisation=null (the race that caused the /onboarding redirect).
  initSession: (user: User, tokens: AuthTokens, org: Organisation | null, orgs: Organisation[]) => void
  setAuth: (user: User, tokens: AuthTokens) => void
  setOrganisation: (org: Organisation | null) => void
  setOrganisations: (orgs: Organisation[]) => void
  setRememberMe: (val: boolean) => void
  setMembership: (role: string, perms: Partial<Record<ModuleKey, AccessLevel>>) => void
  setPlanModules: (modules: string[] | null) => void
  setPlanTaxEngine: (engine: string | null) => void
  setPlanName: (name: string | null) => void
  setSubscriptionExpired: (expired: boolean) => void
  setLogoDataUrl: (url: string | null) => void
  setStampDataUrl: (url: string | null) => void
  setAvatarDataUrl: (url: string | null) => void
  updateUser: (user: Partial<User>) => void
  updateOrganisation: (org: Partial<Organisation>) => void
  updateTokens: (tokens: Partial<AuthTokens>) => void
  logout: () => void
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      user: null,
      tokens: null,
      organisation: null,
      organisations: [],
      isAuthenticated: false,
      orgInitialized: false,
      rememberMe: false,
      memberRole: null,
      modulePermissions: {},
      planModules: null,
      planTaxEngine: null,
      planName: null,
      subscriptionExpired: false,
      logoDataUrl: null,
      stampDataUrl: null,
      avatarDataUrl: null,

      setRememberMe: (val) => {
        if (val) localStorage.setItem(REMEMBER_FLAG_KEY, 'true')
        else localStorage.removeItem(REMEMBER_FLAG_KEY)
        set({ rememberMe: val })
      },

      // Atomic login commit: sets user, tokens, isAuthenticated, org, and
      // orgInitialized all in one set() call.  Zustand notifies subscribers
      // exactly once, so ProtectedRoute never sees the transient state where
      // isAuthenticated=true but organisation=null that caused /onboarding redirects.
      initSession: (user, tokens, org, orgs) => {
        const media = readMediaCache()
        set({
          user, tokens, isAuthenticated: true,
          organisation: org, organisations: orgs,
          orgInitialized: true,
          memberRole: null, modulePermissions: {},
          logoDataUrl: media.logoDataUrl ?? null,
          stampDataUrl: media.stampDataUrl ?? null,
          avatarDataUrl: media.avatarDataUrl ?? null,
        })
      },

      setAuth: (user, tokens) => {
        const media = readMediaCache()
        set({
          user, tokens, isAuthenticated: true,
          memberRole: null, modulePermissions: {},
          logoDataUrl: media.logoDataUrl ?? null,
          stampDataUrl: media.stampDataUrl ?? null,
          avatarDataUrl: media.avatarDataUrl ?? null,
        })
      },

      setOrganisation: (org) => {
        set({ organisation: org })
      },

      setOrganisations: (organisations) => set({ organisations }),

      setMembership: (role, perms) => set({ memberRole: role, modulePermissions: perms }),

      setPlanModules: (modules) => set({ planModules: modules }),

      setPlanTaxEngine: (engine) => set({ planTaxEngine: engine }),

      setPlanName: (name) => set({ planName: name }),

      setSubscriptionExpired: (expired) => set({ subscriptionExpired: expired }),

      setLogoDataUrl: (url) => { set({ logoDataUrl: url }); writeMediaCache({ logoDataUrl: url }) },
      setStampDataUrl: (url) => { set({ stampDataUrl: url }); writeMediaCache({ stampDataUrl: url }) },
      setAvatarDataUrl: (url) => { set({ avatarDataUrl: url }); writeMediaCache({ avatarDataUrl: url }) },

      updateUser: (partial) =>
        set((s) => ({ user: s.user ? { ...s.user, ...partial } : s.user })),

      updateOrganisation: (partial) =>
        set((s) => ({
          organisation: s.organisation ? { ...s.organisation, ...partial } : s.organisation,
        })),

      updateTokens: (partial) =>
        set((s) => {
          const updated = s.tokens ? { ...s.tokens, ...partial } : s.tokens
          return { tokens: updated }
        }),

      logout: () => {
        localStorage.removeItem(REMEMBER_FLAG_KEY)
        localStorage.removeItem('finventory-auth')
        sessionStorage.removeItem('finventory-auth') // belt-and-suspenders
        // Clear offline cache so the next user doesn't see stale org data
        import('@/lib/offlineCache').then(({ offlineCache }) => offlineCache.clearAll()).catch(() => {})
        // Clear PostHog identity so the next user starts a fresh session
        import('@/lib/analytics').then(({ resetAnalytics }) => resetAnalytics()).catch(() => {})
        set({
          user: null, tokens: null, organisation: null, isAuthenticated: false,
          orgInitialized: false,
          rememberMe: false, memberRole: null, modulePermissions: {}, planModules: null,
          planTaxEngine: null, planName: null, subscriptionExpired: false,
          logoDataUrl: null, stampDataUrl: null, avatarDataUrl: null,
        })
      },
    }),
    {
      name: 'finventory-auth',
      // Always use localStorage. The startup guard in main.tsx calls logout()
      // on every app launch, which clears this key before the first render.
      // Tauri/WebView2 does NOT reliably clear sessionStorage on process exit,
      // so using localStorage + explicit logout() is the only safe approach.
      storage: createJSONStorage(() => localStorage),
      partialize: (state) => ({
        // tokens intentionally excluded — kept in memory only.
        // main.tsx calls logout() on every launch which clears localStorage anyway,
        // so persisting tokens adds disk exposure with zero UX benefit.
        user: state.user,
        organisation: state.organisation,
        isAuthenticated: state.isAuthenticated,
        rememberMe: state.rememberMe,
        memberRole: state.memberRole,
        modulePermissions: state.modulePermissions,
        planModules: state.planModules,
        planTaxEngine: state.planTaxEngine,
        planName: state.planName,
        subscriptionExpired: state.subscriptionExpired,
        logoDataUrl: state.logoDataUrl,
        stampDataUrl: state.stampDataUrl,
        avatarDataUrl: state.avatarDataUrl,
      }),
    },
  ),
)

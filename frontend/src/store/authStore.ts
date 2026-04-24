import { create } from 'zustand'
import { persist, createJSONStorage } from 'zustand/middleware'
import type { User, AuthTokens, Organisation, AccessLevel, ModuleKey } from '@/types'

export const REMEMBER_FLAG_KEY = 'audity-remember-me'
// Purge any legacy plaintext password that may have been stored by older builds
localStorage.removeItem('audity-saved-creds')

interface AuthState {
  user: User | null
  tokens: AuthTokens | null
  organisation: Organisation | null
  organisations: Organisation[]
  isAuthenticated: boolean
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

  setAuth: (user: User, tokens: AuthTokens) => void
  setOrganisation: (org: Organisation | null) => void
  setOrganisations: (orgs: Organisation[]) => void
  setRememberMe: (val: boolean) => void
  setMembership: (role: string, perms: Partial<Record<ModuleKey, AccessLevel>>) => void
  setPlanModules: (modules: string[] | null) => void
  setPlanTaxEngine: (engine: string | null) => void
  setPlanName: (name: string | null) => void
  setSubscriptionExpired: (expired: boolean) => void
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
      rememberMe: false,
      memberRole: null,
      modulePermissions: {},
      planModules: null,
      planTaxEngine: null,
      planName: null,
      subscriptionExpired: false,

      setRememberMe: (val) => {
        if (val) localStorage.setItem(REMEMBER_FLAG_KEY, 'true')
        else localStorage.removeItem(REMEMBER_FLAG_KEY)
        set({ rememberMe: val })
      },

      setAuth: (user, tokens) => {
        // Clear stale membership from any previous session so the next myMembership load starts clean
        set({ user, tokens, isAuthenticated: true, memberRole: null, modulePermissions: {} })
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
        set({
          user: null, tokens: null, organisation: null, isAuthenticated: false,
          rememberMe: false, memberRole: null, modulePermissions: {}, planModules: null,
          planTaxEngine: null, planName: null, subscriptionExpired: false,
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
      }),
    },
  ),
)

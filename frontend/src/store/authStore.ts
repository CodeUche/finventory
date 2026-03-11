import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { User, AuthTokens, Organisation, AccessLevel, ModuleKey } from '@/types'

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

  setAuth: (user: User, tokens: AuthTokens) => void
  setOrganisation: (org: Organisation) => void
  setOrganisations: (orgs: Organisation[]) => void
  setRememberMe: (val: boolean) => void
  setMembership: (role: string, perms: Partial<Record<ModuleKey, AccessLevel>>) => void
  updateUser: (user: Partial<User>) => void
  updateOrganisation: (org: Partial<Organisation>) => void
  updateTokens: (tokens: Partial<AuthTokens>) => void
  logout: () => void
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      user: null,
      tokens: null,
      organisation: null,
      organisations: [],
      isAuthenticated: false,
      rememberMe: false,
      memberRole: null,
      modulePermissions: {},

      setRememberMe: (val) => set({ rememberMe: val }),

      setAuth: (user, tokens) => {
        const storage = get().rememberMe ? localStorage : sessionStorage
        storage.setItem('auth', JSON.stringify(tokens))
        set({ user, tokens, isAuthenticated: true })
      },

      setOrganisation: (org) => {
        const storage = get().rememberMe ? localStorage : sessionStorage
        storage.setItem('org_id', org.id)
        set({ organisation: org })
      },

      setOrganisations: (organisations) => set({ organisations }),

      setMembership: (role, perms) => set({ memberRole: role, modulePermissions: perms }),

      updateUser: (partial) =>
        set((s) => ({ user: s.user ? { ...s.user, ...partial } : s.user })),

      updateOrganisation: (partial) =>
        set((s) => ({
          organisation: s.organisation ? { ...s.organisation, ...partial } : s.organisation,
        })),

      updateTokens: (partial) =>
        set((s) => {
          const updated = s.tokens ? { ...s.tokens, ...partial } : s.tokens
          const storage = s.rememberMe ? localStorage : sessionStorage
          if (updated) storage.setItem('auth', JSON.stringify(updated))
          return { tokens: updated }
        }),

      logout: () => {
        localStorage.removeItem('auth')
        localStorage.removeItem('org_id')
        sessionStorage.removeItem('auth')
        sessionStorage.removeItem('org_id')
        set({
          user: null, tokens: null, organisation: null, isAuthenticated: false,
          memberRole: null, modulePermissions: {},
        })
      },
    }),
    {
      name: 'finventory-auth',
      partialize: (state) => ({
        user: state.user,
        tokens: state.tokens,
        organisation: state.organisation,
        isAuthenticated: state.isAuthenticated,
        rememberMe: state.rememberMe,
        memberRole: state.memberRole,
        modulePermissions: state.modulePermissions,
      }),
    },
  ),
)

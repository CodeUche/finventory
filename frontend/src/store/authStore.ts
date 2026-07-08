import { create } from 'zustand'
import { persist, createJSONStorage } from 'zustand/middleware'
import type { User, AuthTokens, Organisation, AccessLevel, ModuleKey } from '@/types'
import type { OfflineVerifierBlob } from '@/lib/offlineVerifier'

export const REMEMBER_FLAG_KEY = 'audity-remember-me'
// Purge any legacy plaintext password that may have been stored by older builds
localStorage.removeItem('audity-saved-creds')

// Media data URLs are stored in a SEPARATE key so they survive logout() and the
// startup guard in main.tsx (both wipe 'finventory-auth' but never this key).
//
// SECURITY: keys are scoped PER ORGANISATION. The old unscoped 'audity-media'
// key leaked the previous org's logo/stamp/avatar to the next user who logged
// in on the same machine (and the stamp could land on their generated PDFs).
const LEGACY_MEDIA_KEY = 'audity-media'
const mediaKey = (orgId: string) => `audity-media:${orgId}`

type MediaCache = { logoDataUrl?: string | null; stampDataUrl?: string | null; avatarDataUrl?: string | null }

function readMediaCache(orgId: string | null | undefined): MediaCache {
  if (!orgId) return {}
  try {
    const scoped = localStorage.getItem(mediaKey(orgId))
    if (scoped) return JSON.parse(scoped)
    // One-time migration: adopt the legacy unscoped blob for the first org that
    // logs in after this build, then delete it so it can never leak cross-org.
    // (Pre-migration builds had a single org per machine in practice.)
    const legacy = localStorage.getItem(LEGACY_MEDIA_KEY)
    if (legacy) {
      localStorage.setItem(mediaKey(orgId), legacy)
      localStorage.removeItem(LEGACY_MEDIA_KEY)
      return JSON.parse(legacy)
    }
    return {}
  } catch { return {} }
}
function writeMediaCache(orgId: string | null | undefined, patch: Partial<{ logoDataUrl: string | null; stampDataUrl: string | null; avatarDataUrl: string | null }>) {
  if (!orgId) return
  try {
    const cur = readMediaCache(orgId)
    const next: Record<string, string | null> = { ...cur }
    for (const [k, v] of Object.entries(patch)) {
      if (v == null) delete next[k]; else next[k] = v
    }
    localStorage.setItem(mediaKey(orgId), JSON.stringify(next))
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
  // True when the backend flagged this request as a superuser viewing an org
  // they aren't a member of — never persisted, recomputed from live responses.
  supportAccess: boolean
  // True when authenticated via offline PBKDF2 verifier, not real JWTs.
  // The session has no access tokens; all API writes are queued.
  isOfflineSession: boolean
  // Persisted base-64 data URLs for logo, stamp, and avatar — set when user uploads in Settings.
  // Avoids re-fetching from the server (which may be ephemeral on Railway without S3).
  logoDataUrl: string | null
  stampDataUrl: string | null
  avatarDataUrl: string | null

  // Atomic login commit — sets user, tokens, org, and isAuthenticated in a single
  // Zustand set() call so ProtectedRoute never sees isAuthenticated=true with
  // organisation=null (the race that caused the /onboarding redirect).
  initSession: (user: User, tokens: AuthTokens, org: Organisation | null, orgs: Organisation[]) => void
  startOfflineSession: (blob: OfflineVerifierBlob) => void
  setAuth: (user: User, tokens: AuthTokens) => void
  setOrganisation: (org: Organisation | null) => void
  setOrganisations: (orgs: Organisation[]) => void
  setRememberMe: (val: boolean) => void
  setMembership: (role: string, perms: Partial<Record<ModuleKey, AccessLevel>>) => void
  setPlanModules: (modules: string[] | null) => void
  setPlanTaxEngine: (engine: string | null) => void
  setPlanName: (name: string | null) => void
  setSubscriptionExpired: (expired: boolean) => void
  setSupportAccess: (active: boolean) => void
  setLogoDataUrl: (url: string | null) => void
  setStampDataUrl: (url: string | null) => void
  setAvatarDataUrl: (url: string | null) => void
  updateUser: (user: Partial<User>) => void
  updateOrganisation: (org: Partial<Organisation>) => void
  updateTokens: (tokens: Partial<AuthTokens>) => void
  // Ends the auth session but PRESERVES offline capability: the encrypted
  // offline verifier, the offline read cache, and queued mutations all survive.
  // For the startup guard, session expiry, and the inactivity lock — the device
  // owner hasn't changed, they just need to re-authenticate (online OR offline).
  clearSession: () => void
  // Full logout: clearSession + wipes the offline verifier (local + server),
  // the offline cache, and analytics identity. Only for the explicit
  // user-initiated "Log out" action — after this, offline unlock is impossible
  // until the next online login.
  logout: () => void
}

// State reset shared by clearSession() and logout().
const CLEARED_SESSION_STATE = {
  user: null, tokens: null, organisation: null, isAuthenticated: false,
  orgInitialized: false, isOfflineSession: false,
  rememberMe: false, memberRole: null, modulePermissions: {}, planModules: null,
  planTaxEngine: null, planName: null, subscriptionExpired: false,
  logoDataUrl: null, stampDataUrl: null, avatarDataUrl: null,
  supportAccess: false,
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
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
      supportAccess: false,
      isOfflineSession: false,

      setRememberMe: (val) => {
        if (val) localStorage.setItem(REMEMBER_FLAG_KEY, 'true')
        else localStorage.removeItem(REMEMBER_FLAG_KEY)
        set({ rememberMe: val })
      },
      setSupportAccess: (active) => set((s) => s.supportAccess === active ? s : { supportAccess: active }),

      // Atomic login commit: sets user, tokens, isAuthenticated, org, and
      // orgInitialized all in one set() call.  Zustand notifies subscribers
      // exactly once, so ProtectedRoute never sees the transient state where
      // isAuthenticated=true but organisation=null that caused /onboarding redirects.
      initSession: (user, tokens, org, orgs) => {
        const media = readMediaCache(org?.id)
        set({
          user, tokens, isAuthenticated: true,
          // A real-token login always ends any offline grace session — without
          // this, the api layer would keep queueing mutations after re-login.
          isOfflineSession: false,
          organisation: org, organisations: orgs,
          orgInitialized: true,
          memberRole: null, modulePermissions: {},
          logoDataUrl: media.logoDataUrl ?? null,
          stampDataUrl: media.stampDataUrl ?? null,
          avatarDataUrl: media.avatarDataUrl ?? null,
        })
      },

      // Offline grace session: authenticated via PBKDF2 verifier, no real JWTs.
      // Restores org context AND the user's identity + RBAC from the verifier
      // snapshot so the sidebar renders correctly for EVERY user type with no
      // network. (Blobs issued before the identity-snapshot change omit these
      // fields; the sidebar then fills in from its online fetch on reconnect.)
      // All API writes are queued; reads come from offlineCache.
      startOfflineSession: (blob) => {
        const firstOrg = blob.organisations[0] ?? null
        const media    = readMediaCache(firstOrg?.id ?? null)
        const isSuper  = blob.is_superuser === true

        // Map the active org's module_permissions list → { module: level }.
        const perms: Partial<Record<ModuleKey, AccessLevel>> = {}
        for (const p of firstOrg?.module_permissions ?? []) {
          perms[p.module as ModuleKey] = p.access_level as AccessLevel
        }
        // Superusers and owners/admins are unrestricted (mirrors online logic).
        const role = firstOrg?.role ?? (isSuper ? 'owner' : null)

        set({
          isAuthenticated: true,
          isOfflineSession: true,
          orgInitialized: true,
          user: {
            id: blob.user_id,
            email: blob.email,
            first_name: blob.first_name ?? '',
            last_name: blob.last_name ?? '',
            phone: blob.phone ?? '',
            is_verified: true,
            is_superuser: isSuper,
            is_staff: blob.is_staff === true,
            is_sub_account: blob.is_sub_account === true,
            has_partner_profile: blob.has_partner_profile === true,
            mfa_enabled: blob.mfa_enabled,
          } as User,
          tokens: null,
          organisation: firstOrg as Organisation | null,
          organisations: blob.organisations as Organisation[],
          memberRole: role,
          modulePermissions: perms,
          // Superusers are never plan-restricted (planModules stays null).
          planModules: isSuper ? null : (firstOrg?.plan_modules ?? null),
          planTaxEngine: firstOrg?.plan_tax_engine ?? null,
          planName: firstOrg?.plan_name ?? null,
          subscriptionExpired: firstOrg?.subscription_expired ?? false,
          logoDataUrl: media.logoDataUrl ?? null,
          stampDataUrl: media.stampDataUrl ?? null,
          avatarDataUrl: media.avatarDataUrl ?? null,
        })
      },

      setAuth: (user, tokens) => {
        // No org context here — media loads in initSession/setOrganisation,
        // which know WHICH org's cached media is safe to show.
        set({
          user, tokens, isAuthenticated: true, isOfflineSession: false,
          memberRole: null, modulePermissions: {},
        })
      },

      setOrganisation: (org) => {
        // Load the media cached for THIS org (never another org's).
        const media = readMediaCache(org?.id)
        set({
          organisation: org,
          logoDataUrl: media.logoDataUrl ?? null,
          stampDataUrl: media.stampDataUrl ?? null,
          avatarDataUrl: media.avatarDataUrl ?? null,
        })
      },

      setOrganisations: (organisations) => set({ organisations }),

      setMembership: (role, perms) => set({ memberRole: role, modulePermissions: perms }),

      setPlanModules: (modules) => set({ planModules: modules }),

      setPlanTaxEngine: (engine) => set({ planTaxEngine: engine }),

      setPlanName: (name) => set({ planName: name }),

      setSubscriptionExpired: (expired) => set({ subscriptionExpired: expired }),

      setLogoDataUrl: (url) => { set({ logoDataUrl: url }); writeMediaCache(get().organisation?.id, { logoDataUrl: url }) },
      setStampDataUrl: (url) => { set({ stampDataUrl: url }); writeMediaCache(get().organisation?.id, { stampDataUrl: url }) },
      setAvatarDataUrl: (url) => { set({ avatarDataUrl: url }); writeMediaCache(get().organisation?.id, { avatarDataUrl: url }) },

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

      clearSession: () => {
        localStorage.removeItem(REMEMBER_FLAG_KEY)
        localStorage.removeItem('finventory-auth')
        sessionStorage.removeItem('finventory-auth') // belt-and-suspenders
        // Deliberately KEEPS on disk: the encrypted offline verifier (so the
        // user can unlock offline), the password-wrapped refresh token (so an
        // unlocked session can silently resume), the offline read cache, and
        // the sync queue (queued sales must never be lost). This is the whole
        // offline-first contract. In-MEMORY secrets do get dropped — the next
        // session must re-derive them from the typed password.
        import('@/lib/offlineResume').then(({ clearResumeMemory }) => clearResumeMemory()).catch(() => {})
        set({ ...CLEARED_SESSION_STATE })
      },

      logout: () => {
        localStorage.removeItem(REMEMBER_FLAG_KEY)
        localStorage.removeItem('finventory-auth')
        sessionStorage.removeItem('finventory-auth') // belt-and-suspenders
        // Wipe offline verifier blob so no offline login is possible after logout.
        // deleteVerifier also removes the password-wrapped refresh token blob.
        // Also attempt server-side revocation (best-effort — non-fatal if offline).
        import('@/lib/offlineVerifier').then(async ({ deleteVerifier }) => {
          await deleteVerifier()
          try {
            const { authApi } = await import('@/services/api')
            await authApi.revokeOfflineVerifier()
          } catch { /* non-fatal: server will expire it in 14 days */ }
        }).catch(() => {})
        // Drop the in-memory resume secrets (wrap key + decrypted refresh token)
        import('@/lib/offlineResume').then(({ clearResumeMemory }) => clearResumeMemory()).catch(() => {})
        // Clear offline cache so the next user doesn't see stale org data.
        // The sync queue is NOT wiped — queued sales are real business data.
        // flush() is org-scoped, so another user logging in can never replay
        // this org's queue into their own tenant.
        import('@/lib/offlineCache').then(({ offlineCache }) => offlineCache.clearAll()).catch(() => {})
        // Clear PostHog identity so the next user starts a fresh session
        import('@/lib/analytics').then(({ resetAnalytics }) => resetAnalytics()).catch(() => {})
        set({ ...CLEARED_SESSION_STATE })
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

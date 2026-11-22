import { useAuthStore } from '@/store/authStore'
import { FEATURES } from '@/lib/featureFlags'
import type { ModuleKey } from '@/types'

/**
 * Whether a navigation item should be shown to the signed-in user.
 * One source of truth for the sidebar and the hub pages, so a hub never links
 * to something the sidebar hides (plan gating, sub-account permissions, owner-only,
 * partner-only and business-type rules).
 */
export function useCanSeeNavItem() {
  const { user, organisation, memberRole, modulePermissions, planModules, planName } = useAuthStore()
  const isOwnerOrAdmin = user?.is_superuser === true || memberRole === 'owner' || memberRole === 'admin'

  // Returns true if the nav item should be visible.
  // Checks: ownerOnly → plan modules → sub-account RBAC permissions
  const canSeeItem = (mod?: ModuleKey, ownerOnly?: boolean, partnerOnly?: boolean, businessType?: string) => {
    const membershipLoading = memberRole === null && !user?.is_superuser
    if (partnerOnly && (!FEATURES.PARTNER_CHANNEL || !user?.has_partner_profile)) return false
    if (partnerOnly && !user?.is_superuser && !planName?.startsWith('partner')) return false
    // Business-type gate (e.g. restaurant-only POS): hide once the org's type is known
    // and differs. Fail-open while the org type is still loading.
    const orgBusinessType = (organisation as { business_type?: string } | null)?.business_type
    if (businessType && orgBusinessType && orgBusinessType !== businessType) return false
    // Owner-only items (Billing & Plans, Connectors, Tickets...) have no module,
    // so this test must run before the "no module" early return below.
    if (ownerOnly && !isOwnerOrAdmin && !user?.is_superuser) return false
    if (!mod) return true                             // no module restriction (dashboard, settings)
    if (user?.is_superuser) return true              // superusers always see everything
    // Plan-level gate: if the active plan restricts modules, only show allowed ones
    if (planModules !== null && !planModules.includes(mod)) return false
    // While membership is loading, hide all module items — sub-accounts must not see
    // modules they have no access to, even briefly.
    if (membershipLoading) return false
    if (ownerOnly && !isOwnerOrAdmin) return false   // explicitly owner-only items
    if (isOwnerOrAdmin) return true                   // owners/admins see all plan-allowed modules
    const level = modulePermissions?.[mod]
    return level === 'view' || level === 'write' || level === 'edit'
  }
  return { canSeeItem, isOwnerOrAdmin }
}

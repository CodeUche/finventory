/**
 * useModuleAccess — per-module permission helper.
 *
 * Owners and admins always receive full access.
 * All other roles are governed by the ModulePermission records
 * set by the admin, which are loaded into the auth store at login.
 *
 * Usage:
 *   const { canView, canWrite, canEdit } = useModuleAccess('sales')
 *   if (!canView) return null
 *   ...
 *   {canEdit && <button>Delete</button>}
 */

import { useAuthStore } from '@/store/authStore'
import type { AccessLevel, ModuleKey } from '@/types'

const FULL = { canView: true, canWrite: true, canEdit: true, accessLevel: 'edit' as AccessLevel }
const NONE = { canView: false, canWrite: false, canEdit: false, accessLevel: 'none' as AccessLevel }

export function useModuleAccess(module: ModuleKey) {
  const { memberRole, modulePermissions, user } = useAuthStore()

  // Platform superusers and org owners/admins always have unrestricted access
  // null memberRole = membership still loading; treat as no access until confirmed
  if (user?.is_superuser || memberRole === 'owner' || memberRole === 'admin') {
    return FULL
  }

  // No explicit permission record = no access (restrictive default for sub-accounts)
  const level: AccessLevel = modulePermissions[module] ?? 'none'

  switch (level) {
    case 'none':
      return NONE
    case 'view':
      return { canView: true, canWrite: false, canEdit: false, accessLevel: level }
    case 'write':
      return { canView: true, canWrite: true, canEdit: false, accessLevel: level }
    case 'edit':
    default:
      return FULL
  }
}

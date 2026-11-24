/**
 * useReportNeeds - answers "may this person open a screen that needs X?" for the Reports home.
 *
 * Module needs use the same rule as the sidebar (plan gate + Team permission tick). The figure
 * flags come from useReportAccess, which mirrors what the server allows. "owner" is the
 * owner-only Owner Analytics screen.
 */
import { useCanSeeNavItem } from '@/lib/navAccess'
import { useReportAccess } from '@/hooks/useReportAccess'
import type { Need } from '@/lib/reportGroups'
import type { ModuleKey } from '@/types'

const FLAGS = ['profitLoss', 'arAging', 'apAging', 'expenseBreakdown', 'customerBalance', 'inventoryValuation'] as const

export function useReportNeeds(): (need: Need) => boolean {
  const { canSeeItem, isOwnerOrAdmin } = useCanSeeNavItem()
  const access = useReportAccess()
  return (need: Need) => {
    if (need === 'owner') return isOwnerOrAdmin && canSeeItem('owner_analytics')
    if ((FLAGS as readonly string[]).includes(need)) return access[need as (typeof FLAGS)[number]]
    return canSeeItem(need as ModuleKey)
  }
}

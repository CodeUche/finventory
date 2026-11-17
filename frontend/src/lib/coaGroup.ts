import type { AccountTaxonomyGroup } from '@/types'

/**
 * Which "Account Type" group an existing account belongs to, for the Edit Account pop-up.
 * Older accounts can have an empty account_group, which left the type box on
 * "Select type..." and locked the Sub Type box. We then look at the saved sub type,
 * and last, at the base type (only when exactly one group has that base type).
 */
export function resolveAccountGroup(
  taxonomy: AccountTaxonomyGroup[],
  acct: { account_group?: string | null; sub_type?: string | null; account_type: string },
): string {
  const saved = acct.account_group ?? ''
  if (saved && taxonomy.some((g) => g.group === saved)) return saved
  if (acct.sub_type) {
    const bySub = taxonomy.find((g) => g.sub_types.some((s) => s.id === acct.sub_type))
    if (bySub) return bySub.group
  }
  const byBase = taxonomy.filter((g) => g.base_account_type === acct.account_type)
  return byBase.length === 1 ? byBase[0].group : ''
}

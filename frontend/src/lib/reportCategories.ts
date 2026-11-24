/**
 * The shape of one entry in the backend report catalog (GET /reports/catalog/, built from
 * backend/apps/reports/registry.py). `category` is the registry's own grouping; the Reports home
 * groups reports by business question instead (see lib/reportGroups.ts).
 */
export interface CatalogEntry {
  key: string
  label: string
  category: string
  description: string
  needs_period: boolean
}

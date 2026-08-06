import { useEffect, useState } from 'react'
import { reportApi } from '@/services/api'
import type { CatalogEntry } from '@/lib/reportCategories'

/**
 * Fetches the report registry catalog (GET /reports/catalog/) once on mount.
 *
 * Used by the Sidebar's nested "GENERAL REPORTS" tree so it always reflects
 * whatever reports are actually registered in backend/apps/reports/registry.py
 * — no separate hardcoded list to keep in sync by hand. AllReportsPage.tsx
 * fetches the same endpoint itself (it also needs to re-run it after a
 * refresh action), so the two calls are independent and cheap (a small,
 * mostly-static JSON list) rather than sharing a cache.
 */
export function useReportCatalog() {
  const [catalog, setCatalog] = useState<CatalogEntry[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    reportApi.catalog()
      .then(({ data }) => { if (!cancelled) setCatalog(data?.reports ?? []) })
      .catch(() => { /* sidebar silently falls back to an empty tree — the main Reports page surfaces the real error */ })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [])

  return { catalog, loading }
}

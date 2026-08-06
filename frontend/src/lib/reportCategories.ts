/**
 * Shared report-catalog category order + icons.
 *
 * Used by both frontend/src/pages/reports/AllReportsPage.tsx (the report
 * tree/viewer) and frontend/src/components/layout/Sidebar.tsx (the sidebar's
 * nested "GENERAL REPORTS" menu), so the two trees always show reports in the
 * same grouping — pulled out to one file specifically so editing one doesn't
 * silently drift out of sync with the other. Category names here must match
 * the `category` string each ReportDef is registered with in
 * backend/apps/reports/registry.py exactly (case-sensitive).
 */
import {
  BarChart3, BookOpen, Boxes, FileSpreadsheet, Landmark, Users, UsersRound, Wallet,
} from 'lucide-react'

export interface CatalogEntry {
  key: string
  label: string
  category: string
  description: string
  needs_period: boolean
}

export const CATEGORY_ORDER: { name: string; icon: React.ElementType }[] = [
  { name: 'Financial Statements', icon: BarChart3 },
  { name: 'General Ledger',       icon: BookOpen },
  { name: 'Accounts Receivable',  icon: Users },
  { name: 'Accounts Payable',     icon: Wallet },
  { name: 'Inventory',            icon: Boxes },
  { name: 'Fixed Assets',         icon: Landmark },
  { name: 'Payroll & HR',         icon: UsersRound },
  { name: 'Accountant Reports',   icon: FileSpreadsheet },
]

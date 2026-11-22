/**
 * Hub pages — one landing page of big tiles per sidebar group, as in the
 * designer's screens ("Accounting", "Inventory", "HR", ...). The title and the
 * tiles come from the sidebar's own groups, so names and permissions always
 * match the menu. `label` is the navGroups key.
 */
export interface HubDef { slug: string; label: string; title: string; blurb: string }

export const HUBS: HubDef[] = [
  { slug: 'accounting',  label: 'ACCOUNTING & FINANCE', title: 'Accounting',  blurb: 'Your books: accounts, journals, budgets, assets and reconciliation.' },
  { slug: 'customers',   label: 'CUSTOMERS & RECEIPTS', title: 'Customers & Receipts',  blurb: 'Customers, receipts, transfers and card settlements.' },
  { slug: 'sales-pos',   label: 'SALES & POS',          title: 'Sales & POS',           blurb: 'Quotes, invoices, the register, POS orders and your storefront.' },
  { slug: 'procurement', label: 'PROCUREMENT',          title: 'Procurement',           blurb: 'Suppliers, purchase orders, returns and bills.' },
  { slug: 'inventory',   label: 'INVENTORY',            title: 'Inventory',             blurb: 'Products, stock levels, warehouses and batches.' },
  { slug: 'hr',          label: 'HR',                   title: 'HR',                    blurb: 'Employees, leave, payroll, compliance and analytics.' },
]

export const HUB_FOR_GROUP: Record<string, HubDef> = Object.fromEntries(HUBS.map((h) => [h.label, h]))
export const hubBySlug = (slug?: string) => HUBS.find((h) => h.slug === slug)

/**
 * The designer's tile wording and order for each hub. Keyed by the page's route
 * (so it always follows the same permissions as the menu). A page the designer
 * has not drawn (for example "New Sale / Invoice") keeps its menu name and is
 * listed after the drawn ones.
 */
export const HUB_TILES: Record<string, { href: string; label: string }[]> = {
  accounting: [
    { href: '/accounting/coa', label: 'Chart Of Accounts' },
    { href: '/budgets', label: 'Budget' },
    { href: '/accounting/beginning-balances', label: 'Beginning Balances' },
    { href: '/accounting/assets', label: 'Fixed Asset' },
    { href: '/accounting/journal', label: 'Journal Entries' },
    { href: '/accounting/reconciliation', label: 'Bank Reconciliation' },
    { href: '/budgets/periods', label: 'Budget Period' },
    { href: '/budgets/allocations', label: 'Budget Allocation' },
    { href: '/accounting/gl-health', label: 'GL Health' },
  ],
  'sales-pos': [
    { href: '/quotes', label: 'Quotes' },
    { href: '/sales', label: 'Invoices' },
    { href: '/sales/returns', label: 'Sales Return' },
    { href: '/recurring', label: 'Recurring Invoices' },
    { href: '/pos/register', label: 'Register (Till)' },
    { href: '/pos/restaurant', label: 'POS Orders' },
    { href: '/pos/till', label: 'Till/Cash Up' },
    { href: '/storefront', label: 'Storefront' },
    { href: '/locations', label: 'Locations' },
  ],
  hr: [
    { href: '/hr/employees', label: 'Employees' },
    { href: '/hr/org-chart', label: 'Org Chart' },
    { href: '/hr/leave', label: 'Leave' },
    { href: '/hr/runs', label: 'Payroll Run' },
    { href: '/hr/compliance', label: 'Compliance & Remittance' },
    { href: '/hr/analytics', label: 'HR Analytics' },
  ],
}

/**
 * Hub pages — one landing page of big tiles per sidebar group, as in the
 * designer's screens ("Accounting", "Inventory", "HR", ...). The title and the
 * tiles come from the sidebar's own groups, so names and permissions always
 * match the menu. `label` is the navGroups key.
 */
export interface HubDef { slug: string; label: string; title: string; blurb: string }

export const HUBS: HubDef[] = [
  { slug: 'accounting',  label: 'ACCOUNTING & FINANCE', title: 'Accounting & Finance',  blurb: 'Your books: accounts, journals, budgets, assets and reconciliation.' },
  { slug: 'customers',   label: 'CUSTOMERS & RECEIPTS', title: 'Customers & Receipts',  blurb: 'Customers, receipts, transfers and card settlements.' },
  { slug: 'sales-pos',   label: 'SALES & POS',          title: 'Sales & POS',           blurb: 'Quotes, invoices, the register, POS orders and your storefront.' },
  { slug: 'procurement', label: 'PROCUREMENT',          title: 'Procurement',           blurb: 'Suppliers, purchase orders, returns and bills.' },
  { slug: 'inventory',   label: 'INVENTORY',            title: 'Inventory',             blurb: 'Products, stock levels, warehouses and batches.' },
  { slug: 'hr',          label: 'HR',                   title: 'HR',                    blurb: 'Employees, leave, payroll, compliance and analytics.' },
]

export const HUB_FOR_GROUP: Record<string, HubDef> = Object.fromEntries(HUBS.map((h) => [h.label, h]))
export const hubBySlug = (slug?: string) => HUBS.find((h) => h.slug === slug)

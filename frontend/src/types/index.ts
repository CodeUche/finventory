// ─── Auth ─────────────────────────────────────────────────────────────────────
export interface User {
  id: string
  email: string
  first_name: string
  last_name: string
  phone: string
  is_verified: boolean
  is_superuser?: boolean
  is_staff?: boolean
  is_sub_account?: boolean
  mfa_enabled?: boolean
  has_partner_profile?: boolean
  avatar?: string
}

export interface AuthTokens {
  access: string
  refresh: string
}

// ─── Organisation ──────────────────────────────────────────────────────────────
export interface Organisation {
  id: string
  name: string
  slug: string
  account_type: 'personal' | 'business'
  country: string
  currency: string
  phone: string
  email: string
  address?: string
  logo?: string
  company_stamp?: string
  tax_id?: string
  registration_number?: string
  is_active: boolean
  onboarding_completed: boolean
  bank_name?: string
  bank_account_number?: string
  bank_account_name?: string
  bank_sort_code?: string
  brand_color?: string
  invoice_company_name?: string
  company_name_font?: string
  company_name_font_color?: string
  company_name_font_size?: number
  company_name_font_bold?: boolean
  company_name_font_italic?: boolean
  company_name_font_underline?: boolean
  show_company_name_on_pdf?: boolean
  invoice_template?: string
  pension_provider?: string
  ai_custom_context?: string
  managing_firm_name?: string | null
  managing_firm_logo?: string | null
}

// ─── Product ──────────────────────────────────────────────────────────────────
export interface Product {
  id: string
  sku: string
  name: string
  brand: string
  category: string | null
  category_name: string | null
  unit_of_measure: string
  product_type?: 'physical' | 'service' | 'digital'
  alcohol_percentage?: number
  volume_ml?: number
  cost_price: string
  owner_cost_price?: string
  selling_price: string
  reorder_level: number
  is_active: boolean
  is_taxable: boolean
  tax_class: string | null
  total_stock: number
}

export interface StockItem {
  id: string
  product: string
  product_name: string
  product_sku: string
  warehouse: string
  warehouse_name: string
  quantity_on_hand: string
  quantity_available: string
  is_low_stock: boolean
  stock_level?: 'low' | 'medium' | 'ok'
}

// ─── Customer ─────────────────────────────────────────────────────────────────
export interface Customer {
  id: string
  code: string
  name: string
  customer_type: 'retail' | 'wholesale' | 'distributor'
  email: string
  phone: string
  address?: string
  credit_limit: string
  outstanding_balance: string
  store_credit: string
  available_credit: string
  is_credit_blocked: boolean
  credit_score?: number
  is_active: boolean
}

// ─── Invoice ──────────────────────────────────────────────────────────────────
export interface SalePayment {
  id: string
  amount: string
  method: string
  reference: string
  notes: string
  received_at: string
}

export interface Invoice {
  id: string
  invoice_number: string
  customer: string | null
  customer_name: string | null
  status: 'draft' | 'proforma' | 'confirmed' | 'paid' | 'partially_paid' | 'overdue' | 'voided' | 'credit' | 'returned'
  payment_method: string
  issue_date: string
  due_date?: string
  subtotal: string
  discount_amount: string
  tax_amount: string
  total_amount: string
  credit_applied: string
  amount_paid: string
  amount_due: string
  notes: string
  sold_by?: string
  items: SaleItem[]
  payments: SalePayment[]
  created_at: string
}

export interface SaleItem {
  id: string
  product: string
  product_name: string
  product_sku: string
  quantity: string
  quantity_returned: string
  unit_price: string
  line_total: string
}

// ─── Warehouse ────────────────────────────────────────────────────────────────
export interface Warehouse {
  id: string
  name: string
  address: string
  is_default: boolean
  is_active: boolean
}

export interface OwnerAnalytics {
  period: string
  total_revenue: string
  company_cogs: string
  owner_cogs: string
  company_gross_profit: string
  owner_gross_profit: string
  company_margin_pct: string
  owner_margin_pct: string
  top_products: { product_name: string; revenue: string; company_gross: string; owner_gross: string }[]
}

export interface WarehouseSalesRow {
  warehouse_id: string
  warehouse_name: string
  total_revenue: string
  invoice_count: number
  top_products: { product_name: string; units_sold: string; revenue: string }[]
}

// ─── Expense ──────────────────────────────────────────────────────────────────
export interface Expense {
  id: string
  category: string
  category_name: string
  amount: string
  previous_price?: string | null
  is_income: boolean
  description: string
  expense_date: string
  payment_method: string
  attachment?: string
  group?: string | null
  group_name?: string | null
}

export interface ExpenseGroup {
  id: string
  name: string
  description: string
  group_date: string | null
  parent: string | null
  parent_name: string | null
  ancestors: { id: string; name: string }[]
  children_count: number
  expense_count: number
  total_amount: string
  created_at: string
}

// ─── Credits ──────────────────────────────────────────────────────────────────
export interface CreditTransaction {
  id: string
  customer: string
  customer_name: string
  transaction_type: 'debit' | 'credit' | 'adjustment' | 'write_off'
  amount: string
  balance_after: string
  due_date: string | null
  description: string
  created_at: string
}

// ─── Purchases ────────────────────────────────────────────────────────────────
export interface PurchaseOrder {
  id: string
  po_number: string
  supplier: string
  supplier_name: string
  warehouse: string
  warehouse_name?: string
  status: 'draft' | 'sent' | 'partially_received' | 'received' | 'closed' | 'canceled'
  order_date: string
  expected_date: string | null
  total_amount: string
  notes: string
  receipt: string | null
  created_at: string
}

// ─── Reports ──────────────────────────────────────────────────────────────────
export interface PnL {
  period_start: string
  period_end: string
  revenue: { gross_sales: string; tax_collected: string; discounts: string }
  cost_of_goods_sold: string
  gross_profit: string
  gross_margin_pct: string
  operating_expenses: string
  net_profit: string
  net_margin_pct: string
}

export interface SalesSummaryPoint {
  period: string
  total_revenue: string
  invoice_count: number
  total_tax: string
}

// ─── Tax ──────────────────────────────────────────────────────────────────────
export interface TaxClass {
  id: string
  name: string
  rate: string
  description: string
  is_active: boolean
}

export interface TaxBracket {
  id: string
  lower_bound: string
  upper_bound: string | null
  rate: string
  cumulative_tax_below: string
}

export interface TaxConfig {
  id: string
  name: string
  tax_type: 'income' | 'corporate' | 'vat' | 'withholding' | 'excise'
  country: string
  tax_year: number
  is_progressive: boolean
  flat_rate: string
  personal_allowance: string
  is_active: boolean
  notes: string
  brackets: TaxBracket[]
}

// ─── Pagination ───────────────────────────────────────────────────────────────
export interface PaginatedResponse<T> {
  count: number
  total_pages: number
  current_page: number
  next: string | null
  previous: string | null
  results: T[]
}

// Quotes
export interface QuoteItem {
  id: string
  product: string
  product_name: string
  quantity: string
  unit_price: string
  discount_percent: string
  tax_rate: string
  line_total: string
}

export interface Quote {
  id: string
  quote_number: string
  customer: string | null
  customer_name: string | null
  warehouse: string
  warehouse_name: string
  status: 'draft' | 'sent' | 'accepted' | 'rejected' | 'expired' | 'converted'
  issue_date: string
  valid_until: string
  subtotal: string
  discount_amount: string
  tax_amount: string
  total_amount: string
  notes: string
  terms: string
  converted_invoice: string | null
  created_at: string
  items: QuoteItem[]
}

// Bills / Accounts Payable
export interface BillItem {
  id: string
  description: string
  quantity: string
  unit_cost: string
  line_total: string
}

export interface BillPayment {
  id: string
  amount: string
  payment_date: string
  method: string
  reference: string
  notes: string
}

export interface Bill {
  id: string
  bill_number: string
  supplier: string
  supplier_name: string
  status: 'draft' | 'received' | 'approved' | 'paid' | 'partially_paid' | 'overdue' | 'voided'
  issue_date: string
  due_date: string
  reference: string
  subtotal: string
  tax_amount: string
  total_amount: string
  amount_paid: string
  amount_due: string
  notes: string
  attachment: string | null
  created_at: string
  items: BillItem[]
  payments: BillPayment[]
}

// Accounting / Chart of Accounts
export interface Account {
  id: string
  code: string
  name: string
  account_type: 'asset' | 'liability' | 'equity' | 'revenue' | 'expense' | 'cogs'
  parent: string | null
  description: string
  is_active: boolean
  is_system: boolean
  balance: string
}

export interface JournalLine {
  id: string
  account: string
  account_name: string
  account_code: string
  debit: string
  credit: string
  description: string
}

export interface JournalEntry {
  id: string
  reference: string
  description: string
  entry_date: string
  status: 'draft' | 'posted'
  created_at: string
  lines: JournalLine[]
}

export interface DepreciationEntry {
  id: string
  period_year: number
  period_month: number
  depreciation_amount: string
  accumulated_to_date: string
  net_book_value: string
}

export interface FixedAsset {
  id: string
  name: string
  asset_code: string
  category: 'land' | 'building' | 'vehicle' | 'equipment' | 'furniture' | 'other'
  account: string | null
  purchase_date: string
  purchase_cost: string
  depreciation_method: 'straight_line' | 'reducing_balance'
  useful_life_years: number
  residual_value: string
  disposal_date: string | null
  disposal_amount: string | null
  is_active: boolean
  annual_depreciation: string
  accumulated_depreciation: string
  net_book_value: string
  depreciation_entries: DepreciationEntry[]
}

// Payroll
export interface Employee {
  id: string
  employee_id: string
  first_name: string
  last_name: string
  full_name: string
  email: string
  phone: string
  job_title: string
  department: string
  employment_type: 'full_time' | 'part_time' | 'contract'
  hire_date: string
  termination_date: string | null
  bank_name: string
  account_number: string
  account_name: string
  pfa_name: string
  pfa_number: string
  tin: string
  basic_salary: string
  housing_allowance: string
  transport_allowance: string
  leave_allowance: string
  other_allowances: string
  gross_salary: string
  is_active: boolean
  created_at: string
}

export interface EmployeePenalty {
  id: string
  employee: string
  reason: string
  amount: string
  penalty_date: string
  status: 'pending' | 'applied' | 'waived'
  applied_in_run: string | null
  created_at: string
}

export interface EmployeeLoan {
  id: string
  employee: string
  principal_amount: string
  interest_rate: string
  duration_months: number
  start_date: string
  total_repayable: string
  monthly_installment: string
  amount_repaid: string
  balance_remaining: string
  status: 'active' | 'settled' | 'cancelled'
  notes: string
  created_at: string
}

export interface EmployeeDocument {
  id: string
  employee: string
  name: string
  document_type: 'cv' | 'id' | 'certificate' | 'contract' | 'other'
  file: string
  file_url: string | null
  file_size: number
  file_size_display: string
  created_at: string
}

export interface PayslipLine {
  id: string
  employee: string
  employee_name: string
  employee_id_str: string
  employee_bank_name?: string
  employee_bank_code?: string
  employee_account_number?: string
  employee_account_name?: string
  basic_salary: string
  housing_allowance: string
  transport_allowance: string
  leave_allowance: string
  other_allowances: string
  gross_salary: string
  bonus_amount: string
  overtime_amount: string
  employee_pension: string
  nhf: string
  nsitf: string
  consolidated_relief_allowance: string
  taxable_income: string
  paye_tax: string
  employer_pension: string
  penalty_deductions: string
  loan_deductions: string
  attendance_deduction: string
  total_deductions: string
  net_salary: string
  status: string
  transfer_status: 'pending' | 'initiated' | 'success' | 'failed' | 'skipped'
  transfer_reference: string
  transfer_error: string
}

export interface PayrollRun {
  id: string
  run_number: string
  period_year: number
  period_month: number
  status: 'draft' | 'processing' | 'approved' | 'paid'
  total_gross: string
  total_deductions: string
  total_net: string
  total_paye: string
  total_pension_employee: string
  total_pension_employer: string
  total_nhf: string
  total_nsitf: string
  total_bonus: string
  total_overtime: string
  submitted_for_approval: boolean
  submitted_by: string | null
  payment_date: string | null
  transfer_reference: string
  created_at: string
  payslips: PayslipLine[]
  employee_count: number
}

// Tax extensions
export interface ExciseDuty {
  id: string
  name: string
  product_category: 'spirits' | 'wine' | 'beer' | 'tobacco' | 'other'
  duty_type: 'specific' | 'ad_valorem'
  rate: string
  effective_date: string
  is_active: boolean
  notes: string
}

export interface WHTRate {
  id: string
  transaction_type: string
  company_rate: string
  individual_rate: string
  is_active: boolean
}

export interface WHTTransaction {
  id: string
  transaction_type: 'sale' | 'purchase'
  wht_rate: string
  wht_rate_name: string
  counterparty_name: string
  tin: string
  gross_amount: string
  wht_rate_percent: string
  wht_amount: string
  net_amount: string
  transaction_date: string
  status: 'withheld' | 'remitted'
  notes: string
}

// Recurring invoices
export interface RecurringInvoice {
  id: string
  template_name: string
  customer: string | null
  customer_name: string | null
  custom_customer_name: string
  warehouse: string
  warehouse_name: string
  frequency: 'daily' | 'weekly' | 'monthly' | 'quarterly' | 'annual'
  interval: number
  next_run_date: string
  end_date: string | null
  max_occurrences: number | null
  occurrences_count: number
  is_active: boolean
  items: object[]
  notes: string
  payment_method: string
  created_at: string
}

// Budget
export interface BudgetLine {
  id: string
  category: string | null
  category_name: string
  category_type: 'expense' | 'revenue'
  period_month: number | null
  budgeted_amount: string
  actual_amount?: string
  variance?: string
}

export interface Budget {
  id: string
  name: string
  fiscal_year: number
  period_type: 'monthly' | 'quarterly' | 'annual'
  status: 'draft' | 'active' | 'closed'
  notes: string
  created_at: string
  lines: BudgetLine[]
}

// Payment gateway
export interface PaymentGatewayConfig {
  id: string
  provider: 'paystack' | 'flutterwave'
  public_key: string
  is_active: boolean
}

export interface PaymentLink {
  id: string
  invoice: string
  invoice_number: string
  provider: string
  payment_reference: string
  amount: string
  currency: string
  link_url: string
  status: 'pending' | 'paid' | 'failed' | 'cancelled'
  paid_at: string | null
  created_at: string
}

// ─── Financial Periods ────────────────────────────────────────────────────────
export interface FinancialPeriod {
  id: string
  year: number
  month: number
  is_locked: boolean
  locked_by: string | null
  locked_by_name: string | null
  locked_at: string | null
  created_at: string
}

// ─── Bank Reconciliation ──────────────────────────────────────────────────────
export interface BankReconciliationLine {
  id: string
  description: string
  transaction_date: string
  amount: string
  is_cleared: boolean
  reference: string
  journal_line: string | null
}

export interface BankReconciliation {
  id: string
  account: string
  account_name: string
  account_code: string
  period_start: string
  period_end: string
  statement_closing_balance: string
  book_balance: string
  is_reconciled: boolean
  reconciled_by: string | null
  reconciled_at: string | null
  notes: string
  lines: BankReconciliationLine[]
  created_at: string
}

// ─── AR Aging ─────────────────────────────────────────────────────────────────
export interface ARAgingBuckets {
  current: number
  '1_30': number
  '31_60': number
  '61_90': number
  over_90: number
}

export interface ARAgingInvoice {
  id: string
  invoice_number: string
  customer_name: string | null
  amount_due: string
  due_date: string | null
  days_overdue: number
}

export interface ARAgingReport {
  as_of: string
  buckets: ARAgingBuckets
  total_outstanding: string
  invoices: ARAgingInvoice[]
}

// ─── VAT Summary ──────────────────────────────────────────────────────────────
export interface VATSummary {
  period_start: string
  period_end: string
  output_vat: string
  input_vat: string
  net_vat_payable: string
}

// ─── Team / Module Permissions ───────────────────────────────────────────────
export type ModuleKey =
  | 'sales' | 'purchases' | 'bills' | 'expenses' | 'inventory'
  | 'customers' | 'suppliers' | 'payroll' | 'reports' | 'accounting'
  | 'tax' | 'budget' | 'quotes' | 'recurring' | 'settings'
  | 'audit_log' | 'owner_analytics' | 'team'

export type AccessLevel = 'none' | 'view' | 'write' | 'edit'

export interface ModulePermission {
  id: string
  module: ModuleKey
  access_level: AccessLevel
}

export interface TeamMember {
  id: string
  user: string
  user_email: string
  user_full_name: string
  role: string
  is_active: boolean
  joined_at: string | null
  module_permissions: ModulePermission[]
  partner_firm_name?: string | null
}

// ─── Subscription / Billing ──────────────────────────────────────────────────
export interface Plan {
  id: string
  name: string
  slug: string
  description: string
  price: string
  interval: 'monthly' | 'annual'
  trial_days: number
  features: Record<string, number | boolean | string>
  is_public: boolean
  display_order: number
}

export interface Subscription {
  id: string
  plan: Plan
  status: 'trialing' | 'active' | 'past_due' | 'canceled' | 'unpaid' | 'incomplete'
  is_active: boolean
  trial_end: string | null
  current_period_start: string | null
  current_period_end: string | null
  canceled_at: string | null
  created_at: string
}

export interface SubscriptionPayment {
  id: string
  amount: string
  currency: string
  status: 'succeeded' | 'failed' | 'refunded'
  description: string
  created_at: string
}

export interface InitiatePaymentResult {
  authorization_url: string
  reference: string
  access_code: string
}

// ─── Overdue Invoice Alert ────────────────────────────────────────────────────
export interface OverdueInvoiceAlert {
  id: string
  invoice_number: string
  customer_name: string | null
  amount_due: string
  due_date: string
  days_overdue: number
}

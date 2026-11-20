/**
 * New Sale page — money lines and the request body.
 *
 * Guards the visual tidy of the page: for each VAT / discount situation the
 * summary strings the cashier reads, and the exact body sent to salesApi.create,
 * must not move. The EXPECTED values below were recorded from the page BEFORE
 * the tidy (base commit e83e43b), then checked again after it.
 */
import { appendFileSync } from 'node:fs'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import NewSalePage from '@/pages/sales/NewSalePage'
import { useAuthStore } from '@/store/authStore'

const createMock = vi.fn()
let sellable: unknown[] = []

vi.mock('@/services/api', () => ({
  customerApi: { list: vi.fn(() => Promise.resolve({ data: { results: [] } })) },
  inventoryApi: {
    sellableProducts: vi.fn(() => Promise.resolve({ data: { results: sellable } })),
    warehouses: vi.fn(() => Promise.resolve({ data: { results: [{ id: 'wh1', name: 'Main Store', is_default: true }] } })),
  },
  locationApi: { list: vi.fn(() => Promise.resolve({ data: { results: [] } })) },
  tillApi: { current: vi.fn(() => Promise.resolve({ data: { open: true } })) },
  taxApi: { classes: vi.fn(() => Promise.resolve({ data: { results: [{ id: 'vat', rate: '7.5' }] } })) },
  salesApi: { create: (...a: unknown[]) => createMock(...a) },
  urlToDataUrl: vi.fn(() => Promise.resolve(null)),
}))
vi.mock('@/contexts/NotificationsContext', () => ({ useNotifications: () => ({ refetch: vi.fn() }) }))
vi.mock('@/hooks/useReceiptDefaults', () => ({ useReceiptDefaults: () => ({ merchant: 'Test Shop' }) }))
vi.mock('@/lib/receipt', () => ({ printReceipt: vi.fn(), formatReceiptTime: () => '' }))
vi.mock('react-hot-toast', () => ({ default: Object.assign(vi.fn(), { error: vi.fn(), success: vi.fn() }) }))

type P = Record<string, unknown>
const product = (id: string, price: string, extra: P = {}): P => ({
  id, sku: `SKU-${id}`, name: `Item ${id}`, brand: '', category: null, category_name: null,
  unit_of_measure: 'pcs', selling_price: price, total_stock: 50, barcode: '',
  is_taxable: false, tax_class: null, tax_type: 'exclusive', ...extra,
})
const noVat = product('a', '1000.00')
const vatEx = product('b', '1500.00', { is_taxable: true, tax_class: 'vat', tax_type: 'exclusive' })
const vatIn = product('c', '1075.00', { is_taxable: true, tax_class: 'vat', tax_type: 'inclusive' })

/** The text of the right-hand figure on a summary row, or null when the row is absent. */
const row = (label: string) => {
  const el = screen.queryByText(label, { selector: 'span' })
  return el ? (el.parentElement?.textContent ?? null) : null
}

async function addProduct(p: P) {
  sellable = [p]
  const box = screen.getByPlaceholderText(/scan barcode/i)
  fireEvent.change(box, { target: { value: String(p.name) } })
  const btn = await screen.findByText(String(p.name), { selector: 'p' }, { timeout: 3000 })
  fireEvent.mouseDown(btn)
  await waitFor(() => expect(screen.queryByPlaceholderText(/scan barcode/i)).toHaveValue(''))
}

async function runCase(items: P[], discount?: string) {
  cleanup()
  createMock.mockReset()
  createMock.mockResolvedValue({ data: {} })
  render(<MemoryRouter><NewSalePage /></MemoryRouter>)
  for (const p of items) await addProduct(p)
  if (discount) {
    // each cart row has three number boxes: quantity, unit price, discount %
    const boxes = screen.getAllByRole('spinbutton')
    for (let i = 2; i < boxes.length; i += 3) fireEvent.change(boxes[i], { target: { value: discount } })
  }
  // the page must have a warehouse before it will submit
  await waitFor(() => expect(screen.getByRole('combobox')).toHaveValue('wh1'))
  const lines = {
    subtotal: row('Subtotal'),
    discount: row('Discount'),
    vat: row('VAT'),
    vatIncluded: row('VAT included in prices'),
    grandTotal: row('Grand Total'),
    confirm: screen.getByRole('button', { name: /Confirm Sale/ }).textContent,
  }
  fireEvent.click(screen.getByRole('button', { name: /Confirm Sale/ }))
  await waitFor(() => expect(createMock).toHaveBeenCalledTimes(1))
  return { lines, body: JSON.stringify(createMock.mock.calls[0][0]) }
}

// Filled from the BASE run (see commit message). null = the row is not shown.
const EXPECTED: Record<string, { lines: Record<string, string | null>; body: string }> = {
  "no VAT": {
    lines: {"subtotal": "Subtotal₦1,000.00", "discount": null, "vat": null, "vatIncluded": null, "grandTotal": null, "confirm": "Confirm Sale · ₦1,000.00"},
    body: "{\"customer_id\":null,\"warehouse_id\":\"wh1\",\"location_id\":null,\"payment_method\":\"cash\",\"amount_paid\":\"1000.00\",\"amount_tendered\":\"1000.00\",\"credit_applied\":\"0.00\",\"notes\":\"\",\"sold_by\":\"Test Cashier\",\"is_proforma\":false,\"items\":[{\"product_id\":\"a\",\"quantity\":1,\"unit_price\":\"1000.0000\",\"discount_percent\":\"0.00\"}]}",
  },
  "VAT exclusive": {
    lines: {"subtotal": "Subtotal₦1,500.00", "discount": null, "vat": "VAT+ ₦112.50", "vatIncluded": null, "grandTotal": "Grand Total₦1,612.50", "confirm": "Confirm Sale · ₦1,612.50"},
    body: "{\"customer_id\":null,\"warehouse_id\":\"wh1\",\"location_id\":null,\"payment_method\":\"cash\",\"amount_paid\":\"1612.50\",\"amount_tendered\":\"1612.50\",\"credit_applied\":\"0.00\",\"notes\":\"\",\"sold_by\":\"Test Cashier\",\"is_proforma\":false,\"items\":[{\"product_id\":\"b\",\"quantity\":1,\"unit_price\":\"1500.0000\",\"discount_percent\":\"0.00\"}]}",
  },
  "VAT inclusive": {
    lines: {"subtotal": "Subtotal₦1,075.00", "discount": null, "vat": null, "vatIncluded": "VAT included in prices₦75.00", "grandTotal": null, "confirm": "Confirm Sale · ₦1,075.00"},
    body: "{\"customer_id\":null,\"warehouse_id\":\"wh1\",\"location_id\":null,\"payment_method\":\"cash\",\"amount_paid\":\"1075.00\",\"amount_tendered\":\"1075.00\",\"credit_applied\":\"0.00\",\"notes\":\"\",\"sold_by\":\"Test Cashier\",\"is_proforma\":false,\"items\":[{\"product_id\":\"c\",\"quantity\":1,\"unit_price\":\"1075.0000\",\"discount_percent\":\"0.00\"}]}",
  },
  "mixed": {
    lines: {"subtotal": "Subtotal₦3,575.00", "discount": null, "vat": "VAT+ ₦112.50", "vatIncluded": "VAT included in prices₦75.00", "grandTotal": "Grand Total₦3,687.50", "confirm": "Confirm Sale · ₦3,687.50"},
    body: "{\"customer_id\":null,\"warehouse_id\":\"wh1\",\"location_id\":null,\"payment_method\":\"cash\",\"amount_paid\":\"3687.50\",\"amount_tendered\":\"3687.50\",\"credit_applied\":\"0.00\",\"notes\":\"\",\"sold_by\":\"Test Cashier\",\"is_proforma\":false,\"items\":[{\"product_id\":\"a\",\"quantity\":1,\"unit_price\":\"1000.0000\",\"discount_percent\":\"0.00\"},{\"product_id\":\"b\",\"quantity\":1,\"unit_price\":\"1500.0000\",\"discount_percent\":\"0.00\"},{\"product_id\":\"c\",\"quantity\":1,\"unit_price\":\"1075.0000\",\"discount_percent\":\"0.00\"}]}",
  },
  "10% discount": {
    lines: {"subtotal": "Subtotal₦3,575.00", "discount": "Discount− ₦357.50", "vat": "VAT+ ₦101.25", "vatIncluded": "VAT included in prices₦67.50", "grandTotal": "Grand Total₦3,318.75", "confirm": "Confirm Sale · ₦3,318.75"},
    body: "{\"customer_id\":null,\"warehouse_id\":\"wh1\",\"location_id\":null,\"payment_method\":\"cash\",\"amount_paid\":\"3318.75\",\"amount_tendered\":\"3318.75\",\"credit_applied\":\"0.00\",\"notes\":\"\",\"sold_by\":\"Test Cashier\",\"is_proforma\":false,\"items\":[{\"product_id\":\"a\",\"quantity\":1,\"unit_price\":\"1000.0000\",\"discount_percent\":\"10.00\"},{\"product_id\":\"b\",\"quantity\":1,\"unit_price\":\"1500.0000\",\"discount_percent\":\"10.00\"},{\"product_id\":\"c\",\"quantity\":1,\"unit_price\":\"1075.0000\",\"discount_percent\":\"10.00\"}]}",
  },
}
const CASES: Record<string, () => Promise<{ lines: Record<string, string | null>; body: string }>> = {
  'no VAT': () => runCase([noVat]),
  'VAT exclusive': () => runCase([vatEx]),
  'VAT inclusive': () => runCase([vatIn]),
  'mixed': () => runCase([noVat, vatEx, vatIn]),
  '10% discount': () => runCase([noVat, vatEx, vatIn], '10'),
}

describe('New Sale totals and request body', () => {
  beforeEach(() => {
    sellable = []
    localStorage.clear()
    useAuthStore.setState({
      user: { id: 'u1', first_name: 'Test', last_name: 'Cashier', email: 't@example.com' },
      organisation: { id: 'o1', charges_vat: true },
    } as never)
  })

  for (const name of Object.keys(CASES)) {
    it(name, async () => {
      const got = await CASES[name]()
      if (process.env.RECORD_NEWSALE) appendFileSync(process.env.RECORD_NEWSALE, `${name}	${JSON.stringify(got)}
`)
      const want = EXPECTED[name]
      expect(want).toBeDefined()
      expect(got.lines).toEqual(want.lines)
      expect(got.body).toBe(want.body)
    }, 20000)
  }
})

/**
 * New sale & invoice page — money lines and the request body.
 *
 * The EXPECTED request bodies below were recorded from the OLD New Sale page (base commit
 * e83e43b) and must not move: "Complete sale" with the default choices posts exactly what
 * "Confirm Sale" always did. The figures were recorded from the same page's summary.
 * Further cases cover the invoice path (dates, delivery, fulfil later), the signed total
 * adjustment, credit, deposits, held baskets and the saleTotals helper itself.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import NewSalePage from '@/pages/sales/NewSalePage'
import { useAuthStore } from '@/store/authStore'
import { saleTotals } from '@/lib/saleMath'

const createMock = vi.fn()
let sellable: unknown[] = []
let customerList: unknown[] = []

vi.mock('@/services/api', () => ({
  customerApi: { list: vi.fn(() => Promise.resolve({ data: { results: customerList } })) },
  inventoryApi: {
    sellableProducts: vi.fn(() => Promise.resolve({ data: { results: sellable } })),
    warehouses: vi.fn(() => Promise.resolve({ data: { results: [{ id: 'wh1', name: 'Main Store', is_default: true }] } })),
  },
  locationApi: { list: vi.fn(() => Promise.resolve({ data: { results: [] } })) },
  tillApi: { current: vi.fn(() => Promise.resolve({ data: { open: true } })) },
  taxApi: { classes: vi.fn(() => Promise.resolve({ data: { results: [{ id: 'vat', name: 'VAT', rate: '7.5' }] } })) },
  teamApi: { members: vi.fn(() => Promise.resolve({ data: { results: [] } })) },
  salesApi: { create: (...a: unknown[]) => createMock(...a), invoice: vi.fn(), sendEmail: vi.fn() },
  savedMessage: (_r: unknown, done: string) => done,
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

/** The right-hand figure of a summary row found by its label text, or null when absent. */
const row = (label: RegExp | string) => {
  const el = within(screen.getByRole('region', { name: 'Order summary' })).queryByText(label)
  return el ? (el.parentElement?.lastElementChild?.textContent ?? null) : null
}
const grand = () => screen.getByTestId('grand-total').textContent

async function addProduct(p: P) {
  sellable = [p]
  const box = screen.getByPlaceholderText(/scan barcode/i)
  fireEvent.change(box, { target: { value: String(p.name) } })
  const btn = await screen.findByText(String(p.name), { selector: 'p' }, { timeout: 3000 })
  fireEvent.mouseDown(btn)
  await waitFor(() => expect(screen.queryByPlaceholderText(/scan barcode/i)).toHaveValue(''))
}

async function setup(items: P[], discount?: string) {
  cleanup()
  createMock.mockReset()
  createMock.mockResolvedValue({ data: {}, statusText: 'Created' })
  render(<MemoryRouter><NewSalePage /></MemoryRouter>)
  for (const p of items) await addProduct(p)
  if (discount) {
    items.forEach((_, i) => fireEvent.change(screen.getByLabelText(`Discount percent, line ${i + 1}`), { target: { value: discount } }))
  }
  // the page must have a warehouse before it will submit
  await waitFor(() => expect(screen.getByLabelText('Warehouse (stock)')).toHaveValue('wh1'))
}

async function pickCustomer() {
  customerList = [{ id: 'cust1', name: 'Ada Stores', customer_type: 'business', phone: '080', store_credit: '0', available_credit: '0' }]
  fireEvent.change(screen.getByPlaceholderText('Search customer…'), { target: { value: 'Ada' } })
  fireEvent.mouseDown(await screen.findByText('Ada Stores', { selector: 'p' }, { timeout: 3000 }))
}

async function runCase(items: P[], discount?: string) {
  await setup(items, discount)
  const lines = {
    subtotal: row(/^Subtotal ·/),
    discount: row('Item discounts'),
    vat: row('VAT'),
    vatIncluded: row('VAT included in prices'),
    grandTotal: grand(),
  }
  fireEvent.click(screen.getByRole('button', { name: 'Complete sale' }))
  await waitFor(() => expect(createMock).toHaveBeenCalledTimes(1))
  return { lines, body: JSON.stringify(createMock.mock.calls[0][0]) }
}

// Bodies recorded from the OLD page; figures are what its summary showed. null = row not shown.
const EXPECTED: Record<string, { lines: Record<string, string | null>; body: string }> = {
  "no VAT": {
    lines: { subtotal: "₦1,000.00", discount: "₦0.00", vat: "₦0.00", vatIncluded: null, grandTotal: "₦1,000.00" },
    body: "{\"customer_id\":null,\"warehouse_id\":\"wh1\",\"location_id\":null,\"payment_method\":\"cash\",\"amount_paid\":\"1000.00\",\"amount_tendered\":\"1000.00\",\"credit_applied\":\"0.00\",\"notes\":\"\",\"sold_by\":\"Test Cashier\",\"is_proforma\":false,\"items\":[{\"product_id\":\"a\",\"quantity\":1,\"unit_price\":\"1000.0000\",\"discount_percent\":\"0.00\"}]}",
  },
  "VAT exclusive": {
    lines: { subtotal: "₦1,500.00", discount: "₦0.00", vat: "+ ₦112.50", vatIncluded: null, grandTotal: "₦1,612.50" },
    body: "{\"customer_id\":null,\"warehouse_id\":\"wh1\",\"location_id\":null,\"payment_method\":\"cash\",\"amount_paid\":\"1612.50\",\"amount_tendered\":\"1612.50\",\"credit_applied\":\"0.00\",\"notes\":\"\",\"sold_by\":\"Test Cashier\",\"is_proforma\":false,\"items\":[{\"product_id\":\"b\",\"quantity\":1,\"unit_price\":\"1500.0000\",\"discount_percent\":\"0.00\"}]}",
  },
  "VAT inclusive": {
    lines: { subtotal: "₦1,075.00", discount: "₦0.00", vat: "₦0.00", vatIncluded: "₦75.00", grandTotal: "₦1,075.00" },
    body: "{\"customer_id\":null,\"warehouse_id\":\"wh1\",\"location_id\":null,\"payment_method\":\"cash\",\"amount_paid\":\"1075.00\",\"amount_tendered\":\"1075.00\",\"credit_applied\":\"0.00\",\"notes\":\"\",\"sold_by\":\"Test Cashier\",\"is_proforma\":false,\"items\":[{\"product_id\":\"c\",\"quantity\":1,\"unit_price\":\"1075.0000\",\"discount_percent\":\"0.00\"}]}",
  },
  "mixed": {
    lines: { subtotal: "₦3,575.00", discount: "₦0.00", vat: "+ ₦112.50", vatIncluded: "₦75.00", grandTotal: "₦3,687.50" },
    body: "{\"customer_id\":null,\"warehouse_id\":\"wh1\",\"location_id\":null,\"payment_method\":\"cash\",\"amount_paid\":\"3687.50\",\"amount_tendered\":\"3687.50\",\"credit_applied\":\"0.00\",\"notes\":\"\",\"sold_by\":\"Test Cashier\",\"is_proforma\":false,\"items\":[{\"product_id\":\"a\",\"quantity\":1,\"unit_price\":\"1000.0000\",\"discount_percent\":\"0.00\"},{\"product_id\":\"b\",\"quantity\":1,\"unit_price\":\"1500.0000\",\"discount_percent\":\"0.00\"},{\"product_id\":\"c\",\"quantity\":1,\"unit_price\":\"1075.0000\",\"discount_percent\":\"0.00\"}]}",
  },
  "10% discount": {
    lines: { subtotal: "₦3,575.00", discount: "− ₦357.50", vat: "+ ₦101.25", vatIncluded: "₦67.50", grandTotal: "₦3,318.75" },
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

describe('New sale & invoice totals and request body', () => {
  beforeEach(() => {
    sellable = []
    customerList = []
    localStorage.clear()
    useAuthStore.setState({
      user: { id: 'u1', first_name: 'Test', last_name: 'Cashier', email: 't@example.com' },
      organisation: { id: 'o1', charges_vat: true },
    } as never)
  })

  for (const name of Object.keys(CASES)) {
    it(`Complete sale: ${name}`, async () => {
      const got = await CASES[name]()
      const want = EXPECTED[name]
      expect(got.lines).toEqual(want.lines)
      expect(got.body).toBe(want.body)
    }, 20000)
  }

  it('Create invoice sends dates, delivery and fulfil later, and the total includes delivery', async () => {
    await setup([vatEx])
    await pickCustomer()
    fireEvent.click(screen.getByRole('radio', { name: /Fulfill later/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Credit · pay later' }))
    fireEvent.change(screen.getByLabelText(/Delivery \/ shipping/), { target: { value: '500' } })
    expect(grand()).toBe('₦2,112.50')
    fireEvent.click(screen.getByRole('button', { name: 'Create invoice' }))
    await waitFor(() => expect(createMock).toHaveBeenCalledTimes(1))
    const b = createMock.mock.calls[0][0]
    expect(b).toMatchObject({
      customer_id: 'cust1', payment_method: 'credit', amount_paid: '0', amount_tendered: null,
      is_proforma: false, defer_fulfillment: true, shipping_amount: '500.0000',
    })
    expect(b.issue_date).toMatch(/^\d{4}-\d{2}-\d{2}$/)
    expect(b.adjustment_amount).toBeUndefined()
  }, 20000)

  it('always starts on Fulfill now, so a credit sale to a customer still moves stock as before', async () => {
    await setup([noVat])
    await pickCustomer()
    fireEvent.click(screen.getByRole('button', { name: 'Credit · pay later' }))
    expect(screen.getByRole('radio', { name: /Fulfill now/ })).toBeChecked()
    fireEvent.click(screen.getByRole('button', { name: 'Complete sale' }))
    await waitFor(() => expect(createMock).toHaveBeenCalledTimes(1))
    expect(createMock.mock.calls[0][0].defer_fulfillment).toBeUndefined()
  }, 20000)

  it('Create invoice needs a customer', async () => {
    await setup([noVat])
    expect(screen.getByRole('button', { name: 'Create invoice' })).toBeDisabled()
    expect(screen.getByText('For an invoice, also select a customer.')).toBeTruthy()
    expect(createMock).not.toHaveBeenCalled()
  }, 20000)

  it('Total adjustment is signed, changes the grand total and is sent as adjustment_amount', async () => {
    await setup([vatEx])
    fireEvent.change(screen.getByLabelText(/Total adjustment/), { target: { value: '-100' } })
    expect(grand()).toBe('₦1,512.50')
    expect(screen.getByTestId('adjustment-signed').textContent).toBe('-₦100.00')
    fireEvent.click(screen.getByRole('button', { name: 'Complete sale' }))
    await waitFor(() => expect(createMock).toHaveBeenCalledTimes(1))
    const b = createMock.mock.calls[0][0]
    expect(b.adjustment_amount).toBe('-100.00')
    expect(b.amount_paid).toBe('1512.50')
  }, 20000)

  it('an adjustment bigger than the total, or not a number, is refused with a plain message', async () => {
    await setup([noVat])
    fireEvent.change(screen.getByLabelText(/Total adjustment/), { target: { value: '-5000' } })
    expect(screen.getAllByText('Adjustment is bigger than the total.').length).toBeGreaterThan(0)
    expect(screen.getByRole('button', { name: 'Complete sale' })).toBeDisabled()
    fireEvent.change(screen.getByLabelText(/Total adjustment/), { target: { value: '-' } })
    expect(screen.getAllByText('Enter a number, like -500 or 200.').length).toBeGreaterThan(0)
  }, 20000)

  it('credit needs a named customer: a walk-in cannot be put on credit, and no tender box shows', async () => {
    await setup([noVat])
    fireEvent.click(screen.getByRole('button', { name: 'Credit · pay later' }))
    expect(screen.getByRole('button', { name: 'Complete sale' })).toBeDisabled()
    expect(screen.getAllByText('Pick a customer to sell on credit.').length).toBeGreaterThan(0)
    expect(screen.queryByLabelText(/Amount received/)).toBeNull()
  }, 20000)

  it('cash tender 5,000 on a 1,000 sale shows change 4,000; a short tender says what is still owed', async () => {
    await setup([noVat])
    fireEvent.change(screen.getByLabelText(/Amount received/), { target: { value: '5000' } })
    expect(screen.getByTestId('change').textContent).toBe('₦4,000.00')
    fireEvent.change(screen.getByLabelText(/Amount received/), { target: { value: '600' } })
    expect(screen.getByText('₦400.00 still owed')).toBeTruthy()
  }, 20000)

  it('delivery blocks Complete sale (invoice only)', async () => {
    await setup([noVat])
    fireEvent.change(screen.getByLabelText(/Delivery \/ shipping/), { target: { value: '200' } })
    expect(screen.getByRole('button', { name: 'Complete sale' })).toBeDisabled()
  }, 20000)

  it('paid + fulfil later is a deposit: sent with defer_fulfillment and the paid amount', async () => {
    await setup([noVat])
    fireEvent.click(screen.getByRole('radio', { name: /Fulfill later/ }))
    expect(screen.getByText(/held as a customer deposit/)).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Complete sale' }))
    await waitFor(() => expect(createMock).toHaveBeenCalledTimes(1))
    expect(createMock.mock.calls[0][0]).toMatchObject({ defer_fulfillment: true, amount_paid: '1000.00' })
  }, 20000)

  it('save as proforma posts no payment', async () => {
    await setup([noVat])
    fireEvent.click(screen.getByRole('button', { name: 'Save as proforma' }))
    await waitFor(() => expect(createMock).toHaveBeenCalledTimes(1))
    expect(createMock.mock.calls[0][0]).toMatchObject({ is_proforma: true, amount_paid: '0', amount_tendered: null })
  }, 20000)

  it('a double click on Complete sale makes exactly one sale', async () => {
    await setup([noVat])
    const btn = screen.getByRole('button', { name: 'Complete sale' })
    fireEvent.click(btn)
    fireEvent.click(btn)
    await waitFor(() => expect(createMock).toHaveBeenCalledTimes(1))
    await new Promise((r) => setTimeout(r, 100))
    expect(createMock).toHaveBeenCalledTimes(1)
  }, 20000)

  it('hold then resume brings back the items, quantities and the customer', async () => {
    await setup([noVat])
    await pickCustomer()
    fireEvent.change(screen.getByLabelText('Quantity, line 1'), { target: { value: '3' } })
    fireEvent.click(screen.getByRole('button', { name: 'Hold basket' }))
    expect(screen.getByText('Basket held.')).toBeTruthy()
    expect(grand()).toBe('₦0.00')
    fireEvent.click(screen.getByRole('button', { name: 'Held (1)' }))
    fireEvent.click(screen.getByRole('button', { name: 'Resume' }))
    await waitFor(() => expect(grand()).toBe('₦3,000.00'))
    expect(screen.getByLabelText('Quantity, line 1')).toHaveValue(3)
    expect(screen.getByText('Ada Stores')).toBeTruthy()
  }, 20000)

  it('a blank page greys the four buttons and Email / Export PDF', async () => {
    await setup([])
    for (const n of ['Create invoice', 'Complete sale']) expect(screen.getByRole('button', { name: n })).toBeDisabled()
    expect(screen.getByRole('button', { name: /Email/ })).toBeDisabled()
    expect(screen.getByRole('button', { name: /Export PDF/ })).toBeDisabled()
    expect(screen.getByText('Add at least one item to continue.')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Hold basket' }))
    expect(screen.getByText('Nothing to hold.')).toBeTruthy()
  }, 20000)
})

describe('saleTotals with a signed adjustment', () => {
  const line = { unitPrice: 1500, quantity: 1, taxRate: 7.5 }
  it('is unchanged when there is no adjustment', () => {
    expect(saleTotals([line]).total).toBe(1612.5)
    expect(saleTotals([line], 0, 0).total).toBe(1612.5)
  })
  it('a minus adjustment is a discount, a plus one an extra charge, added after VAT and delivery', () => {
    expect(saleTotals([line], 500, -100).total).toBe(2012.5)
    expect(saleTotals([line], 0, 250.25).total).toBe(1862.75)
  })
  it('adds up to the kobo with awkward figures', () => {
    expect(saleTotals([{ unitPrice: 0.1, quantity: 3 }], 0.2, -0.05).total).toBe(0.45)
  })
})

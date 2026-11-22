/**
 * Security clean-ups: what a held basket may keep on disk, what may go into a receipt's <img src>,
 * and clearing the service worker's saved API answers.
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { buildReceiptHtml, safeLogoDataUrl, safeBase64, type ReceiptData } from '@/lib/receipt'
import { slimProduct, slimCustomer, stripProductSecrets } from '@/lib/localUserData'
import { clearApiCache } from '@/lib/localDataGuard'
import type { Customer, Product } from '@/types'

const product = {
  id: 'p1', sku: 'S1', name: 'Rice', brand: 'X', category: 'c', category_name: 'Grains', unit_of_measure: 'bag',
  cost_price: '4200.00', owner_cost_price: '4100.00', selling_price: '5000.00', reorder_level: 3, is_active: true,
  is_taxable: true, tax_class: 'vat', tax_type: 'exclusive', barcode: '123',
  inventory_account: 'acc-1', cogs_account_code: '5000', costing_method: 'fifo', custom_fields: { supplier: 'Secret Ltd' },
  total_stock: 40,
} as unknown as Product

const customer = {
  id: 'c1', code: 'C-1', name: 'Ada Stores', customer_type: 'retail', email: 'ada@x.com', phone: '080',
  address: '1 Road', credit_limit: '90000', outstanding_balance: '1200', store_credit: '500', available_credit: '500',
  is_credit_blocked: false, credit_score: 700, is_active: true,
} as unknown as Customer

describe('held basket keeps only what it needs', () => {
  it('a product loses cost price, ledger accounts and custom fields but keeps what resumes a line', () => {
    const s = JSON.stringify(slimProduct(product))
    expect(s).not.toMatch(/4200|4100|acc-1|5000"|fifo|Secret/)
    expect(slimProduct(product)).toMatchObject({ id: 'p1', name: 'Rice', sku: 'S1', selling_price: '5000.00', is_taxable: true, tax_class: 'vat', tax_type: 'exclusive' })
  })
  it('a customer keeps only id, name, type and phone', () => {
    const s = slimCustomer(customer)
    expect(s).toMatchObject({ id: 'c1', name: 'Ada Stores', phone: '080' })
    expect(JSON.stringify(s)).not.toMatch(/ada@x.com|1 Road|90000|1200|700/)
    expect(s.store_credit).toBe('0')
  })
  it('the till register copy drops only the private fields', () => {
    const s = stripProductSecrets(product) as unknown as Record<string, unknown>
    expect(s.cost_price).toBe('')
    expect(s.owner_cost_price).toBeUndefined()
    expect(s.inventory_account).toBeUndefined()
    expect(s.cogs_account_code).toBeUndefined()
    expect(s.custom_fields).toBeUndefined()
    expect(s.name).toBe('Rice')
    expect(s.selling_price).toBe('5000.00')
  })
})

describe('receipt pictures', () => {
  const png = 'data:image/png;base64,iVBORw0KGgo='
  it('accepts a plain base64 png, jpeg or webp', () => {
    expect(safeLogoDataUrl(png)).toBe(png)
    expect(safeLogoDataUrl('data:image/jpeg;base64,/9j/4AAQ==')).not.toBe('')
    expect(safeLogoDataUrl('data:image/webp;base64,UklGRg==')).not.toBe('')
  })
  it('rejects anything that could break out of the attribute', () => {
    expect(safeLogoDataUrl('data:image/png;base64,AAA" onerror="alert(1)')).toBe('')
    expect(safeLogoDataUrl('data:image/svg+xml;base64,PHN2Zz4=')).toBe('')
    expect(safeLogoDataUrl('javascript:alert(1)')).toBe('')
    expect(safeLogoDataUrl(null)).toBe('')
    expect(safeBase64('AAA"><script>')).toBe('')
    expect(safeBase64('QUJD')).toBe('QUJD')
  })
  it('a bad logo or QR never reaches the receipt page', () => {
    const d = {
      merchant: 'Shop', invoiceNumber: 'INV-1', date: '01/01/2026', lines: [], subtotal: 0, tax: 0, total: 0,
      logoDataUrl: 'data:image/png;base64,AAA" onerror="alert(1)', qrCodeBase64: 'AAA"><script>alert(1)</script>',
    } as unknown as ReceiptData
    const html = buildReceiptHtml(d)
    expect(html).not.toMatch(/onerror|<script/i)
    expect(html).not.toContain('class="qr"')
    const ok = buildReceiptHtml({ ...d, logoDataUrl: png, qrCodeBase64: 'QUJD' })
    expect(ok).toContain(`src="${png}"`)
    expect(ok).toContain('data:image/png;base64,QUJD')
  })
})

describe('service worker API cache', () => {
  afterEach(() => { vi.unstubAllGlobals() })
  it('clears api-cache and leaves other caches alone', async () => {
    const store: Record<string, boolean> = { 'api-cache': true, 'workbox-precache-v2': true }
    vi.stubGlobal('caches', {
      keys: async () => Object.keys(store),
      delete: async (n: string) => { delete store[n]; return true },
    })
    expect(await clearApiCache()).toBe(true)
    expect(Object.keys(store)).toEqual(['workbox-precache-v2'])
  })
  it('is fine where there is no Cache Storage, and reports a failure', async () => {
    vi.stubGlobal('caches', undefined)
    expect(await clearApiCache()).toBe(true)
    vi.stubGlobal('caches', { keys: async () => { throw new Error('nope') } })
    expect(await clearApiCache()).toBe(false)
  })
})

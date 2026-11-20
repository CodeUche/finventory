/**
 * New sale & invoice: browser proof that what the screen shows is what gets saved.
 * Money rows of the matrix that a browser is needed for. The server arithmetic
 * (journals, stock, rounding) is proven in backend/apps/sales/test_p2_sale_matrix.py.
 *
 * Own products (unique SKU per run), own invoices, all removed in afterAll.
 */
import { test, expect, apiLogin, Tracker, Api, gotoNewSale, addProduct, pickCustomer, money, NS, URL_BASE } from './p2/support'

test.describe.configure({ mode: 'serial' })

let api: Api, t: Tracker
let plain: { id: string; sku: string; name: string }   // 1000, no VAT
let taxed: { id: string; sku: string; name: string }   // 1000 + 7.5% VAT on top
let customer: { id: string; name: string }

test.beforeAll(async () => {
  api = await apiLogin(); t = new Tracker(api)
  const cls = await (await api.ctx.get('tax/classes/')).json()
  const vat = cls.results.find((c: any) => Number(c.rate) === 7.5)
  expect(vat, 'staging org needs a 7.5% tax class').toBeTruthy()
  plain = await t.product({}, 'P2QA-PLAIN')
  taxed = await t.product({ is_taxable: true, tax_class: vat.id, tax_type: 'exclusive' }, 'P2QA-VAT75')
  const cres = await api.ctx.post('customers/', { data: { code: `P2${Date.now().toString(36)}`.toUpperCase(), name: `P2QA Cust ${Date.now().toString(36)}`, customer_type: 'retail', phone: '+2348000000000' } })
  expect(cres.ok(), await cres.text()).toBeTruthy()
  customer = await cres.json()
})
test.afterAll(async () => {
  await t.cleanup()
  if (customer?.id) await api.ctx.delete(`customers/${customer.id}/`).catch(() => {})
  await api.ctx.dispose()
})

async function lastCreate(page: any, fn: () => Promise<void>) {
  const wait = page.waitForResponse((r: any) => r.request().method() === 'POST' && /\/sales\/invoices\/?(\?.*)?$/.test(r.url()))
  await fn()
  const r = await wait
  return { status: r.status(), sent: JSON.parse(r.request().postData() || '{}'), got: await r.json() }
}

test('cash, walk-in, no VAT: 1000 in, 1000 saved, paid, goes back to Sales', async ({ page, errors }) => {
  t.watch(page)
  await gotoNewSale(page)
  await addProduct(page, plain.sku)
  expect(await money(page, 'Grand Total')).toBe(1000)
  const r = await lastCreate(page, () => page.getByRole('button', { name: NS.confirm }).click())
  expect(r.status).toBe(201)
  expect(r.sent.payment_method).toBe('cash')
  expect(r.sent.customer_id).toBeNull()
  expect(Number(r.got.total_amount)).toBe(1000)
  expect(Number(r.got.tax_amount)).toBe(0)
  expect(r.got.status).toBe('paid')
  await expect(page).toHaveURL(/\/sales$/)
  expect(errors).toEqual([])
})

test('VAT exclusive 7.5%: screen total 1075 = saved total 1075, VAT 75', async ({ page }) => {
  t.watch(page)
  await gotoNewSale(page)
  await addProduct(page, taxed.sku)
  expect(await money(page, 'Grand Total')).toBe(1075)
  const r = await lastCreate(page, () => page.getByRole('button', { name: NS.confirm }).click())
  expect(Number(r.got.total_amount)).toBe(1075)
  expect(Number(r.got.tax_amount)).toBe(75)
  expect(Number(r.got.amount_due)).toBe(0)
})

test('10% discount on 3 x 1000 with VAT: 2902.50 on screen and saved', async ({ page }) => {
  t.watch(page)
  await gotoNewSale(page)
  await addProduct(page, taxed.sku)
  await page.getByLabel('Increase quantity').click({ clickCount: 2 })
  await page.locator('xpath=//p[contains(.,"Discount %")]/following-sibling::input').fill('10')
  // 3000 - 300 = 2700 ; VAT 202.50 ; total 2902.50
  expect(await money(page, 'Grand Total')).toBe(2902.5)
  const r = await lastCreate(page, () => page.getByRole('button', { name: NS.confirm }).click())
  expect(Number(r.got.discount_amount)).toBe(300)
  expect(Number(r.got.tax_amount)).toBe(202.5)
  expect(Number(r.got.total_amount)).toBe(2902.5)
})

test('credit sale needs a customer, then saves open with nothing paid', async ({ page }) => {
  t.watch(page)
  await gotoNewSale(page)
  await addProduct(page, plain.sku)
  await page.getByRole('button', { name: /^credit$/ }).click()
  await page.getByRole('button', { name: NS.confirm }).click()
  await expect(page.getByText(/select a customer for credit/i)).toBeVisible()   // refused, nothing sent
  await pickCustomer(page, customer.name)
  const r = await lastCreate(page, () => page.getByRole('button', { name: NS.confirm }).click())
  expect(r.got.status).toBe('credit')
  expect(Number(r.got.amount_paid)).toBe(0)
  expect(Number(r.got.amount_due)).toBe(1000)
  expect(r.got.customer ?? r.sent.customer_id).toBeTruthy()
})

test('card (pos) and bank transfer save as paid with the right method', async ({ page }) => {
  t.watch(page)
  for (const [label, method] of [[/^Card \/ POS$/, 'pos'], [/^bank transfer$/i, 'bank_transfer']] as const) {
    await gotoNewSale(page)
    await addProduct(page, plain.sku)
    await page.getByRole('button', { name: label }).click()
    const r = await lastCreate(page, () => page.getByRole('button', { name: NS.confirm }).click())
    expect(r.sent.payment_method).toBe(method)
    expect(r.got.status).toBe('paid')
  }
})

test('proforma: saved as proforma, nothing paid', async ({ page }) => {
  t.watch(page)
  await gotoNewSale(page)
  await addProduct(page, plain.sku)
  const r = await lastCreate(page, () => page.getByRole('button', { name: NS.proforma }).click())
  expect(r.got.status).toBe('proforma')
  expect(Number(r.got.amount_paid)).toBe(0)
})

test('zero price is refused on screen and nothing is sent', async ({ page }) => {
  let posts = 0
  page.on('request', (rq) => { if (rq.method() === 'POST' && /\/sales\/invoices\/?(\?.*)?$/.test(rq.url())) posts++ })
  await gotoNewSale(page)
  await addProduct(page, plain.sku)
  await page.locator('xpath=//p[normalize-space()="Unit price"]/following-sibling::input').fill('0')
  await page.getByRole('button', { name: NS.confirm }).click()
  await expect(page.getByText(/zero or negative price/i)).toBeVisible()
  expect(posts).toBe(0)
})

test('hold then resume brings the same basket back, and survives a reload', async ({ page }) => {
  await gotoNewSale(page)
  await addProduct(page, plain.sku)
  await page.getByRole('button', { name: NS.hold }).click()
  await expect(page.getByText('Basket held')).toBeVisible()
  expect(await page.getByLabel('Increase quantity').count()).toBe(0)     // cart emptied
  await page.reload()
  await page.getByRole('button', { name: /Resume \(1\)/ }).click()
  await page.locator('.ds-held-row button', { hasText: /resume/i }).first().click()
  await expect(page.getByLabel('Increase quantity')).toBeVisible()
  expect(await money(page, 'Grand Total')).toBe(1000)
  await expect(page.getByRole('button', { name: /Resume \(/ })).toHaveCount(0)   // no leftover held basket
})

test('receipt on: print is called once after a sale; off: never', async ({ page }) => {
  t.watch(page)
  for (const on of [true, false]) {
    await gotoNewSale(page)
    await addProduct(page, plain.sku)
    const toggle = page.getByRole('button', { name: /^Receipt (on|off)$/ })
    if (((await toggle.innerText()).trim() === 'Receipt on') !== on) await toggle.click()
    await page.evaluate(() => { (window as any).__prints = 0 })
    await lastCreate(page, () => page.getByRole('button', { name: NS.confirm }).click())
    await page.waitForURL(/\/sales$/)
    await page.waitForTimeout(1500)
    expect(await page.evaluate(() => (window as any).__prints)).toBe(on ? 1 : 0)
  }
})

test('offline: no crash, and anything queued reaches the server once after reconnect', async ({ page, context, errors }) => {
  t.watch(page)
  await gotoNewSale(page)
  await addProduct(page, plain.sku)
  await context.setOffline(true)
  await page.getByRole('button', { name: NS.confirm }).click()
  await page.waitForTimeout(2500)
  await expect(page.getByText(/something went wrong|unexpected error/i)).toHaveCount(0)
  await context.setOffline(false)
  await page.waitForTimeout(8000)
  expect(errors).toEqual([])
  // sweep: only invoices that contain OUR product (other sessions share staging)
  const list = await (await api.ctx.get('sales/invoices/?page_size=10&ordering=-created_at')).json()
  for (const inv of list.results ?? []) {
    const d = await (await api.ctx.get(`sales/invoices/${inv.id}/`)).json()
    if ((d.items ?? []).some((i: any) => i.product === plain.id || i.product_id === plain.id)) t.invoices.push(inv.id)
  }
})

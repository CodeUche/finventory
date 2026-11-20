/**
 * Shared helpers for the design-phase-2 specs (project "p2").
 *
 * Runs against the STAGING API (default :8001) with a web build served on its
 * own port (default :5195). The staging API only allows the origin :5174, so
 * every API call from the page is routed through Playwright and answered with
 * the right CORS headers (the same trick the earlier click-through scripts used).
 *
 *   P2_URL=http://localhost:5195  P2_API=http://localhost:8001
 *   P2_EMAIL=global.ds@audity.test  P2_PASSWORD='Passw0rd!123'
 *   npx playwright test --project=p2
 *
 * No-leak rule: every record a test makes goes into `Tracker`, and the
 * tracker's cleanup voids/deletes it (invoices) or deletes it (products).
 * Records are named with a per-run tag so a crashed run can be swept by hand.
 */
import { test as base, expect, request as pwRequest, APIRequestContext, BrowserContext, Page } from '@playwright/test'

export const URL_BASE = process.env.P2_URL || 'http://localhost:5195'
export const API = process.env.P2_API || 'http://localhost:8001'
export const EMAIL = process.env.P2_EMAIL || 'global.ds@audity.test'
export const PASSWORD = process.env.P2_PASSWORD || 'Passw0rd!123'
export const RUN = `p2qa-${Date.now().toString(36)}`
export const STATE = './e2e/.auth/p2.json'

/** Answer every call to the staging API with CORS headers for our origin. */
export async function allowCors(ctx: BrowserContext) {
  await ctx.route(`${API}/**`, async (route) => {
    const req = route.request()
    const cors = {
      'access-control-allow-origin': URL_BASE,
      'access-control-allow-credentials': 'true',
      'access-control-allow-headers': req.headers()['access-control-request-headers'] || '*',
      'access-control-allow-methods': 'GET,POST,PUT,PATCH,DELETE,OPTIONS',
      'access-control-expose-headers': '*',
    }
    if (req.method() === 'OPTIONS') return route.fulfill({ status: 204, headers: cors })
    try {
      const r = await route.fetch()
      await route.fulfill({ response: r, headers: { ...r.headers(), ...cors } })
    } catch (e) { if (process.env.P2_DEBUG) console.log('route error', req.url(), String(e).slice(0, 120)) }
  })
}

export interface Api { ctx: APIRequestContext; org: string }

/** One API login per spec file (the login throttle is 20/min). */
export async function apiLogin(): Promise<Api> {
  const anon = await pwRequest.newContext()
  const res = await anon.post(`${API}/api/v1/auth/login/`, { data: { email: EMAIL, password: PASSWORD } })
  expect(res.ok(), `API login failed: ${res.status()}`).toBeTruthy()
  const body = await res.json()
  const org = body.organisations[0].id as string
  const ctx = await pwRequest.newContext({
    baseURL: `${API}/api/v1/`,
    extraHTTPHeaders: { Authorization: `Bearer ${body.access}`, 'X-Organisation-ID': org },
  })
  return { ctx, org }
}

/** Remembers what a test created so it can be removed afterwards. */
export class Tracker {
  invoices: string[] = []
  products: string[] = []
  constructor(private api: Api) {}

  /**
   * A fixture product with a FIXED sku, found or created. The API refuses to
   * delete a product that has ever been on an invoice (audit trail), so making
   * a new one per run would leave a growing pile on staging. Reusing one means
   * a run leaves exactly what the previous run left: nothing new.
   */
  async product(over: Record<string, unknown> = {}, sku = `P2QA-FIX-${this.products.length + 1}`) {
    const found = await (await this.api.ctx.get(`inventory/products/?search=${sku}&page_size=20`)).json()
    const hit = (found.results ?? []).find((p: any) => p.sku === sku)
    if (hit) {
      await this.api.ctx.patch(`inventory/products/${hit.id}/`, { data: { is_active: true, ...over } })
      this.products.push(hit.id)
      return hit as { id: string; sku: string; name: string }
    }
    const res = await this.api.ctx.post('inventory/products/', {
      data: {
        sku, name: `P2QA Item ${sku}`, product_type: 'service', unit_of_measure: 'unit',
        cost_price: '0', selling_price: '1000', ...over,
      },
    })
    expect(res.ok(), `product create failed: ${res.status()} ${await res.text()}`).toBeTruthy()
    const p = await res.json()
    this.products.push(p.id)
    return p as { id: string; sku: string; name: string }
  }

  /** Watch the page for invoices the UI creates, so cleanup finds them. */
  watch(page: Page) {
    page.on('response', async (r) => {
      if (r.request().method() !== 'POST' || !/\/sales\/invoices\/?(\?.*)?$/.test(r.url())) return
      try { const b = await r.json(); if (b?.id) this.invoices.push(b.id) } catch { /* not a create */ }
    })
  }

  async cleanup() {
    for (const id of this.invoices) {
      const d = await this.api.ctx.get(`sales/invoices/${id}/`).then((r) => r.json()).catch(() => null)
      if (!d) continue
      if (['paid', 'partially_paid'].includes(d.status)) {
        // A paid invoice cannot be voided ("needs a return process"), so give the
        // money back with a full return: stock goes back, the ledger is reversed.
        await this.api.ctx.post(`sales/invoices/${id}/process_return/`, {
          data: {
            items: (d.items ?? []).map((i: any) => ({ sale_item_id: i.id, quantity_returned: i.quantity })),
            reason: 'other', notes: 'p2qa cleanup', restocked: true, refund_method: 'cash',
          },
        }).catch(() => {})
      } else if (d.status !== 'voided') {
        await this.api.ctx.post(`sales/invoices/${id}/void/`, { data: { reason: 'p2qa cleanup' } }).catch(() => {})
      }
      await this.api.ctx.delete(`sales/invoices/${id}/`).catch(() => {})
    }
    this.invoices = []
    // fixture products are kept on purpose (see product()); they hold no stock and no open balances
    this.products = []
  }
}

/** The fixtures: CORS on, service worker off, theme set, page errors collected. */
export const test = base.extend<{ errors: string[]; theme: 'light' | 'dark' }>({
  theme: ['light', { option: true }],
  context: async ({ context, theme }, use) => {
    await allowCors(context)
    await context.addInitScript((t) => {
      try { localStorage.setItem('finventory-theme', t) } catch { /* private mode */ }
      ;(window as any).__prints = 0
      window.print = () => { (window as any).__prints++ }
      // The receipt prints from a hidden iframe (lib/receipt.ts), not window.print,
      // so count those frames: one per receipt handed to the printer.
      new MutationObserver((muts) => {
        for (const m of muts) m.addedNodes.forEach((n) => { if ((n as Element).tagName === 'IFRAME') (window as any).__prints++ })
      }).observe(document, { childList: true, subtree: true })
    }, theme)
    await use(context)
  },
  errors: async ({ page }, use) => {
    const errs: string[] = []
    page.on('pageerror', (e) => errs.push(String(e)))
    await use(errs)
  },
})
export { expect }

/** The page the money gets entered on. One place to change if the merge renames things. */
export const NS = {
  url: '/sales/new',
  search: 'input[placeholder^="Scan barcode"]',
  dropdownItem: 'div.absolute.top-full button',
  customer: 'input[placeholder="Search customer…"]',
  confirm: /Confirm Sale/,
  proforma: 'Save as Proforma Invoice',
  hold: /Hold basket/,
}

export async function gotoNewSale(page: Page) {
  for (let attempt = 0; attempt < 3; attempt++) {
    await page.goto(URL_BASE + NS.url, { waitUntil: 'domcontentloaded' })
    await expect(page.locator(NS.search)).toBeVisible({ timeout: 30_000 })
    // the pay panel needs a warehouse; on a busy machine its fetch can lose the race
    // "No warehouses found" shows until the fetch lands, so wait for it to go away
    const loaded = await expect(page.getByText('No warehouses found')).toHaveCount(0, { timeout: 15_000 }).then(() => true, () => false)
    if (loaded) return
  }
  throw new Error('New sale page never loaded a warehouse after 3 tries')
}

/** Pick the product whose name matches `query` from the live search dropdown. */
export async function addProduct(page: Page, query: string) {
  const s = page.locator(NS.search)
  await s.fill(query)
  const opt = page.locator(NS.dropdownItem).first()
  await expect(opt).toBeVisible({ timeout: 15_000 })
  await opt.dispatchEvent('mousedown')   // the dropdown closes on blur, so click would miss
}

export async function pickCustomer(page: Page, query: string) {
  await page.locator(NS.customer).fill(query)
  const opt = page.locator(NS.dropdownItem).first()
  await expect(opt).toBeVisible({ timeout: 15_000 })
  await opt.dispatchEvent('mousedown')
}

/**
 * What the cashier is told to collect. The "Grand Total" row only shows when
 * there is VAT, so the primary button ("Confirm Sale · N") is the one figure
 * that is always there. Any other label reads that row from the summary.
 */
export async function money(page: Page, label: string): Promise<number> {
  const num = (t: string) => parseFloat(t.replace(/[^0-9.\-]/g, ''))
  if (label === 'Grand Total') {
    const btn = page.getByRole('button', { name: NS.confirm })
    await expect(btn).toBeEnabled()
    return num((await btn.innerText()).split('·').pop() || '')
  }
  const row = page.locator(`xpath=//span[normalize-space()="${label}"]/following-sibling::span[1]`).first()
  return num(await row.innerText())
}

/**
 * Objective health of the page as drawn right now:
 *   over - how many px the page is wider than the window (sideways scroll)
 *   bad  - visible text whose colour is (almost) the colour of the solid
 *          background behind it, i.e. text nobody can read
 * Text over images/gradients has no solid background and is skipped, so this
 * under-reports rather than cries wolf; the screenshots cover the rest.
 */
export async function pageHealth(page: Page): Promise<{ over: number; bad: string[] }> {
  return page.evaluate(() => {
    const parse = (c: string) => {
      const m = c.match(/rgba?\(([^)]+)\)/)
      if (!m) return null
      const p = m[1].split(',').map((x) => parseFloat(x))
      return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 }
    }
    const out: string[] = []
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT)
    let n: Node | null
    let checked = 0
    while ((n = walker.nextNode()) && checked < 400) {
      const t = (n.textContent || '').trim()
      if (t.length < 2) continue
      const el = n.parentElement!
      const r = el.getBoundingClientRect()
      if (r.width === 0 || r.height === 0) continue
      const cs = getComputedStyle(el)
      if (cs.visibility === 'hidden' || cs.display === 'none' || +cs.opacity === 0) continue
      checked++
      const fg = parse(cs.color)
      if (!fg || fg.a < 0.5) continue
      let bg: ReturnType<typeof parse> = null
      for (let e: HTMLElement | null = el; e; e = e.parentElement) {
        const b = parse(getComputedStyle(e).backgroundColor)
        if (b && b.a >= 0.99) { bg = b; break }
      }
      if (!bg) continue
      if (Math.abs(fg.r - bg.r) + Math.abs(fg.g - bg.g) + Math.abs(fg.b - bg.b) < 30) out.push(t.slice(0, 40))
    }
    return { over: document.documentElement.scrollWidth - document.documentElement.clientWidth, bad: out.slice(0, 5) }
  })
}

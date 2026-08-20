/**
 * Browser click-through for the POS receipt work.
 *
 * Covers the three things that can only be proven in a running app rather than
 * in a unit test:
 *   1. The Receipt Layout picker exists, offers the six templates, and a choice
 *      actually persists to the backend (not just to local component state).
 *   2. The Payments settings tab is reachable again, so a merchant can enter
 *      their own gateway keys. It was commented out of the tab list, which is
 *      what made "Paystack secret key is missing" unrecoverable from the UI.
 *   3. The organisation in the client store carries `address`, `phone` and
 *      `tax_id`. The login response used to omit them, so every receipt printed
 *      with the business name and nothing else. A unit test cannot catch that —
 *      the data was missing before it ever reached the renderer.
 */
import { test, expect, Page } from '@playwright/test'

const EMAIL = process.env.E2E_RECEIPTS_EMAIL || 'ui.test@audity.test'
const PW = process.env.E2E_RECEIPTS_PASSWORD || 'Passw0rd!123'

// One context for the file: a login per test burns the authenticated
// 1000/hour throttle, after which the org fetch 429s and the app silently
// degrades in ways that look like permission bugs.
test.describe.configure({ mode: 'serial' })

async function login(page: Page) {
  await page.goto('/dashboard', { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(1500)
  if (/\/dashboard/.test(page.url())) return

  await page.goto('/login', { waitUntil: 'domcontentloaded' })
  await page.locator('input[type="email"]').first().fill(EMAIL)
  await page.locator('input[type="password"]').first().fill(PW)
  await page.locator('button[type="submit"]').first().click()
  await expect(page).toHaveURL(/\/dashboard/, { timeout: 45_000 })
}

/** Read the persisted organisation once it has more than the login stub. */
async function hydratedOrg(page: Page) {
  await page.waitForFunction(() => {
    const raw = localStorage.getItem('finventory-auth')
    const org = raw ? JSON.parse(raw)?.state?.organisation : null
    // Login deliberately returns {id, onboarding_completed} and AppLayout
    // backfills the rest, so wait for the backfill rather than racing it.
    return !!org && 'address' in org
  }, undefined, { timeout: 45_000 })

  return page.evaluate(() => {
    const raw = localStorage.getItem('finventory-auth')
    return JSON.parse(raw || '{}')?.state?.organisation ?? null
  })
}

test('the organisation reaching the client carries what a receipt header needs', async ({ page }) => {
  await login(page)
  const org = await hydratedOrg(page)

  expect(org, 'no organisation in the client store').toBeTruthy()
  // Everything the receipt header prints has to survive into the client store,
  // because the print sites read it from there and never re-fetch.
  expect(Object.keys(org)).toEqual(expect.arrayContaining(['address', 'phone', 'tax_id']))
  expect(org).toHaveProperty('receipt_template')
  expect(String(org.address || ''), 'seeded org should carry an address').toContain('Admiralty')
})

test('the receipt layout picker offers six templates and the choice sticks', async ({ page }) => {
  await login(page)
  await page.goto('/settings?tab=invoice_templates', { waitUntil: 'domcontentloaded' })

  const card = page.locator('div.card', { hasText: 'Receipt Layout Template' }).first()
  await expect(card).toBeVisible({ timeout: 30_000 })

  for (const name of ['Compact', 'Detailed', 'Branded', 'Classic cash', 'Shop & barcode', 'Stay folio']) {
    await expect(card.getByText(name, { exact: true })).toBeVisible()
  }

  await card.getByText('Detailed', { exact: true }).click()
  await expect(page.getByText(/Receipt template saved/i)).toBeVisible({ timeout: 20_000 })

  // Reload: a picker that only moved component state would lose this.
  await page.reload({ waitUntil: 'domcontentloaded' })
  await page.goto('/settings?tab=invoice_templates', { waitUntil: 'domcontentloaded' })
  const reloaded = page.locator('div.card', { hasText: 'Receipt Layout Template' }).first()
  await expect(reloaded).toBeVisible({ timeout: 30_000 })

  const stored = (await hydratedOrg(page))?.receipt_template
  expect(stored).toBe('detailed')

  await page.screenshot({ path: 'e2e/.scratch/receipt-templates.png', fullPage: true })
})

test('the branded template reveals its own closing message field', async ({ page }) => {
  await login(page)
  await page.goto('/settings?tab=invoice_templates', { waitUntil: 'domcontentloaded' })

  const card = page.locator('div.card', { hasText: 'Receipt Layout Template' }).first()
  await expect(card).toBeVisible({ timeout: 30_000 })

  // Establish the starting point rather than assuming one — this file runs
  // serially and an earlier test leaves its own choice behind.
  await card.getByText('Compact', { exact: true }).click()
  await expect(card.getByText('Closing message', { exact: true })).toHaveCount(0)

  await card.getByText('Branded', { exact: true }).click()
  await expect(card.getByText('Closing message', { exact: true })).toBeVisible({ timeout: 20_000 })

  // And it goes away again, so the field belongs to the template rather than
  // being switched on permanently by the first visit.
  await card.getByText('Compact', { exact: true }).click()
  await expect(card.getByText('Closing message', { exact: true })).toHaveCount(0)
})

test('payments settings are reachable, so merchant keys can be entered', async ({ page }) => {
  await login(page)
  // Landing here also opens the FINANCE settings group in the sidebar, so the
  // nav entry can be checked in the same pass.
  await page.goto('/settings?tab=payments', { waitUntil: 'domcontentloaded' })

  // Reachable by navigation, not just by typing the URL: the tab was missing
  // from the sidebar list as well as from the settings tab list.
  await expect(page.locator('a[href="/settings?tab=payments"]')).toBeVisible({ timeout: 30_000 })

  await expect(page.getByText('Paystack Integration')).toBeVisible({ timeout: 20_000 })
  await expect(page.getByPlaceholder(/pk_live/)).toBeVisible()
  await expect(page.getByPlaceholder(/sk_live/)).toBeVisible()

  await page.screenshot({ path: 'e2e/.scratch/payments-tab.png', fullPage: true })
})

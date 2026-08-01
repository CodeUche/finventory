/**
 * Browser E2E for the public storefront (Phase 3).
 *
 * The critical property is that a customer reaches all of this with NO
 * session, so these tests deliberately run in a fresh context with the stored
 * login cleared — if any of it depended on being signed in, they would fail.
 */
import { test, expect, Page } from '@playwright/test'

// No storageState: this is the open internet, not a signed-in staff member.
test.use({ storageState: { cookies: [], origins: [] } })
test.describe.configure({ mode: 'serial' })

const SHOP = '/s/kates-stores'

async function openShop(page: Page) {
  await page.goto(SHOP)
  await expect(page.getByText("Kate's Stores").first()).toBeVisible({ timeout: 25_000 })
}

async function addRice(page: Page) {
  await page.getByRole('button', { name: /Add to basket/ }).first().click()
  await page.getByRole('button', { name: /Basket|^1$/ }).first().click()
}

test('a customer reaches the shop without logging in', async ({ page }) => {
  await openShop(page)
  // Not bounced to the login screen.
  await expect(page).toHaveURL(/\/s\/kates-stores/)
  await expect(page.getByPlaceholder('you@company.com')).toHaveCount(0)
  await expect(page.getByText('Provisions in Ikeja')).toBeVisible()
})

test('the shop shows no Audity staff navigation', async ({ page }) => {
  await openShop(page)
  for (const item of ['ACCOUNTING & FINANCE', 'GENERAL REPORTS', 'Dashboard', 'Sign out']) {
    await expect(page.getByText(item, { exact: true })).toHaveCount(0)
  }
})

test('the catalogue never shows cost price', async ({ page }) => {
  await openShop(page)
  await expect(page.getByText('Rice 5kg').first()).toBeVisible()
  await expect(page.getByText('9,200.00').first()).toBeVisible()   // selling price
  await expect(page.getByText(/6,000/)).toHaveCount(0)             // cost price
})

test('an unknown shop says so rather than erroring', async ({ page }) => {
  await page.goto('/s/no-such-shop-anywhere')
  await expect(page.getByText(/isn.t available/i)).toBeVisible({ timeout: 25_000 })
})

test('a customer can fill a basket and see the total', async ({ page }) => {
  await openShop(page)
  await addRice(page)
  await expect(page.getByRole('heading', { name: 'Your basket' })).toBeVisible()
  await expect(page.getByText('9,200.00').first()).toBeVisible()
})

test('the order form asks for a name and phone before it will send', async ({ page }) => {
  await openShop(page)
  await addRice(page)
  await page.getByRole('button', { name: /^Place order$/ }).click()
  await expect(page.getByText(/tell us your name/i)).toBeVisible()

  await page.getByPlaceholder('Your name').fill('Ada Buyer')
  await page.getByRole('button', { name: /^Place order$/ }).click()
  await expect(page.getByText(/phone number/i).first()).toBeVisible()
})

test('delivery asks where to deliver', async ({ page }) => {
  await openShop(page)
  await addRice(page)
  await page.getByRole('button', { name: /^delivery$/i }).click()
  await expect(page.getByPlaceholder(/Where should we deliver/)).toBeVisible()
})

test('placing an order returns a reference the customer can quote', async ({ page }) => {
  await openShop(page)
  await addRice(page)
  await page.getByPlaceholder('Your name').fill('Ada Buyer')
  await page.getByPlaceholder('Phone number').fill('08030000000')
  await page.getByRole('button', { name: /^Place order$/ }).click()

  await expect(page.getByRole('heading', { name: 'Order placed' })).toBeVisible({ timeout: 30_000 })
  const reference = await page.locator('p.font-mono').first().innerText()
  expect(reference.trim()).toHaveLength(8)
  // Readable over the phone — no confusable characters.
  expect(reference).not.toMatch(/[IO01]/)
})

test('the reference can be used to track the order, still with no login', async ({ page }) => {
  await openShop(page)
  await addRice(page)
  await page.getByPlaceholder('Your name').fill('Ada Buyer')
  await page.getByPlaceholder('Phone number').fill('08030000000')
  await page.getByRole('button', { name: /^Place order$/ }).click()
  await expect(page.getByRole('heading', { name: 'Order placed' })).toBeVisible({ timeout: 30_000 })

  const reference = (await page.locator('p.font-mono').first().innerText()).trim()
  await page.goto(`${SHOP}/order/${reference}`)

  await expect(page.getByText(reference)).toBeVisible({ timeout: 25_000 })
  await expect(page.getByText('Placed')).toBeVisible()
  await expect(page.getByText('Rice 5kg')).toBeVisible()
})

test('a QR table link marks the order as table service', async ({ page }) => {
  await page.goto(`${SHOP}/t/T4`)
  await expect(page.getByText("Kate's Stores").first()).toBeVisible({ timeout: 25_000 })
  await expect(page.getByText(/Table T4/)).toBeVisible()
})

/**
 * Browser E2E for the retail counter (Phase 2).
 *
 * Scan-and-go behaviour on the POS: a scanned barcode goes straight into the
 * basket without the cashier picking from a list, baskets can be parked and
 * resumed, and weighed goods keep their decimal quantity.
 */
import { test, expect, Page } from '@playwright/test'

test.describe.configure({ mode: 'serial' })

async function goPos(page: Page) {
  await page.goto('/sales/new')
  await expect(page.getByPlaceholder(/Scan barcode/)).toBeVisible({ timeout: 25_000 })
}

/** Scan a code the way a hardware scanner does: type it, then Enter immediately.
 *  No pause on purpose — a scanner fires Enter within milliseconds, and that
 *  race is precisely what used to drop the scan. */
async function scan(page: Page, code: string) {
  const box = page.getByPlaceholder(/Scan barcode/)
  await box.fill(code)
  await box.press('Enter')
}

/** The cart panel — scoped so assertions can't match a toast that names the same product. */
const cart = (page: Page) => page.locator('div.card').filter({ hasText: 'Cart' }).first()

test('scanning a barcode drops the item straight into the basket', async ({ page }) => {
  await goPos(page)
  await scan(page, '00999')
  // Straight in — no dropdown to choose from.
  await expect(cart(page).getByText('Rice 5kg')).toBeVisible({ timeout: 25_000 })
})

test('an unknown code says so instead of failing silently', async ({ page }) => {
  await goPos(page)
  await scan(page, 'NOT-A-REAL-BARCODE')
  await expect(page.getByText(/Nothing found/i)).toBeVisible({ timeout: 25_000 })
})

test('a weighed item keeps its decimal quantity', async ({ page }) => {
  await goPos(page)
  await scan(page, '00999')
  await expect(cart(page).getByText('Rice 5kg')).toBeVisible({ timeout: 25_000 })

  // 1.42 kg must survive — rounding to 1 or 2 misprices every weighed sale.
  const qty = page.locator('input[type="number"], input[inputmode="decimal"]').first()
  await qty.fill('1.42')
  await qty.blur()
  await expect(qty).toHaveValue(/1\.42/)
})

test('a basket can be held and resumed', async ({ page }) => {
  await goPos(page)
  await scan(page, '00999')
  await expect(cart(page).getByText('Rice 5kg')).toBeVisible({ timeout: 25_000 })

  await page.getByRole('button', { name: /Hold basket/ }).click()
  await expect(page.getByText(/Basket held/i)).toBeVisible({ timeout: 25_000 })

  // Parked, so the counter is clear for the next customer.
  await expect(page.getByRole('button', { name: /Resume \(/ })).toBeVisible()
  await page.getByRole('button', { name: /Resume \(/ }).click()
  await page.getByRole('button', { name: /^Resume$/ }).first().click()

  await expect(page.getByText(/Basket resumed/i)).toBeVisible({ timeout: 25_000 })
  await expect(cart(page).getByText('Rice 5kg')).toBeVisible()
})

test('holding an empty basket is refused', async ({ page }) => {
  await goPos(page)
  await page.getByRole('button', { name: /Hold basket/ }).click()
  await expect(page.getByText(/Nothing to hold/i)).toBeVisible({ timeout: 25_000 })
})

test('the receipt toggle is remembered on the device', async ({ page }) => {
  await goPos(page)
  const toggle = page.getByRole('button', { name: /Receipt (on|off)/ })
  const before = await toggle.innerText()
  await toggle.click()
  await expect(toggle).not.toHaveText(before)

  const afterClick = await toggle.innerText()
  await page.reload()
  await expect(page.getByRole('button', { name: /Receipt (on|off)/ })).toHaveText(afterClick)
})

test('the cashier is warned when no till is open', async ({ page }) => {
  await goPos(page)
  // The payments fixture leaves no till open, so the warning must be showing.
  await expect(page.getByText(/No till is open/i)).toBeVisible({ timeout: 25_000 })
  await expect(page.getByRole('button', { name: /Open a till/ })).toBeVisible()
})

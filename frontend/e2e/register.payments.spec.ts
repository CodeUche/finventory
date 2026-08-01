/**
 * Browser E2E for the dedicated Register (Phase 2e).
 *
 * The register is the locked-down till surface. What matters here is as much
 * what it does NOT show — cost price, margin, price editing, credit sales,
 * app navigation — as what it does.
 */
import { test, expect, Page } from '@playwright/test'

test.describe.configure({ mode: 'serial' })

async function goRegister(page: Page) {
  await page.goto('/pos/register')
  await expect(page.getByPlaceholder(/Scan barcode or search/)).toBeVisible({ timeout: 25_000 })
}

async function scan(page: Page, code: string) {
  const box = page.getByPlaceholder(/Scan barcode or search/)
  await box.fill(code)
  await box.press('Enter')
}

const basket = (page: Page) => page.locator('aside').first()

test('the register opens full screen with no app sidebar', async ({ page }) => {
  await goRegister(page)
  // The sidebar's nav groups must not be reachable — a cashier stays put.
  await expect(page.getByText('ACCOUNTING & FINANCE', { exact: true })).toHaveCount(0)
  await expect(page.getByText('GENERAL REPORTS', { exact: true })).toHaveCount(0)
  await expect(page.getByText('Register', { exact: true }).first()).toBeVisible()
})

test('scanning adds to the basket', async ({ page }) => {
  await goRegister(page)
  await scan(page, '00999')
  await expect(basket(page).getByText('Rice 5kg')).toBeVisible({ timeout: 25_000 })
})

test('it shows the selling price but never cost or margin', async ({ page }) => {
  await goRegister(page)
  await scan(page, '00999')
  await expect(basket(page).getByText('Rice 5kg')).toBeVisible({ timeout: 25_000 })

  // Seeded cost is 6,000 and selling is 9,200 — the cost must appear nowhere.
  await expect(page.getByText('9,200').first()).toBeVisible()
  await expect(page.getByText(/6,000/)).toHaveCount(0)
  await expect(page.getByText(/margin/i)).toHaveCount(0)
  await expect(page.getByText(/cost/i)).toHaveCount(0)
})

test('a cashier cannot sell on credit from the register', async ({ page }) => {
  await goRegister(page)
  await expect(page.getByRole('button', { name: 'Cash', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Card', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Transfer', exact: true })).toBeVisible()
  // Credit is an owner decision, not a counter one.
  await expect(page.getByRole('button', { name: /credit/i })).toHaveCount(0)
})

test('change is worked out from the cash tendered', async ({ page }) => {
  await goRegister(page)
  await scan(page, '00999')
  await expect(basket(page).getByText('Rice 5kg')).toBeVisible({ timeout: 25_000 })

  await page.getByPlaceholder(/Cash tendered/).fill('10000')
  await expect(page.getByText(/Change/)).toBeVisible()
  await expect(page.getByText('800').first()).toBeVisible()
})

test('quantity accepts a weighed decimal', async ({ page }) => {
  await goRegister(page)
  await scan(page, '00999')
  await expect(basket(page).getByText('Rice 5kg')).toBeVisible({ timeout: 25_000 })

  const qty = basket(page).locator('input[inputmode="decimal"]').first()
  await qty.fill('1.42')
  await expect(qty).toHaveValue(/1\.42/)
})

test('a basket can be held and resumed', async ({ page }) => {
  await goRegister(page)
  await scan(page, '00999')
  await expect(basket(page).getByText('Rice 5kg')).toBeVisible({ timeout: 25_000 })

  await page.getByRole('button', { name: /^Hold$/ }).click()
  await expect(page.getByText(/Basket held/i)).toBeVisible({ timeout: 25_000 })
  await expect(basket(page).getByText('Scan an item to begin')).toBeVisible()

  await page.getByRole('button', { name: /Resume 1 item/ }).click()
  await expect(basket(page).getByText('Rice 5kg')).toBeVisible()
})

test('the till state is shown so cash is never taken blind', async ({ page }) => {
  await goRegister(page)
  await expect(page.getByText(/No till open/i)).toBeVisible({ timeout: 25_000 })
})

test('an empty basket cannot be tendered', async ({ page }) => {
  await goRegister(page)
  await expect(page.getByRole('button', { name: 'Cash', exact: true })).toBeDisabled()
})

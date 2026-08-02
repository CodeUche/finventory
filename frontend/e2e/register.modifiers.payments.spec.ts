/**
 * Browser E2E for product modifiers (Phase 5) on the dedicated Register.
 *
 * Seeded fixture: "Jollof Combo" (barcode 00998) carries two modifier groups —
 * a required single-choice "Size" (Small default / Large +500) and an
 * optional "Extras" (Extra chicken +300). "Rice 5kg" (00999) deliberately
 * carries none, so the existing scan-straight-in behaviour stays covered.
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

test('a product with modifier groups opens the picker instead of adding straight away', async ({ page }) => {
  await goRegister(page)
  await scan(page, '00998')
  await expect(page.getByText('Required', { exact: true })).toBeVisible({ timeout: 25_000 })
  await expect(basket(page).getByText('Jollof Combo')).toHaveCount(0)
})

test('a required group blocks confirm until answered', async ({ page }) => {
  await goRegister(page)
  await scan(page, '00998')
  await expect(page.getByText('Required', { exact: true })).toBeVisible({ timeout: 25_000 })

  // "Small" comes pre-selected as the group default — deselect it to leave
  // the required group empty.
  await page.getByRole('button', { name: /Small/ }).click()
  await page.getByRole('button', { name: 'Add to basket' }).click()
  await expect(page.getByText(/Please choose size/i)).toBeVisible()
  // The picker must still be open — nothing should have reached the basket.
  await expect(page.getByText('Required', { exact: true })).toBeVisible()
  await expect(basket(page).getByText('Jollof Combo')).toHaveCount(0)
})

test('choosing Large + Extra chicken prices and labels the basket line correctly', async ({ page }) => {
  await goRegister(page)
  await scan(page, '00998')
  await expect(page.getByText('Required', { exact: true })).toBeVisible({ timeout: 25_000 })

  await page.getByRole('button', { name: /Large/ }).click()
  await page.getByRole('button', { name: /Extra chicken/ }).click()
  await page.getByRole('button', { name: 'Add to basket' }).click()

  await expect(basket(page).getByText('Jollof Combo')).toBeVisible({ timeout: 25_000 })
  await expect(basket(page).getByText('Large, Extra chicken')).toBeVisible()
  // Base 2,000 + Large 500 + Extra chicken 300 = 2,800.
  await expect(basket(page).getByText('2,800').first()).toBeVisible()
})

test('two differently-modified instances of the same product stay as separate basket rows', async ({ page }) => {
  await goRegister(page)
  await scan(page, '00998')
  await expect(page.getByText('Required', { exact: true })).toBeVisible({ timeout: 25_000 })
  // Accept the default (Small, no extras).
  await page.getByRole('button', { name: 'Add to basket' }).click()
  await expect(basket(page).getByText('Jollof Combo')).toBeVisible({ timeout: 25_000 })

  await scan(page, '00998')
  await expect(page.getByText('Required', { exact: true })).toBeVisible({ timeout: 25_000 })
  await page.getByRole('button', { name: /Large/ }).click()
  await page.getByRole('button', { name: 'Add to basket' }).click()

  await expect(basket(page).getByText('Jollof Combo')).toHaveCount(2)
  await expect(basket(page).getByText('Large').first()).toBeVisible()
})

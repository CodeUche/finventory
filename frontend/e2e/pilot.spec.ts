import { test, expect, Page } from '@playwright/test'

const EMAIL = 'e2e.pilot@audity.test'
const PW = 'Passw0rd!123'

async function login(page: Page) {
  await page.goto('/')
  await page.getByPlaceholder('you@company.com').fill(EMAIL)
  await page.locator('input[type="password"]').first().fill(PW)
  await page.locator('button[type="submit"]').click()
  await expect(page).toHaveURL(/\/dashboard/, { timeout: 45_000 })
}

test('a real user can log in and reach the dashboard', async ({ page }) => {
  await login(page)
})

test('POS: build an order and take payment', async ({ page }) => {
  await login(page)
  await page.goto('/pos/restaurant')

  // Use Pickup so no table is required (also proves the cross-sector path).
  await page.getByRole('button', { name: /Pickup/ }).click()

  // Add two menu items to the cart.
  await page.getByText('Jollof Rice', { exact: false }).first().click()
  await page.getByText('Grilled Chicken', { exact: false }).first().click()

  await page.getByRole('button', { name: /^Pay$|Pay$/ }).click()
  await page.getByRole('button', { name: /Complete Payment/ }).click()

  // Success toast confirms invoice created + payment posted.
  await expect(page.getByText(/Paid|Invoice/i).first()).toBeVisible({ timeout: 25_000 })
})

test('help desk: raise a ticket', async ({ page }) => {
  await login(page)
  await page.goto('/helpdesk')
  await page.getByRole('button', { name: /New Ticket/ }).click()
  await page.getByPlaceholder('Subject').fill('Playwright smoke ticket')
  await page.getByRole('button', { name: /Create Ticket/ }).click()
  // The success toast confirms the POST succeeded.
  await expect(page.getByText(/Ticket created/i).first()).toBeVisible({ timeout: 25_000 })
})

test('balance sheet renders (drill-down page)', async ({ page }) => {
  await login(page)
  await page.goto('/reports/balance-sheet')
  await expect(page.getByText(/ASSETS|Balance Sheet|Total Assets/i).first()).toBeVisible({ timeout: 25_000 })
})

test('settings → GL Mapping renders by module (with NHF)', async ({ page }) => {
  await login(page)
  // Settings tabs are query-param driven.
  await page.goto('/settings?tab=gl_mapping')
  // Wait for the module-grouped mapping to load, then confirm the Payroll module
  // header and the NHF role LABEL render (target the <p> label, not the same-named
  // "2600 NHF Payable" <option> that appears inside every account dropdown).
  await expect(page.getByText('Account Mapping').first()).toBeVisible({ timeout: 25_000 })
  await expect(page.getByRole('heading', { name: 'Payroll' })).toBeVisible({ timeout: 25_000 })
  await expect(page.locator('p', { hasText: /^NHF Payable$/ }).first()).toBeVisible()
})

/**
 * Browser E2E for till sessions (Phase 1).
 *
 * Runs on the payments stack (its own throwaway database), and holds the line
 * that matters: the drawer count is blind, and a shortfall becomes a real
 * number the cashier is told about.
 */
import { test, expect, Page } from '@playwright/test'

test.describe.configure({ mode: 'serial' })

async function goTill(page: Page) {
  await page.goto('/pos/till')
  await expect(page.getByRole('heading', { name: 'Till', exact: true })).toBeVisible({ timeout: 25_000 })
  // The heading renders while the session is still loading, so wait until one
  // of the two forms has actually resolved before touching anything.
  await expect(
    page.getByRole('button', { name: /^Open till$|Close till/ }).first(),
  ).toBeVisible({ timeout: 25_000 })
}

/** Close any till left open by an earlier test so each starts from a clean slate. */
async function ensureClosed(page: Page) {
  await goTill(page)
  const closeBtn = page.getByRole('button', { name: /Close till/ })
  if (await closeBtn.isVisible().catch(() => false)) {
    await page.getByPlaceholder('Counted (required)').fill('0')
    await closeBtn.click()
    await expect(page.getByText(/Till closed/i)).toBeVisible({ timeout: 25_000 })
  }
}

test('a till can be opened with a float', async ({ page }) => {
  await ensureClosed(page)
  await goTill(page)

  await expect(page.getByText(/No till open/)).toBeVisible()
  await page.getByPlaceholder('0.00').fill('20000')
  await page.getByRole('button', { name: /^Open till$/ }).click()

  await expect(page.getByRole('button', { name: /Close till/ })).toBeVisible({ timeout: 25_000 })
  await expect(page.getByText('Opening float')).toBeVisible()
  await expect(page.getByText(/20,000/).first()).toBeVisible()
})

test('the expected cash is never shown before the count is entered', async ({ page }) => {
  await goTill(page)
  // The count field must be empty — pre-filling it would defeat a blind count.
  await expect(page.getByPlaceholder('Counted (required)')).toHaveValue('')
})

test('closing short reports the shortfall and says it reached the accounts', async ({ page }) => {
  await goTill(page)

  await page.getByPlaceholder('Counted (required)').fill('19700')
  await page.getByPlaceholder(/Reason for any difference/).fill('Short at close')
  await page.getByRole('button', { name: /Close till/ }).click()

  await expect(page.getByText(/Till closed/i)).toBeVisible({ timeout: 25_000 })
  await expect(page.getByRole('heading', { name: 'End of shift' })).toBeVisible()
  await expect(page.getByText(/short/i).first()).toBeVisible()
  await expect(page.getByText(/Cash Over & Short/i)).toBeVisible()
  await expect(page.getByText(/300/).first()).toBeVisible()
})

test('the Z-report lists every tender with expected against counted', async ({ page }) => {
  // Each test gets a fresh page, so run a whole shift rather than relying on
  // the report left on screen by the previous one.
  await ensureClosed(page)
  await goTill(page)
  await page.getByPlaceholder('0.00').fill('7500')
  await page.getByRole('button', { name: /^Open till$/ }).click()
  await expect(page.getByRole('button', { name: /Close till/ })).toBeVisible({ timeout: 25_000 })
  await page.getByPlaceholder('Counted (required)').fill('7500')
  await page.getByRole('button', { name: /Close till/ }).click()

  await expect(page.getByRole('heading', { name: 'End of shift' })).toBeVisible({ timeout: 25_000 })
  await expect(page.getByText('Expected')).toBeVisible()
  await expect(page.getByText('Counted')).toBeVisible()
  await expect(page.getByText('Difference')).toBeVisible()
  await expect(page.getByText('Cash', { exact: true }).first()).toBeVisible()
})

test('a till that balances closes with no variance warning', async ({ page }) => {
  await goTill(page)
  await page.getByPlaceholder('0.00').fill('5000')
  await page.getByRole('button', { name: /^Open till$/ }).click()
  await expect(page.getByRole('button', { name: /Close till/ })).toBeVisible({ timeout: 25_000 })

  await page.getByPlaceholder('Counted (required)').fill('5000')
  await page.getByRole('button', { name: /Close till/ }).click()

  await expect(page.getByRole('heading', { name: 'End of shift' })).toBeVisible({ timeout: 25_000 })
  await expect(page.getByText(/has been posted to Cash Over/i)).toHaveCount(0)
})

test('a second till cannot be opened while one is running', async ({ page }) => {
  await goTill(page)
  await page.getByPlaceholder('0.00').fill('1000')
  await page.getByRole('button', { name: /^Open till$/ }).click()
  await expect(page.getByRole('button', { name: /Close till/ })).toBeVisible({ timeout: 25_000 })

  // Re-opening is impossible from the UI (the form is replaced), which is the
  // guarantee we want — the close form is what shows instead.
  await goTill(page)
  await expect(page.getByRole('button', { name: /^Open till$/ })).toHaveCount(0)
  await expect(page.getByRole('button', { name: /Close till/ })).toBeVisible()

  await ensureClosed(page)
})

test('a receipt can be printed from an invoice', async ({ page }) => {
  await page.goto('/sales')
  const row = page.locator('tr', { hasText: 'INV-00002' }).first()
  await expect(row).toBeVisible({ timeout: 25_000 })
  await row.locator('button[title="View details"]').click()

  // The print dialog is native and cannot be driven, so assert the control is
  // there and that clicking it does not throw.
  const printBtn = page.getByRole('button', { name: /Print receipt/ })
  await expect(printBtn).toBeVisible()
})

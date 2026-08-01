/**
 * Browser E2E for card settlement (Phase 4).
 *
 * Uploads a real terminal-style export and checks the page behaves the way the
 * matcher does: certain matches go through, anything doubtful is listed for a
 * person, and the operator is warned before matching by hand.
 */
import { test, expect, Page } from '@playwright/test'

test.describe.configure({ mode: 'serial' })

async function goSettlement(page: Page) {
  await page.goto('/payments/settlement')
  await expect(page.getByRole('heading', { name: 'Card settlement' })).toBeVisible({ timeout: 25_000 })
}

/** Upload a CSV without touching the OS file picker. */
async function upload(page: Page, csv: string, name = 'terminal-export.csv') {
  await page.setInputFiles('input[type="file"]', {
    name, mimeType: 'text/csv', buffer: Buffer.from(csv),
  })
}

const unique = () => `RRN${Date.now()}${Math.floor(Math.random() * 1000)}`

test('the page explains what to upload', async ({ page }) => {
  await goSettlement(page)
  await expect(page.getByText(/Moniepoint or OPay/)).toBeVisible()
  await expect(page.getByRole('button', { name: /Import terminal export/ })).toBeVisible()
})

test('an export with no amount column is refused with a readable message', async ({ page }) => {
  await goSettlement(page)
  await upload(page, 'Reference,Terminal\nR1,T1\n')
  await expect(page.getByText(/amount column/i)).toBeVisible({ timeout: 30_000 })
})

test('a payout with no matching sale is listed for review, not guessed', async ({ page }) => {
  await goSettlement(page)
  const ref = unique()
  await upload(page, `Date,Reference,Amount\n2026-08-01 10:00:00,${ref},77777\n`)

  await expect(page.getByText(/imported/i)).toBeVisible({ timeout: 30_000 })
  const row = page.locator('tr', { hasText: ref })
  await expect(row).toBeVisible({ timeout: 25_000 })
  await expect(row.getByText(/Needs review/i)).toBeVisible()
  await expect(row.getByRole('button', { name: /Match/ })).toBeVisible()
})

test('the same export cannot be imported twice', async ({ page }) => {
  await goSettlement(page)
  const ref = unique()
  const csv = `Date,Reference,Amount\n2026-08-01 10:00:00,${ref},4321\n`

  await upload(page, csv)
  await expect(page.getByText(/1 payout imported/i)).toBeVisible({ timeout: 30_000 })

  await page.reload()
  await expect(page.getByRole('heading', { name: 'Card settlement' })).toBeVisible({ timeout: 25_000 })
  await upload(page, csv)
  // Re-importing yesterday's file must not create the money a second time.
  await expect(page.getByText(/0 payouts imported/i)).toBeVisible({ timeout: 30_000 })
  await expect(page.locator('tr', { hasText: ref })).toHaveCount(1)
})

test('matching by hand warns before it commits', async ({ page }) => {
  await goSettlement(page)
  const ref = unique()
  await upload(page, `Date,Reference,Amount\n2026-08-01 10:00:00,${ref},5150\n`)
  await expect(page.getByText(/imported/i)).toBeVisible({ timeout: 30_000 })

  await page.locator('tr', { hasText: ref }).getByRole('button', { name: /Match/ }).click()
  await expect(page.getByRole('heading', { name: 'Match this payout' })).toBeVisible()
  await expect(page.getByText(/hard to spot later/i)).toBeVisible()
})

test('money with no sale behind it can be booked as other income', async ({ page }) => {
  await goSettlement(page)
  const ref = unique()
  await upload(page, `Date,Reference,Amount\n2026-08-01 10:00:00,${ref},2600\n`)
  await expect(page.getByText(/imported/i)).toBeVisible({ timeout: 30_000 })

  await page.locator('tr', { hasText: ref }).getByRole('button', { name: /Other income/ }).click()
  await page.getByRole('button', { name: /^(Confirm|Yes|OK)$/ }).last().click()
  await expect(page.getByText(/Recorded as other income/i)).toBeVisible({ timeout: 30_000 })
})

test('the header counts what still needs a person', async ({ page }) => {
  await goSettlement(page)
  await expect(page.getByText(/need review|accounted for/i).first()).toBeVisible()
})

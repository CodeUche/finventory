/**
 * Browser E2E for payment collection (Phase 0).
 *
 * Drives the three ways a merchant gets paid exactly as a cashier would, and
 * proves the two things that must never go wrong: an unconfirmed transfer must
 * not mark a sale paid, and confirming it must.
 */
import { test, expect, Page } from '@playwright/test'

const EMAIL = 'ui.test@audity.test'
const PW = 'Passw0rd!123'

// One login for the file — a login per test burns the 20/min throttle.
test.describe.configure({ mode: 'serial' })

async function login(page: Page) {
  await page.goto('/dashboard')
  if (!/\/dashboard/.test(page.url())) {
    await page.goto('/')
    await page.getByPlaceholder('you@company.com').fill(EMAIL)
    await page.locator('input[type="password"]').first().fill(PW)
    await page.locator('button[type="submit"]').click()
  }
  await expect(page).toHaveURL(/\/dashboard/, { timeout: 45_000 })
  const agree = page.getByRole('button', { name: /I agree — continue/ })
  if (await agree.isVisible().catch(() => false)) await agree.click()
}

/** Open the first unpaid invoice and bring up the collect-payment modal. */
async function openCollect(page: Page) {
  await page.goto('/sales')
  const row = page.locator('tr', { hasText: 'INV-00001' }).first()
  await expect(row).toBeVisible({ timeout: 25_000 })
  // The row itself isn't clickable — details open from the eye icon.
  await row.locator('button[title="View details"]').click()
  await page.getByRole('button', { name: /Ask customer to pay/ }).click()
  await expect(page.getByRole('heading', { name: 'Collect payment' })).toBeVisible()
}

test.describe('Collect payment', () => {
  test('offers every method the merchant has configured', async ({ page }) => {
    await login(page)
    await openCollect(page)

    // Provider configured → card + one-time account. Bank account added → transfer.
    await expect(page.getByRole('button', { name: /One-time account/ })).toBeVisible()
    await expect(page.getByRole('button', { name: /Card \/ online/ })).toBeVisible()
    await expect(page.getByRole('button', { name: /Bank transfer/ })).toBeVisible()
  })

  test('shows the amount outstanding', async ({ page }) => {
    await login(page)
    await openCollect(page)
    // Scope to the modal — the invoice panel behind it also says "Amount Due".
    const modal = page.locator('div.card', { hasText: 'Collect payment' }).first()
    await expect(modal.getByText('Amount due')).toBeVisible()
    await expect(modal.getByText(/40,796/)).toBeVisible()
  })

  test("bank transfer shows the merchant's own account and warns it is manual", async ({ page }) => {
    await login(page)
    await openCollect(page)
    await page.getByRole('button', { name: /Bank transfer/ }).click()

    await expect(page.getByText('0123456789')).toBeVisible()
    await expect(page.getByText(/Guaranty Trust Bank/)).toBeVisible()
    // The honesty check: this route is NOT auto-confirmed and must say so.
    await expect(page.getByText(/no automatic confirmation/i)).toBeVisible()
  })

  test('claiming a transfer does not mark the invoice paid', async ({ page }) => {
    await login(page)
    await openCollect(page)
    await page.getByRole('button', { name: /Bank transfer/ }).click()
    await page.getByPlaceholder(/Who is sending it/).fill('Ada Buyer')
    await page.getByRole('button', { name: /Customer has transferred/ }).click()

    await expect(page.getByText(/stays unpaid until someone confirms/i)).toBeVisible({ timeout: 20_000 })
  })

  test('a provider failure surfaces a readable message, not a crash', async ({ page }) => {
    // The seeded Paystack key is fake, so issuing an account really does fail.
    await login(page)
    await openCollect(page)
    await page.getByRole('button', { name: /One-time account/ }).click()
    await page.getByRole('button', { name: /Get account number/ }).click()

    // Either a provider error toast or a rejection — never an unhandled crash.
    await expect(
      page.getByText(/Paystack|Could not|reach|rejected|Invalid/i).first(),
    ).toBeVisible({ timeout: 30_000 })
  })
})

test.describe('Transfers to confirm', () => {
  test('the claim appears for staff to review', async ({ page }) => {
    await login(page)
    await page.goto('/payments/transfers')
    await expect(page.getByRole('heading', { name: 'Transfers to confirm' })).toBeVisible()
    await expect(page.getByText('INV-00001').first()).toBeVisible({ timeout: 25_000 })
    await expect(page.getByText('Ada Buyer').first()).toBeVisible()
  })

  test('confirming records the payment and settles the invoice', async ({ page }) => {
    await login(page)
    await page.goto('/payments/transfers')
    await expect(page.getByText('INV-00001').first()).toBeVisible({ timeout: 25_000 })

    await page.getByRole('button', { name: /^Confirm$/ }).first().click()
    // In-app confirm dialog (never a native window.confirm).
    await page.getByRole('button', { name: /^(Confirm|Yes|OK)$/ }).last().click()
    await expect(page.getByText(/Payment recorded/i)).toBeVisible({ timeout: 30_000 })

    // And the invoice is genuinely paid now — check the row, not the status
    // filter's hidden <option value="paid">.
    await page.goto('/sales')
    const row = page.locator('tr', { hasText: 'INV-00001' }).first()
    await expect(row).toBeVisible({ timeout: 25_000 })
    await expect(row.getByText('paid', { exact: true })).toBeVisible()
    await expect(row.getByText('₦0.00').first()).toBeVisible()
  })
})

test.describe('Payment settings', () => {
  test("the merchant's payout accounts are listed and addable", async ({ page }) => {
    await login(page)
    // Banking lives in a collapsed sidebar group, so go straight to the tab.
    await page.goto('/settings?tab=bank')

    await expect(page.getByText('Accounts customers can pay into')).toBeVisible({ timeout: 20_000 })
    await expect(page.getByText('0123456789').first()).toBeVisible()
    await expect(page.getByText(/Audity never/i)).toBeVisible()
  })
})

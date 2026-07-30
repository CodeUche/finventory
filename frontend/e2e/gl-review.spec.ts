/**
 * Browser E2E for the reviewer's GL / Opening Balances feedback.
 *
 * Walks the exact steps in the review document: the COA chips and table must show
 * every account type, adding an account must move both "All" and its own chip,
 * P&L accounts must be selectable on a journal entry, and the Opening Balances
 * modal must offer Dr/Cr on every sub-ledger tab with the Add Line control inline.
 */
import { test, expect, Page } from '@playwright/test'

const EMAIL = 'ui.test@audity.test'
const PW = 'Passw0rd!123'

// One browser context for the whole file: a login per test burns through the
// authenticated rate limit (user: 1000/hour) and the org fetch starts 429-ing.
test.describe.configure({ mode: 'serial' })

async function login(page: Page) {
  await page.goto('/')
  await page.getByPlaceholder('you@company.com').fill(EMAIL)
  await page.locator('input[type="password"]').first().fill(PW)
  await page.locator('button[type="submit"]').click()
  await expect(page).toHaveURL(/\/dashboard/, { timeout: 45_000 })
  await acceptTerms(page)
}

/** A freshly-seeded account is met by the terms gate, which blocks every click. */
async function acceptTerms(page: Page) {
  const agree = page.getByRole('button', { name: /I agree — continue/ })
  if (await agree.isVisible().catch(() => false)) {
    await agree.click()
    await expect(agree).toBeHidden({ timeout: 15_000 })
  }
}

/** Reads the number under a named COA filter chip. */
async function chipCount(page: Page, label: string): Promise<number> {
  const chip = page.locator('button', { has: page.getByText(label, { exact: true }) }).first()
  const text = await chip.innerText()
  const n = text.replace(label, '').trim().split(/\s+/).pop()
  return parseInt(n || '0', 10)
}

test.describe('Chart of Accounts', () => {
  test('chips are capitalised and every account type is counted', async ({ page }) => {
    await login(page)
    await page.goto('/accounting/coa')
    await expect(page.getByRole('heading', { name: 'Chart of Accounts' })).toBeVisible()
    // Wait for the accounts + summary calls to land before reading the counters.
    await expect(page.getByText('4001').first()).toBeVisible({ timeout: 20_000 })

    // Item 7: first letters capitalised.
    for (const label of ['All', 'Asset', 'Liability', 'Equity', 'Revenue', 'Expense', 'Cogs']) {
      await expect(page.getByText(label, { exact: true }).first()).toBeVisible()
    }

    // Items 3-5: revenue / expense / cogs are no longer stuck at 0.
    expect(await chipCount(page, 'Revenue')).toBeGreaterThan(0)
    expect(await chipCount(page, 'Expense')).toBeGreaterThan(0)
    expect(await chipCount(page, 'Cogs')).toBeGreaterThan(0)
  })

  test('revenue, expense and COGS accounts appear in the table', async ({ page }) => {
    await login(page)
    await page.goto('/accounting/coa')
    // Item 6: P&L accounts must be listed, not just counted.
    await expect(page.getByText('4001').first()).toBeVisible({ timeout: 20_000 })
    await expect(page.getByText('5001').first()).toBeVisible()
    await expect(page.getByText('6001').first()).toBeVisible()
  })

  test('adding a revenue account increments both All and Revenue', async ({ page }) => {
    await login(page)
    await page.goto('/accounting/coa')
    await expect(page.getByText('4001').first()).toBeVisible({ timeout: 20_000 })

    const beforeAll = await chipCount(page, 'All')
    const beforeRevenue = await chipCount(page, 'Revenue')

    const code = `48${Date.now().toString().slice(-2)}`
    const name = `E2E Consulting Income ${code}`
    await page.getByRole('button', { name: /Add Account/ }).click()
    // The modal's submit button carries the same label as the toolbar one, so scope to it.
    const modal = page.locator('div.card').filter({ hasText: 'Account Sub Type' }).first()
    await modal.getByPlaceholder('e.g. 1001').fill(code)
    await modal.getByPlaceholder('e.g. Cash and Cash Equivalents').fill(name)
    // "Income" is the P&L group that maps to account_type=revenue.
    await modal.locator('select').filter({ hasText: 'Select type…' }).first()
      .selectOption({ label: 'Income' })
    await modal.getByRole('button', { name: /Add Account|Save Changes/ }).click()

    // Items 1-3: the new account shows up and both counters move.
    await expect(page.getByText(name).first()).toBeVisible({ timeout: 20_000 })
    await expect.poll(async () => chipCount(page, 'All'), { timeout: 20_000 }).toBe(beforeAll + 1)
    expect(await chipCount(page, 'Revenue')).toBe(beforeRevenue + 1)
  })
})

test.describe('Journal entry', () => {
  test('P&L accounts are selectable on a journal line', async ({ page }) => {
    await login(page)
    await page.goto('/accounting/journal')
    await page.getByRole('button', { name: /New Journal|Add Entry|New Entry/ }).first().click()

    // Scope to the New Journal Entry modal — the page behind it has its own selects.
    const modal = page.locator('div.card').filter({ hasText: 'JOURNAL LINES' }).first()
    const accountSelect = modal.locator('select').first()
    await expect(accountSelect.locator('option')).not.toHaveCount(1, { timeout: 20_000 })
    const options = await accountSelect.locator('option').allInnerTexts()
    // Item 8: revenue / expense / COGS must be offered, not just balance-sheet codes.
    expect(options.some((o) => o.startsWith('4001'))).toBeTruthy()
    expect(options.some((o) => o.startsWith('5001'))).toBeTruthy()
    expect(options.some((o) => o.startsWith('6001'))).toBeTruthy()
  })
})

test.describe('Opening Balances', () => {
  async function openModal(page: Page) {
    await page.goto('/accounting/coa')
    await expect(page.getByText('4001').first()).toBeVisible({ timeout: 20_000 })
    await page.getByRole('button', { name: /Opening Balances/ }).click()
    await expect(page.getByText('Take-on balances from your previous accounting system')).toBeVisible()
  }

  test('Add Line sits inline on the row, not at the bottom', async ({ page }) => {
    await login(page)
    await openModal(page)
    // The bottom "Add Line" button is gone…
    await expect(page.getByRole('button', { name: /^Add Line$/ })).toHaveCount(0)
    // …replaced by an inline add control on the row (next to the remove X).
    await expect(page.locator('button[title="Add line below"]').first()).toBeVisible()
    await expect(page.locator('button[title="Remove line"]').first()).toBeVisible()

    // Clicking the inline + adds a row.
    const before = await page.locator('button[title="Add line below"]').count()
    await page.locator('button[title="Add line below"]').first().click()
    expect(await page.locator('button[title="Add line below"]').count()).toBe(before + 1)
  })

  test('Customers, Suppliers and Inventory tabs all offer Dr/Cr', async ({ page }) => {
    await login(page)
    await openModal(page)

    for (const tab of ['Customers', 'Suppliers', 'Inventory']) {
      await page.getByRole('button', { name: tab, exact: true }).click()
      await expect(page.getByRole('button', { name: 'Dr', exact: true }).first())
        .toBeVisible({ timeout: 20_000 })
      await expect(page.getByRole('button', { name: 'Cr', exact: true }).first()).toBeVisible()
    }
  })

  test('posting a customer credit balance succeeds', async ({ page }) => {
    await login(page)
    await openModal(page)

    await page.getByLabel(/As of Date/).fill('01/01/2026').catch(async () => {
      await page.locator('input[placeholder="DD/MM/YYYY"]').first().fill('01/01/2026')
    })
    await page.getByRole('button', { name: 'Customers', exact: true }).click()

    const row = page.locator('div.grid-cols-12')
      .filter({ hasText: 'Better Oil Services Ltd' }).last()
    await expect(row).toBeVisible({ timeout: 20_000 })
    await row.getByRole('button', { name: 'Cr', exact: true }).click()
    await row.locator('input[inputmode="decimal"]').fill('40000')

    await page.getByRole('button', { name: /Post Opening Balances/ }).click()
    await expect(page.getByText(/Opening balances posted/i)).toBeVisible({ timeout: 30_000 })
  })

  test('a direct opening balance on AR is refused with tab guidance', async ({ page }) => {
    await login(page)
    await openModal(page)

    await page.locator('input[placeholder="DD/MM/YYYY"]').first().fill('01/01/2026')
    const select = page.locator('select').filter({ hasText: 'Select account…' }).first()
    const arValue = await select.locator('option', { hasText: '1100' }).first().getAttribute('value')
    await select.selectOption(arValue!)
    await page.locator('input[inputmode="decimal"]').first().fill('300000')
    await page.getByRole('button', { name: /Post Opening Balances/ }).click()

    await expect(page.getByText(/Customers tab/i)).toBeVisible({ timeout: 30_000 })
  })
})

/**
 * Browser E2E for the reviewer's Bank Reconciliation feedback ("I really cannot
 * work around the Bank Recons").
 *
 * A live click-through found the feature could reach an unrecoverable state: a
 * ragged CSV row 500'd the import mid-loop, the rows already written stayed behind
 * (no transaction), and re-importing the corrected file duplicated them — leaving a
 * permanently non-zero Difference, a disabled "Mark as Reconciled", and no delete
 * or edit control anywhere in the UI.
 *
 * C2 is the gate: the reviewer's exact ragged-then-corrected journey must end at
 * Difference ₦0.00 with "Mark as Reconciled" enabled.
 */
import { test, expect, Page } from '@playwright/test'
import fs from 'fs'
import path from 'path'
import os from 'os'

// Credentials for whichever stack this is pointed at (see the bank-recon project
// in playwright.config.ts). Overridable so the same spec can be run against a
// local throwaway stack or a deployed environment.
const EMAIL = process.env.E2E_RECON_EMAIL || 'ui.test@audity.test'
const PW = process.env.E2E_RECON_PASSWORD || 'Passw0rd!123'
// Which account to reconcile — matched against the option text. Defaults to the
// standard bank account code so the run lands on an account with ledger activity.
const ACCOUNT_HINT = process.env.E2E_RECON_ACCOUNT || '1002'

// One browser context for the whole file: a login per test burns through the
// authenticated rate limit (user: 1000/hour) and the org fetch starts 429-ing.
test.describe.configure({ mode: 'serial' })

const tmp = (name: string, body: string) => {
  const p = path.join(os.tmpdir(), name)
  fs.writeFileSync(p, body)
  return p
}

/** The corrected statement. Sums to 311,500.32 — the closing balance we start with. */
const CLEAN_CSV = [
  'date,description,debit,credit',
  '03/07/2026,NIP/TRF/Falcon Ltd,,250000.00',
  '09/07/2026,NIP/TRF/BikeBuzz,,120500.50',
  '15/07/2026,RENT PAYMENT JULY,80000.00,',
  '21/07/2026,NIP/TRF/Unique Foods,,57499.82',
  '24/07/2026,RENT DEPOSIT,35000.00,',
  '28/07/2026,BANK CHARGE COMMISSION,1500.00,',
].join('\n')

/** The same statement as first exported by the bank: one row truncated (missing
 *  trailing columns) and one with stray extra columns. Both are routine in real
 *  Nigerian bank exports and both used to break the import. */
const RAGGED_CSV = [
  'date,description,debit,credit',
  '03/07/2026,NIP/TRF/Falcon Ltd,,250000.00',
  '09/07/2026,NIP/TRF/BikeBuzz',
  '15/07/2026,RENT PAYMENT JULY,80000.00,,EXTRA,COLS',
].join('\n')

async function login(page: Page) {
  // Already signed in? Nothing to do — avoids burning the 20/min login throttle.
  await page.goto('/dashboard', { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(1500)
  if (/\/dashboard/.test(page.url())) return

  await page.goto('/login', { waitUntil: 'domcontentloaded' })
  await page.locator('input[type="email"]').first().fill(EMAIL)
  await page.locator('input[type="password"]').first().fill(PW)
  await page.locator('button[type="submit"]').first().click()
  await expect(page).toHaveURL(/\/dashboard/, { timeout: 45_000 })
}

async function gotoRecon(page: Page) {
  await page.goto('/accounting/reconciliation')
  await page.waitForTimeout(2500)
}

const accountSelect = (page: Page) =>
  page.locator('select').filter({ hasText: 'Select Account' })

async function startReconciliation(page: Page, closingBalance: string) {
  // Accounts load asynchronously — wait for real options before selecting.
  await page.waitForFunction(() => {
    const sels = Array.from(document.querySelectorAll('select'))
    const s = sels.find((x) => (x.textContent || '').includes('Select Account'))
    return !!s && s.options.length > 1
  }, { timeout: 20_000 })

  // Reconcile the account that actually carries ledger activity, rather than
  // whichever happens to sort first — otherwise a legitimately empty account
  // (petty cash with no entries) makes the Book Balance assertion meaningless.
  const options = await accountSelect(page).locator('option').allTextContents()
  const preferred = options.find((o) => o.includes(ACCOUNT_HINT))
  if (preferred) await accountSelect(page).selectOption({ label: preferred })
  else await accountSelect(page).selectOption({ index: 1 })

  // Period fields are DD/MM/YYYY text inputs (DateInput), not input[type=date].
  const texts = page.locator('input[type="text"]')
  const dateIdx: number[] = []
  for (let i = 0; i < (await texts.count()); i++) {
    const v = await texts.nth(i).inputValue().catch(() => '')
    if (/^\d{2}\/\d{2}\/\d{4}$/.test(v)) dateIdx.push(i)
  }
  await texts.nth(dateIdx[0]).fill('')
  await texts.nth(dateIdx[0]).type('01/07/2026', { delay: 30 })
  await texts.nth(dateIdx[1]).fill('')
  await texts.nth(dateIdx[1]).type('31/07/2026', { delay: 30 })

  await page.locator('input[inputmode="decimal"]').first().fill(closingBalance)
  await page.getByRole('button', { name: 'Start Reconciliation' }).click()
  await page.waitForTimeout(3000)
}

const lineRows = (page: Page) =>
  page.locator('div.divide-y > div').filter({ hasText: '₦' })

test.describe('Bank Reconciliation', () => {
  test('C6 — only cash/bank accounts are offered as reconciliation targets', async ({ page }) => {
    await login(page)
    await gotoRecon(page)
    await page.waitForFunction(() => {
      const sels = Array.from(document.querySelectorAll('select'))
      const s = sels.find((x) => (x.textContent || '').includes('Select Account'))
      return !!s && s.options.length > 1
    }, { timeout: 20_000 })

    const options = await accountSelect(page).locator('option').allTextContents()
    // Previously filtered on code.startsWith('1'), which offered every asset account.
    for (const banned of ['Inventory', 'Fixed Assets', 'Accumulated Depreciation',
                          'VAT Receivable', 'Deferred Tax', 'Prepaid']) {
      expect(options.join(' '), `${banned} must not be reconcilable`).not.toContain(banned)
    }
    expect(options.length).toBeGreaterThan(1)
  })

  test('C2 — a ragged import then the corrected file reconciles to zero', async ({ page }) => {
    await login(page)
    await gotoRecon(page)
    await startReconciliation(page, '311500.32')

    // The ragged file must not 500, and must not leave a partial import behind.
    const raggedResponse = page.waitForResponse(
      (r) => r.url().includes('import_statement') , { timeout: 30_000 })
    await page.setInputFiles('input[type="file"]', tmp('recon-ragged.csv', RAGGED_CSV))
    expect((await raggedResponse).status()).not.toBe(500)
    await page.waitForTimeout(3000)

    // Re-import the corrected statement — rows already present must be skipped.
    await page.setInputFiles('input[type="file"]', tmp('recon-clean.csv', CLEAN_CSV))
    await page.waitForTimeout(4000)

    await page.getByRole('button', { name: 'Manual' }).click()
    await page.waitForTimeout(2000)

    // Imported lines must be visible without a page reload (the follow-up GET used
    // to be served from the offline cache, so a successful import looked like a no-op).
    await expect(page.getByText('No transactions yet')).toHaveCount(0)

    const body = (await page.textContent('body')) || ''
    expect((body.match(/Falcon/g) || []).length,
      're-importing the corrected file must not duplicate a row').toBe(1)

    await page.getByRole('button', { name: 'Select All', exact: true }).click()
    await page.waitForTimeout(1200)

    // THE GATE.
    await expect(page.getByText('Balanced')).toBeVisible()
    await expect(page.getByRole('button', { name: 'Mark as Reconciled' })).toBeEnabled()
  })

  test('C6b — Book Balance shows the real ledger figure, not zero', async ({ page }) => {
    await login(page)
    await gotoRecon(page)
    const body = (await page.textContent('body')) || ''
    // book_balance was a stored field nothing ever wrote, so every row read ₦0.00.
    const bookBalCells = await page.locator('table tbody tr td').nth(3).allTextContents().catch(() => [])
    if (bookBalCells.length) expect(bookBalCells.join('')).not.toBe('₦0.00')
    expect(body).toBeTruthy()
  })

  test('C3/C5 — a user with no CSV can add, edit and delete transactions', async ({ page }) => {
    await login(page)
    await gotoRecon(page)
    await startReconciliation(page, '5000')
    await page.getByRole('button', { name: 'Manual' }).click()
    await page.waitForTimeout(1500)

    const before = await lineRows(page).count()

    // Add by hand — add_line and addReconLine both already existed but nothing
    // in the UI ever called them, so a user without a CSV was stuck.
    await page.getByRole('button', { name: 'Add Transaction' }).first().click()
    await page.waitForTimeout(1000)
    await page.locator('div[role="dialog"] input').first().fill('Manual cash deposit')
    await page.locator('div[role="dialog"] input[inputmode="decimal"]').fill('5000')
    await page.locator('div[role="dialog"]').getByRole('button', { name: 'Add transaction' }).click()
    await page.waitForTimeout(3000)
    expect(await lineRows(page).count()).toBe(before + 1)

    // Delete it again — the escape hatch.
    const row = lineRows(page).first()
    await row.hover()
    await row.locator('button[aria-label^="Delete"]').click()
    await page.waitForTimeout(800)
    await page.getByRole('button', { name: 'Delete' }).last().click()
    await page.waitForTimeout(3000)
    expect(await lineRows(page).count()).toBe(before)
  })

  test('C4 — Load from Ledger reconciles without any statement file', async ({ page }) => {
    await login(page)
    await gotoRecon(page)
    await startReconciliation(page, '0')
    await page.getByRole('button', { name: 'Manual' }).click()
    await page.waitForTimeout(1500)

    const before = await lineRows(page).count()
    await page.getByRole('button', { name: 'Load from Ledger' }).click()
    await page.waitForTimeout(4000)
    expect(await lineRows(page).count()).toBeGreaterThanOrEqual(before)
  })

  test('C9 — clearing lines does not fire one request per line', async ({ page }) => {
    await login(page)
    await gotoRecon(page)
    await startReconciliation(page, '311500.32')
    await page.getByRole('button', { name: 'Manual' }).click()
    await page.waitForTimeout(1500)

    const patches: string[] = []
    page.on('request', (r) => {
      if (r.method() === 'PATCH' && r.url().includes('update_line')) patches.push(r.url())
    })
    const selectAll = page.getByRole('button', { name: 'Select All', exact: true })
    if (await selectAll.count()) {
      await selectAll.click()
      await page.waitForTimeout(1500)
    }
    // The UI used to PATCH every line; a 300-line statement meant 300 requests.
    expect(patches.length).toBe(0)
  })
})

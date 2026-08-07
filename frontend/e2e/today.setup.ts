/**
 * Login for the "today" spec (real-browser click-through of HR-to-10,
 * messaging, payment engine, integrations marketplace built earlier today).
 *
 * Runs against its own throwaway stack (backend :8010 / frontend :5183) with
 * its own seeded user, so it needs its own session rather than the shared
 * `e2e`/`payments` ones — same reasoning as payments.setup.ts.
 */
import { test as setup, expect } from '@playwright/test'

const EMAIL = 'browsertest@audity.local'
const PW = 'BrowserTest123!'

export const TODAY_STORAGE_STATE = './e2e/.auth/today.json'

setup('authenticate the today browser-test user', async ({ page }) => {
  await page.goto('/')
  await page.getByPlaceholder('you@company.com').fill(EMAIL)
  await page.locator('input[type="password"]').first().fill(PW)
  await page.locator('button[type="submit"]').click()
  await expect(page).toHaveURL(/\/dashboard/, { timeout: 60_000 })

  // The sidebar only fills in once memberships + plan modules land; snapshotting
  // earlier persists a half-hydrated session with no navigation.
  await expect(page.getByText('ACCOUNTING & FINANCE', { exact: true }))
    .toBeVisible({ timeout: 60_000 })

  await expect
    .poll(async () => page.evaluate(() => {
      const raw = localStorage.getItem('finventory-auth')
      return raw ? JSON.parse(raw)?.state?.memberRole : null
    }), { timeout: 60_000 })
    .toBeTruthy()

  // The seeded browsertest user's terms_accepted_version predates
  // current_terms_version, so TermsGateModal opens a hard re-acceptance gate
  // (z-[70], covers the whole viewport) on first load. Clear it here so it
  // never intercepts clicks in every downstream spec — resolving it once and
  // saving storage state afterward means the acceptance persists for the
  // whole "today" project run.
  const agree = page.getByRole('button', { name: /I agree — continue/ })
  if (await agree.isVisible({ timeout: 5_000 }).catch(() => false)) {
    await agree.click()
    await expect(agree).not.toBeVisible({ timeout: 15_000 })
  }

  await page.context().storageState({ path: TODAY_STORAGE_STATE })
})

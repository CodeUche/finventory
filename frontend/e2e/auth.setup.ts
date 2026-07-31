/**
 * One-time login for the whole E2E run.
 *
 * The backend throttles login at 20/minute per IP. With ~24 specs each doing
 * their own form login, later tests were being rate-limited and failed with
 * misleading "element not found" errors. This setup project logs in ONCE and
 * saves the storage state (Zustand persists auth under `finventory-auth`),
 * which every other project then reuses.
 */
import { test as setup, expect } from '@playwright/test'

const EMAIL = 'e2e.pilot@audity.test'
const PW = 'Passw0rd!123'

// Must match playwright.config.ts (relative to the frontend directory).
export const STORAGE_STATE = './e2e/.auth/user.json'

setup('authenticate once', async ({ page }) => {
  await page.goto('/')
  await page.getByPlaceholder('you@company.com').fill(EMAIL)
  await page.locator('input[type="password"]').first().fill(PW)
  await page.locator('button[type="submit"]').click()
  await expect(page).toHaveURL(/\/dashboard/, { timeout: 60_000 })

  // Landing on /dashboard is not enough: the membership + plan modules load
  // just after, and the sidebar hides every module-gated item until they do.
  // Saving too early persists a half-hydrated session where the whole nav is
  // missing. Wait for a module-gated group before snapshotting.
  await expect(page.getByText('ACCOUNTING & FINANCE', { exact: true }))
    .toBeVisible({ timeout: 60_000 })

  await page.context().storageState({ path: STORAGE_STATE })
})

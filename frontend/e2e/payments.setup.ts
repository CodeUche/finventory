/**
 * Login for the payments spec.
 *
 * The payments E2E runs against its own isolated stack (a throwaway database on
 * :3010), so it needs its own session rather than the shared pilot one.
 */
import { test as setup, expect } from '@playwright/test'

const EMAIL = 'ui.test@audity.test'
const PW = 'Passw0rd!123'

export const PAYMENTS_STORAGE_STATE = './e2e/.auth/payments.json'

setup('authenticate payments user', async ({ page }) => {
  await page.goto('/')
  await page.getByPlaceholder('you@company.com').fill(EMAIL)
  await page.locator('input[type="password"]').first().fill(PW)
  await page.locator('button[type="submit"]').click()
  await expect(page).toHaveURL(/\/dashboard/, { timeout: 60_000 })

  // The sidebar only fills in once memberships + plan modules land; snapshotting
  // earlier persists a half-hydrated session with no navigation.
  await expect(page.getByText('SALES & POS', { exact: true }))
    .toBeVisible({ timeout: 60_000 })

  // memberRole is fetched separately from the module list and owner-only
  // settings tabs stay hidden until it lands, so wait for it in the store
  // before snapshotting — otherwise every settings test starts as a viewer.
  await expect
    .poll(async () => page.evaluate(() => {
      const raw = localStorage.getItem('finventory-auth')
      return raw ? JSON.parse(raw)?.state?.memberRole : null
    }), { timeout: 60_000 })
    .toBeTruthy()

  await page.context().storageState({ path: PAYMENTS_STORAGE_STATE })
})

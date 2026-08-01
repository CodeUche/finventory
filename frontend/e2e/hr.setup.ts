import { test as setup, expect, type Page } from '@playwright/test'

/**
 * One login per persona for the whole HR run.
 *
 * The backend throttles login at 20/minute per IP. A per-test form login
 * exhausts that within a single suite run and the failures surface as
 * misleading "element not found" errors, so both sessions are captured once
 * and reused via storage state.
 */
export const OWNER_STATE = './e2e/.auth/hr-owner.json'
export const EMPLOYEE_STATE = './e2e/.auth/hr-employee.json'

const OWNER = { email: 'hr.owner@audity.test', password: 'HrTestPass123!' }
const EMPLOYEE = { email: 'ada.okonkwo@audity.test', password: 'EmpTestPass123!' }

async function signIn(page: Page, who: { email: string; password: string }) {
  await page.goto('/login')
  await page.getByPlaceholder('you@company.com').fill(who.email)
  await page.locator('input[type="password"]').first().fill(who.password)
  await page.locator('button[type="submit"]').click()
}

setup('authenticate the HR operator', async ({ page }) => {
  await signIn(page, OWNER)
  await expect(page).toHaveURL(/\/dashboard/, { timeout: 60_000 })
  // Landing on /dashboard is not enough: membership + plan modules load just
  // after, and every module-gated nav item stays hidden until they do. Saving
  // too early persists a half-hydrated session with no navigation.
  await expect(page.getByText('ACCOUNTING & FINANCE', { exact: true }))
    .toBeVisible({ timeout: 60_000 })
  await page.context().storageState({ path: OWNER_STATE })
})

setup('authenticate the employee', async ({ page }) => {
  await signIn(page, EMPLOYEE)
  // An employee membership carries no module permissions, so HomeRedirect
  // sends them straight to the self-service portal rather than the dashboard.
  await expect(page).toHaveURL(/\/me/, { timeout: 60_000 })
  await expect(page.getByText(/Hello, Ada/)).toBeVisible({ timeout: 60_000 })
  await page.context().storageState({ path: EMPLOYEE_STATE })
})

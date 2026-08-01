import { test, expect } from '@playwright/test'

/**
 * Employee self-service portal.
 *
 * Runs with the employee's saved session (see hr.setup.ts). The point of these
 * tests is the boundary: an employee must see their own record and nothing
 * else, and must not reach any operator surface.
 */
test.describe.configure({ mode: 'serial' })

test('the portal opens on the employee\'s own record', async ({ page }) => {
  await page.goto('/me')
  await expect(page.getByText(/Hello, Ada/)).toBeVisible({ timeout: 45_000 })
  await expect(page.getByText('Nexa Foods Ltd')).toBeVisible()
})

test('the latest payslip shows net pay and the PAYE authority', async ({ page }) => {
  await page.goto('/me')
  await expect(page.getByText(/Net paid/i)).toBeVisible({ timeout: 45_000 })
  // PAYE is labelled with the State IRS it is owed to, not "FIRS"
  await expect(page.getByText(/Lagos/).first()).toBeVisible()
})

test('no colleague appears anywhere in the portal', async ({ page }) => {
  await page.goto('/me')
  await expect(page.getByText(/Hello, Ada/)).toBeVisible({ timeout: 45_000 })
  for (const colleague of ['Tunde Danjuma', 'Musa Yusuf', 'Bola Eze', 'Chidi Bello']) {
    await expect(page.getByText(colleague)).toHaveCount(0)
  }
})

test('the salary advance entitlement is shown with its basis', async ({ page }) => {
  await page.goto('/me')
  await expect(page.getByText(/salary advance/i).first()).toBeVisible({ timeout: 45_000 })
  await expect(page.getByText(/earned so far/i)).toBeVisible()
  await expect(page.getByText(/working days/i)).toBeVisible()
})

test('leave balances and a request form are available', async ({ page }) => {
  await page.goto('/me')
  await expect(page.getByText(/Hello, Ada/)).toBeVisible({ timeout: 45_000 })
  await page.getByRole('button', { name: /^Leave$/ }).click()
  await expect(page.getByRole('button', { name: /request leave/i }).first())
    .toBeVisible({ timeout: 20_000 })
})

test('an employee cannot reach an operator HR page', async ({ page }) => {
  await page.goto('/hr/employees')
  // The operator employee list must never render for an employee session.
  await expect(page.getByText('Musa Yusuf')).toHaveCount(0)
  await expect(page.getByText('Tunde Danjuma')).toHaveCount(0)
})

test('an employee cannot reach the compliance cockpit', async ({ page }) => {
  await page.goto('/hr/compliance')
  await expect(page.getByText(/Industrial Training Fund/)).toHaveCount(0)
})

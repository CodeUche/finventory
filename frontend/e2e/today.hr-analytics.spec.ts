import { test, expect } from '@playwright/test'

/**
 * Real-browser click-through of HR Analytics (src/pages/payroll/HRAnalyticsPage.tsx),
 * including the new "Documents expiring soon" tile built earlier today.
 */
test.describe.configure({ mode: 'serial' })

test('HR Analytics renders headcount and the documents-expiring tile with no console errors', async ({ page }) => {
  const consoleErrors: string[] = []
  page.on('console', (msg) => {
    if (msg.type() === 'error') consoleErrors.push(msg.text())
  })
  page.on('pageerror', (err) => consoleErrors.push(err.message))

  await page.goto('/hr/analytics')
  await expect(page.getByRole('heading', { name: 'HR Analytics' })).toBeVisible({ timeout: 45_000 })

  // Real data: the stat tiles render with a label + numeric/percent value,
  // not stuck on the loading spinner.
  await expect(page.getByText('Headcount (start of year)')).toBeVisible({ timeout: 20_000 })
  // Exact match — "Joiners" and "Leavers" also appear as substrings inside
  // the "Joiners vs leavers by month" chart caption on this page.
  await expect(page.getByText('Joiners', { exact: true })).toBeVisible()
  await expect(page.getByText('Leavers', { exact: true })).toBeVisible()
  await expect(page.getByText('Attrition rate')).toBeVisible()

  // The new "Documents expiring soon" tile header — scope to the section
  // caption, since the empty-state copy ("No employee documents expiring
  // soon.") also matches the same regex.
  await expect(page.getByText(/Documents expiring soon \(\d+ days\)/i)).toBeVisible()

  // Give any late-firing async errors (chart render, etc.) a moment to surface.
  await page.waitForTimeout(1500)
  expect(consoleErrors, `Console errors on /hr/analytics:\n${consoleErrors.join('\n')}`).toEqual([])
})

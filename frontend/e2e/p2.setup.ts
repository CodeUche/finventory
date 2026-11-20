/** One UI login for the whole p2 run; saves the session for the p2 project. */
import { test as setup, expect } from '@playwright/test'
import { allowCors, URL_BASE, EMAIL, PASSWORD, STATE } from './p2/support'

setup('p2: sign in once', async ({ page, context }) => {
  await allowCors(context)
  await page.goto(URL_BASE + '/login')
  await page.locator('input[type=email]').fill(EMAIL)
  await page.locator('input[type=password]').first().fill(PASSWORD)
  await page.locator('button[type=submit]').click()
  await expect(page).toHaveURL(/\/dashboard/, { timeout: 60_000 })
  await context.storageState({ path: STATE })
})

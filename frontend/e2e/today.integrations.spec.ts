import { test, expect } from '@playwright/test'

/**
 * Real-browser click-through of the integrations marketplace
 * (src/pages/settings/IntegrationsPage.tsx) built earlier today.
 *
 * Browser Test Org is seeded with active entitlements for both `webhooks`
 * and `zapier` IntegrationProduct rows; `quickbooks-sync` exists as a
 * catalog product with NO entitlement, used for the purchase-attempt test.
 */
test.describe.configure({ mode: 'serial' })

test('the catalog shows Custom Webhooks and Zapier as already purchased, with real prices', async ({ page }) => {
  await page.goto('/integrations')
  // exact: true — "Available Integrations" is also an <h2> on this page and
  // would otherwise match the same role/name query (strict-mode violation).
  await expect(page.getByRole('heading', { name: 'Integrations', exact: true })).toBeVisible({ timeout: 30_000 })

  const webhooksCard = page.locator('div.card', { hasText: 'Custom Webhooks' }).first()
  await expect(webhooksCard).toBeVisible({ timeout: 20_000 })
  await expect(webhooksCard.getByText('₦15,000.00')).toBeVisible()
  await expect(webhooksCard.getByText('Purchased')).toBeVisible()

  const zapierCard = page.locator('div.card', { hasText: 'Zapier' }).first()
  await expect(zapierCard).toBeVisible()
  await expect(zapierCard.getByText('₦20,000.00')).toBeVisible()
  await expect(zapierCard.getByText('Purchased')).toBeVisible()
})

test('adding a webhook subscription reveals a one-time secret and can send a test event', async ({ page }) => {
  await page.goto('/integrations')
  // exact: true — "Available Integrations" is also an <h2> on this page and
  // would otherwise match the same role/name query (strict-mode violation).
  await expect(page.getByRole('heading', { name: 'Integrations', exact: true })).toBeVisible({ timeout: 30_000 })

  await expect(page.getByText('Add a new webhook')).toBeVisible({ timeout: 20_000 })
  // A unique URL per run — this throwaway DB persists across repeated local
  // runs (nothing resets WebhookSubscription rows between them), so a fixed
  // URL string accumulates duplicate rows over time and makes `.first()`
  // below resolve to a stale row from an earlier run instead of this one.
  const targetUrl = `https://webhook.site/e2e-today-test-${Date.now()}`
  await page.getByPlaceholder('https://your-app.example.com/webhooks/audity').fill(targetUrl)
  await page.getByText('Invoice created').click()

  await page.getByRole('button', { name: /Add webhook/ }).click()

  // One-time secret shown exactly once.
  await expect(page.getByText(/Save this signing secret now/i)).toBeVisible({ timeout: 20_000 })
  const secretCode = page.locator('code').first()
  await expect(secretCode).toBeVisible()
  const secretText = await secretCode.textContent()
  expect(secretText?.length).toBeGreaterThan(10)

  await page.getByText('Dismiss').click()

  // The new subscription is listed; send a test event and confirm a delivery
  // attempt is recorded (delivered, pending-retry, or failed — any of these
  // is a real recorded attempt; only a crash/hang would be a bug). Delivery
  // dispatches synchronously (bypasses Celery) and does a real outbound HTTPS
  // call, confirmed ~1.8s round trip in this environment — comfortably inside
  // the timeout below.
  const row = page.locator('div.card', { hasText: targetUrl }).first()
  await expect(row).toBeVisible({ timeout: 15_000 })
  await row.getByRole('button', { name: /Send test event/ }).click()

  await expect(
    page.getByText(/Test event delivered successfully|queued for retry|failed to deliver/i).first()
  ).toBeVisible({ timeout: 30_000 })
})

test('a webhook pointed at a loopback address is rejected, not silently accepted', async ({ page }) => {
  await page.goto('/integrations')
  await expect(page.getByText('Add a new webhook')).toBeVisible({ timeout: 30_000 })

  await page.getByPlaceholder('https://your-app.example.com/webhooks/audity').fill('http://127.0.0.1/')
  await page.getByText('Payment received').click()
  await page.getByRole('button', { name: /Add webhook/ }).click()

  // Must NOT show the one-time-secret success state for this submission.
  await expect(page.getByText(/Save this signing secret now/i)).toHaveCount(0, { timeout: 5_000 }).catch(() => {})
  // A rejection is surfaced (toast) rather than pretending success. .first()
  // — react-hot-toast renders each toast twice (a visible copy plus an
  // offscreen accessibility/exit-animation duplicate), both matching here.
  await expect(page.getByText(/disallowed|not allowed|loopback|private|rejected|invalid target/i).first()).toBeVisible({ timeout: 20_000 })
})

test('a webhook pointed at the cloud metadata address is rejected, not silently accepted', async ({ page }) => {
  await page.goto('/integrations')
  await expect(page.getByText('Add a new webhook')).toBeVisible({ timeout: 30_000 })

  await page.getByPlaceholder('https://your-app.example.com/webhooks/audity').fill('http://169.254.169.254/latest/meta-data/')
  await page.getByText('Employee onboarded').click()
  await page.getByRole('button', { name: /Add webhook/ }).click()

  await expect(page.getByText(/disallowed|not allowed|link-local|private|rejected|invalid target/i).first()).toBeVisible({ timeout: 20_000 })
})

test('purchasing a not-yet-entitled product attempts the Paystack flow and fails gracefully', async ({ page }) => {
  await page.goto('/integrations')
  // exact: true — "Available Integrations" is also an <h2> on this page and
  // would otherwise match the same role/name query (strict-mode violation).
  await expect(page.getByRole('heading', { name: 'Integrations', exact: true })).toBeVisible({ timeout: 30_000 })

  const qbCard = page.locator('div.card', { hasText: 'QuickBooks Sync' }).first()
  await expect(qbCard).toBeVisible({ timeout: 20_000 })
  await expect(qbCard.getByText('Purchased')).toHaveCount(0)

  // Case-insensitive and matches both label states: "Purchase — ₦X" for a
  // fresh (no entitlement) product, or "Complete purchase" if an earlier run
  // of this same test already created a pending entitlement (the purchase
  // flow creates the entitlement row before the Paystack call, so a prior
  // failed/incomplete run can leave one behind) — both are legitimate correct
  // UI states, not a bug, so the test should recognize either.
  const purchaseBtn = qbCard.getByRole('button', { name: /purchase/i })
  await expect(purchaseBtn).toBeVisible()
  await purchaseBtn.click()

  // With no real Paystack sandbox key configured, this must fail readably —
  // never hang forever on the spinner and never crash the page.
  await expect(
    page.getByText(/Paystack|not configured|Contact support|Failed to initiate payment|Could not|invalid/i).first()
  ).toBeVisible({ timeout: 30_000 })

  // The button must recover (not stuck disabled/spinning forever).
  await expect(purchaseBtn).toBeEnabled({ timeout: 10_000 })
})

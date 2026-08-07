import { test, expect, Page } from '@playwright/test'
import path from 'path'
import fs from 'fs'
import { fileURLToPath } from 'url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

/**
 * Real-browser click-through of in-app messaging built earlier today
 * (src/pages/messaging/MessagesPage.tsx), including the attachment upload
 * path (previously a stub, wired earlier today) and org isolation.
 *
 * Uses the "today" session (browsertest@audity.local, Browser Test Org).
 * A second same-org user (browsertest2@audity.local) and a different-org
 * user (outsider@audity.local, Isolation Test Org) were seeded via the
 * Django shell against the throwaway finventory_clicktest DB — see the
 * seeding commands run ahead of this spec; both share the same password
 * ('BrowserTest123!') as the primary "today" user so a second browser
 * context can log in directly in-test without touching the shared
 * today.setup.ts storage state.
 */
test.describe.configure({ mode: 'serial' })

const SCRATCH_DIR = path.join(__dirname, '.scratch')
const ATTACHMENT_PATH = path.join(SCRATCH_DIR, 'today-messaging-attachment.txt')

test.beforeAll(() => {
  fs.mkdirSync(SCRATCH_DIR, { recursive: true })
  fs.writeFileSync(ATTACHMENT_PATH, 'Audity messaging attachment E2E fixture.\n')
})

// TermsGateModal (src/components/TermsGateModal.tsx) opens a hard,
// viewport-covering re-acceptance gate for any user whose
// terms_accepted_version is behind current_terms_version — confirmed live
// via a failure screenshot for browsertest2/outsider (both freshly seeded
// users who never accepted terms in-app). today.setup.ts already dismisses
// this once for the primary browsertest@audity.local session and its
// acceptance is saved into storage state, but the two tests below log in
// fresh via browser.newContext({ storageState: undefined }) specifically to
// get an unauthenticated context, so they hit this gate on first load and
// must dismiss it themselves.
async function dismissTermsGateIfPresent(page: Page) {
  // locator.isVisible() is a synchronous snapshot check — it does NOT wait
  // for the element to appear despite looking like it takes a timeout (that
  // timeout only bounds internal actionability polling, not "wait up to N
  // seconds for this to show up"). That was the actual bug: the gate's own
  // useEffect (an authApi.profile() call) can resolve a beat after
  // navigation, so an isVisible() check running immediately after goto()
  // reliably found nothing and moved on, then the gate appeared right on top
  // of the next click. waitFor({state: 'visible'}) genuinely polls.
  const agree = page.getByRole('button', { name: /I agree — continue/ })
  const appeared = await agree
    .waitFor({ state: 'visible', timeout: 4_000 })
    .then(() => true)
    .catch(() => false)
  if (appeared) {
    await agree.click()
    await expect(agree).not.toBeVisible({ timeout: 15_000 })
  }
}

test('starting a new conversation, sending a message, and seeing it in the thread', async ({ page }) => {
  await page.goto('/messages')
  await expect(page.getByRole('heading', { name: 'Messages' })).toBeVisible({ timeout: 30_000 })

  await page.getByRole('button', { name: /New conversation/ }).click()
  await expect(page.getByRole('heading', { name: 'New conversation' })).toBeVisible()

  // Second same-org team member, seeded ahead of this run. Once a
  // conversation with them already exists (e.g. a prior run against this
  // throwaway DB), the SAME email also appears as a sidebar conversation row
  // behind the modal — scope to the "New conversation" modal card itself so
  // the match is unambiguous regardless of what's already in the list.
  const modal = page.locator('div.card', { has: page.getByRole('heading', { name: 'New conversation' }) })
  const target = modal.getByRole('button', { name: /browsertest2@audity\.local/ })
  await expect(target).toBeVisible({ timeout: 15_000 })
  await target.click()

  // Conversation opens directly into the thread pane.
  await expect(page.getByText('No messages yet — say hello.')).toBeVisible({ timeout: 15_000 })

  const composer = page.getByPlaceholder('Type a message…')
  await composer.fill('Hello from the E2E run — real browser, real click.')
  await page.getByLabel('Send message').click()

  await expect(page.getByText('Hello from the E2E run — real browser, real click.')).toBeVisible({ timeout: 15_000 })
})

test('attaching a file shows a pending chip, sends, and renders a downloadable link', async ({ page }) => {
  await page.goto('/messages')
  await expect(page.getByRole('heading', { name: 'Messages' })).toBeVisible({ timeout: 30_000 })

  // Reopen the conversation created in the previous test (My Team tab, first row).
  const convRow = page.locator('button', { hasText: 'browsertest2@audity.local' }).first()
  await expect(convRow).toBeVisible({ timeout: 20_000 })
  await convRow.click()

  const fileInput = page.locator('input[type="file"]')
  await fileInput.setInputFiles(ATTACHMENT_PATH)

  // Pending-attachment chip appears before send.
  await expect(page.getByText('today-messaging-attachment.txt')).toBeVisible({ timeout: 20_000 })

  await page.getByLabel('Send message').click()

  // Renders as a downloadable link in the thread (not just the pending chip).
  const attachmentLink = page.locator('a', { hasText: 'today-messaging-attachment.txt' })
  await expect(attachmentLink).toBeVisible({ timeout: 20_000 })
  const href = await attachmentLink.getAttribute('href')
  expect(href).toBeTruthy()

  // Exercise the authenticated-download endpoint for real. Auth here is a JWT
  // sent via an Authorization header (api.ts's axios interceptor reads it
  // from the Zustand 'finventory-auth' store) — NOT a cookie — so
  // page.request (Playwright's separate API-request context) does not
  // automatically inherit it the way a real <a> click in the browser would.
  // Read the same access token + org id the app itself uses and attach them
  // explicitly; confirmed via curl that the endpoint 401s with no header and
  // 200s with a valid one, i.e. the auth gate itself is working correctly —
  // this was a test gap, not a security regression.
  const authState = await page.evaluate(() => {
    const raw = localStorage.getItem('finventory-auth')
    return raw ? JSON.parse(raw)?.state : null
  })
  const accessToken = authState?.tokens?.access
  const orgId = authState?.organisation?.id
  expect(accessToken).toBeTruthy()

  const resp = await page.request.get(href!, {
    headers: {
      Authorization: `Bearer ${accessToken}`,
      ...(orgId ? { 'X-Organisation-ID': orgId } : {}),
    },
  })
  expect(resp.ok()).toBeTruthy()
  const body = await resp.text()
  expect(body).toContain('Audity messaging attachment E2E fixture.')
})

test('a second same-org user sees the conversation and can reply (two-way visibility)', async ({ browser }) => {
  // storageState: undefined is required — the `today` project's config sets
  // use.storageState to the already-authenticated user-1 session, and
  // browser.newContext() with no override inherits that project-level
  // default (confirmed live: without this, the fresh context lands directly
  // on /dashboard as browsertest@audity.local instead of showing a login
  // form for browsertest2@audity.local, so the login fields below never
  // render and the fill() call times out).
  const context = await browser.newContext({ storageState: undefined })
  const page = await context.newPage()
  await page.goto('/')
  await page.getByPlaceholder('you@company.com').fill('browsertest2@audity.local')
  await page.locator('input[type="password"]').first().fill('BrowserTest123!')
  await page.locator('button[type="submit"]').click()
  await expect(page).toHaveURL(/\/dashboard/, { timeout: 45_000 })
  await dismissTermsGateIfPresent(page)

  await page.goto('/messages')
  await expect(page.getByRole('heading', { name: 'Messages' })).toBeVisible({ timeout: 30_000 })
  // TermsGateModal's own re-acceptance check (authApi.profile(), in a
  // useEffect) can resolve AFTER the dashboard has already rendered, so the
  // gate can pop up moments later — including after this second goto() — and
  // still be sitting on top of the page (z-[70], viewport-covering) when the
  // click below fires. Confirmed live: the first dismiss call above can run
  // before the gate has appeared at all, finds nothing, and the gate then
  // shows up on /messages afterward. Check again right before the click that
  // actually needs a clear click-path.
  await dismissTermsGateIfPresent(page)

  const convRow = page.locator('button', { hasText: 'browsertest@audity.local' }).first()
  await expect(convRow).toBeVisible({ timeout: 20_000 })
  await convRow.click()

  // Sees the first user's message and the attachment sent in the prior test.
  await expect(page.getByText('Hello from the E2E run — real browser, real click.')).toBeVisible({ timeout: 15_000 })
  await expect(page.locator('a', { hasText: 'today-messaging-attachment.txt' })).toBeVisible()

  const composer = page.getByPlaceholder('Type a message…')
  await composer.fill('Reply from the second same-org user.')
  await page.getByLabel('Send message').click()
  await expect(page.getByText('Reply from the second same-org user.')).toBeVisible({ timeout: 15_000 })

  await context.close()
})

test('a user in a different organisation cannot see or reach this conversation', async ({ browser }) => {
  // storageState: undefined — same reason as the test above: without this
  // override, this context would inherit the `today` project's default
  // (already logged in as browsertest@audity.local) instead of starting
  // logged-out so the outsider login actually happens.
  const context = await browser.newContext({ storageState: undefined })
  const page = await context.newPage()
  await page.goto('/')
  await page.getByPlaceholder('you@company.com').fill('outsider@audity.local')
  await page.locator('input[type="password"]').first().fill('BrowserTest123!')
  await page.locator('button[type="submit"]').click()
  // The outsider's org has no completed onboarding/subscription, but a
  // membership still exists, so ProtectedRoute must not bounce them to
  // /onboarding — ends up on /dashboard or /me depending on role.
  await expect(page).toHaveURL(/\/(dashboard|me)/, { timeout: 45_000 })
  await dismissTermsGateIfPresent(page)

  await page.goto('/messages')
  await expect(page.getByRole('heading', { name: 'Messages' })).toBeVisible({ timeout: 30_000 })
  // See the comment on the equivalent second call in the previous test — the
  // gate can appear after this navigation even when the first check found
  // nothing.
  await dismissTermsGateIfPresent(page)

  // No Browser Test Org content should ever appear for this user.
  await expect(page.getByText('browsertest@audity.local')).toHaveCount(0)
  await expect(page.getByText('browsertest2@audity.local')).toHaveCount(0)
  await expect(page.getByText('Hello from the E2E run')).toHaveCount(0)

  // Directly hitting the conversation's search-param deep link must not leak
  // its content either — the backend must scope by participant, not just by
  // "is this a valid conversation id".
  const convId = process.env.E2E_SEEDED_CONVERSATION_ID
  if (convId) {
    await page.goto(`/messages?c=${convId}`)
    await expect(page.getByText('Hello from the E2E run')).toHaveCount(0)
  }

  await context.close()
})

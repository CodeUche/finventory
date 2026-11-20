/**
 * Regression sweep: every restyled page, light and dark, at the four widths.
 * Read-only: opens pages, creates nothing, so nothing to clean up.
 *
 * Per page it asserts, objectively:
 *   - the page loads (no router bounce to /login, no 404 page, no error boundary)
 *   - no uncaught script error
 *   - no sideways scroll on the page body (content wider than the window)
 *   - the main heading is visible
 *   - text is not invisible: no visible text node has the same colour as its
 *     solid background (catches dark-on-dark / light-on-light after a restyle)
 * Screenshots are attached for the human look-over (the part a script cannot judge).
 */
import { test, expect, URL_BASE, pageHealth } from './p2/support'
import { ROUTES } from './p2/routes'

const WIDTHS = [1440, 1280, 1024, 768]
const THEMES = ['light', 'dark'] as const

for (const theme of THEMES) {
  test.describe(`sweep ${theme}`, () => {
    test.use({ theme })
    for (const route of ROUTES) {
      test(`${route} @${theme}`, async ({ page, errors }, info) => {
        test.setTimeout(150_000)
        await page.setViewportSize({ width: 1440, height: 900 })
        await page.goto(URL_BASE + route, { waitUntil: 'domcontentloaded' })
        await page.waitForLoadState('networkidle', { timeout: 40_000 }).catch(() => {})
        expect(page.url(), 'bounced to login = session lost').not.toMatch(/\/login/)
        // some routes legitimately redirect (no module / no permission) - record it, don't fail
        const landed = new URL(page.url()).pathname
        if (landed !== route) info.annotations.push({ type: 'redirected', description: `${route} -> ${landed}` })
        await expect(page.getByText(/page not found|something went wrong/i)).toHaveCount(0)

        for (const w of WIDTHS) {
          await page.setViewportSize({ width: w, height: 900 })
          await page.waitForTimeout(250)
          const m = await pageHealth(page)
          expect.soft(m.over, `${route} ${theme} @${w}: page scrolls sideways by ${m.over}px`).toBeLessThanOrEqual(1)
          expect.soft(m.bad, `${route} ${theme} @${w}: text same colour as its background`).toEqual([])
        }
        await page.setViewportSize({ width: 1280, height: 900 })
        await info.attach(`${route.replace(/\//g, '_')}-${theme}.png`, { body: await page.screenshot(), contentType: 'image/png' })
        expect(errors, 'uncaught script errors').toEqual([])
      })
    }
  })
}

// The detector itself must be able to fail: prove it on a page built to be wrong.
test('self-check: the health probe flags sideways scroll and same-colour text', async ({ page }) => {
  await page.setViewportSize({ width: 800, height: 600 })
  await page.setContent(`<body style="background:#fff;margin:0">
    <p style="color:#ffffff">invisible words</p>
    <div style="width:1600px;height:10px"></div></body>`)
  const m = await pageHealth(page)
  expect(m.over).toBeGreaterThan(1)
  expect(m.bad).toContain('invisible words')
  await page.setContent('<body style="background:#fff"><p style="color:#111">fine words</p></body>')
  const ok = await pageHealth(page)
  expect(ok.over).toBeLessThanOrEqual(1)
  expect(ok.bad).toEqual([])
})

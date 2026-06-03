/**
 * Shared E2E helpers — imported by all spec files.
 *
 * Update this file whenever a new page, route, or auth pattern is added.
 */

import { Page, expect } from "@playwright/test";

export const EMAIL = process.env.TEST_EMAIL    || "";
export const PASS  = process.env.TEST_PASSWORD || "";

/**
 * True when real credentials are configured.
 * Tests that require login call `skipIfNoCredentials()` at the top so they
 * appear as ⊘ skipped (not ✘ failed) when secrets aren't set in CI.
 */
export const hasCredentials = Boolean(EMAIL && PASS);

/** Call at the top of any test that needs a logged-in session. */
export function skipIfNoCredentials(test: { skip(reason?: string): void }) {
  if (!hasCredentials) {
    test.skip("TEST_EMAIL / TEST_PASSWORD secrets not configured — skipping auth-dependent test");
  }
}

/**
 * Log in and navigate to `path`.
 *
 * Fixes vs. old version:
 * - Timeout raised to 25 s to survive Railway cold-starts.
 * - Always navigates to the requested path, even when path === "/dashboard".
 *   (Old code skipped the goto for "/dashboard", leaving the page on whatever
 *   the login redirect went to — e.g. /platform-admin for superusers.)
 * - Waits for the page to leave /login before navigating, so the session
 *   cookie is set before we hit a protected route.
 */
export async function loginAndGo(page: Page, path = "/dashboard") {
  await page.goto("/login");
  await page.locator('input[type="email"]').fill(EMAIL);
  await page.locator('input[type="password"]').first().fill(PASS);
  await page.locator('button[type="submit"]').click();
  // Wait for post-login redirect — any URL that is not /login.
  // 25 s covers Railway cold-start latency (~20 s on the free tier).
  await page.waitForURL(url => !url.pathname.includes("/login"), { timeout: 25_000 });
  // Always navigate to the target path so tests land where they expect.
  await page.goto(path);
}

/** Assert a page loaded — checks for heading OR table OR empty-state text. */
export async function expectPageContent(
  page: Page,
  heading: RegExp,
  emptyText?: RegExp
) {
  const locator = emptyText
    ? page.getByRole("heading", { name: heading }).or(page.getByText(emptyText))
    : page.getByRole("heading", { name: heading });
  await expect(locator).toBeVisible({ timeout: 8_000 });
}

/** Skip a test gracefully if there's no data in a list page. */
export async function skipIfEmpty(page: Page) {
  const firstRow = page.getByRole("row").nth(1);
  if (!(await firstRow.isVisible())) return true;
  return false;
}

/** Assert that a modal / dialog opened after clicking a button. */
export async function clickAndExpectModal(
  page: Page,
  buttonLocator: Parameters<Page["getByRole"]>[1],
  modalHeading: RegExp
) {
  await page.getByRole("button", buttonLocator as any).click();
  await expect(
    page.getByRole("dialog").or(page.getByRole("heading", { name: modalHeading }))
  ).toBeVisible({ timeout: 6_000 });
}

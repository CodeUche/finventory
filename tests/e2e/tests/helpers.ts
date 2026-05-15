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

/** Log in and optionally navigate to `path`. Waits for dashboard URL before redirect. */
export async function loginAndGo(page: Page, path = "/dashboard") {
  await page.goto("/login");
  await page.locator('input[type="email"]').fill(EMAIL);
  await page.locator('input[type="password"]').first().fill(PASS);
  await page.locator('button[type="submit"]').click();
  // Wait for either success (dashboard) or failure (stays on /login with error)
  await page.waitForURL(url => !url.pathname.includes("/login"), { timeout: 15_000 });
  if (path !== "/dashboard" && path !== "/") await page.goto(path);
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

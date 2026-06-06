/**
 * Shared E2E helpers — imported by all spec files.
 */

import { Page, expect } from "@playwright/test";
import * as fs from "fs";
import * as path from "path";

export const EMAIL = process.env.TEST_EMAIL    || "";
export const PASS  = process.env.TEST_PASSWORD || "";

/**
 * True when real credentials are configured.
 */
export const hasCredentials = Boolean(EMAIL && PASS);

// ─── Login-validity flag ──────────────────────────────────────────────────────
// global-setup.ts writes a sentinel file when the login pre-check fails.
// Workers read it here at module load time so all credential-dependent tests
// skip instantly rather than timing out.

// helpers.ts is at tests/e2e/tests/ — sentinel lives one level up at tests/e2e/
const LOGIN_FAILED_SENTINEL = path.join(__dirname, "..", ".login-failed");

function _readLoginWorksFlag(): boolean {
  try {
    return !fs.existsSync(LOGIN_FAILED_SENTINEL);
  } catch {
    return true; // default: assume login works until proven otherwise
  }
}

/** True if global-setup determined that the test credentials are valid. */
export const credentialsWork: boolean = hasCredentials && _readLoginWorksFlag();

// ─── Helpers ──────────────────────────────────────────────────────────────────

/** Call at the top of any test that needs a logged-in session. */
export function skipIfNoCredentials(test: { skip(reason?: string): void }) {
  if (!hasCredentials) {
    test.skip("TEST_EMAIL / TEST_PASSWORD secrets not configured — skipping auth-dependent test");
  }
}

/**
 * Log in and navigate to `path`.
 *
 * Fails fast (≤5 s) when login is rejected rather than waiting 25 s.
 * Uses a Promise.race between the redirect URL change and a timeout; if
 * the redirect doesn't happen the credentials are bad.
 */
export async function loginAndGo(page: Page, path = "/dashboard") {
  await page.goto("/login");
  await page.locator('input[type="email"]').fill(EMAIL);
  await page.locator('input[type="password"]').first().fill(PASS);
  await page.locator('button[type="submit"]').click();

  // Fast failure: if still on /login after 5 s, credentials were rejected.
  // This surfaces as a clear error instead of a 25 s timeout.
  const redirected = await page
    .waitForURL(url => !url.pathname.includes("/login"), { timeout: 5_000 })
    .then(() => true)
    .catch(() => false);

  if (!redirected) {
    throw new Error(
      "LOGIN FAILED — page stayed on /login after submit. " +
      "Check that TEST_EMAIL / TEST_PASSWORD GitHub secrets match a real user " +
      "on the Railway production database."
    );
  }

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

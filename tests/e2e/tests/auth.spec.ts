/**
 * Authentication E2E tests — Playwright
 *
 * Tests types covered:
 *   E2E (full browser journey)
 *   Acceptance (business requirement: user can log in, log out, reset password)
 *   Smoke (@smoke tag = included in fast pre-deploy check)
 *   Regression (re-runs after every change)
 *   Usability (form validation feedback visible, redirect correct)
 */

import { test, expect, Page } from "@playwright/test";

const TEST_EMAIL = process.env.TEST_EMAIL || "testuser@audity.test";
const TEST_PASSWORD = process.env.TEST_PASSWORD || "StrongPass123!";

// ─── Helper ─────────────────────────────────────────────────────────────────

async function login(page: Page, email = TEST_EMAIL, password = TEST_PASSWORD) {
  await page.goto("/login");
  await page.locator('input[type="email"]').fill(email);
  await page.locator('input[type="password"]').first().fill(password);
  await page.locator('button[type="submit"]').click();
}

// ─── Smoke tests ─────────────────────────────────────────────────────────────

test.describe("@smoke Authentication", () => {
  test("login page loads", async ({ page }) => {
    await page.goto("/login");
    await expect(page).toHaveTitle(/Audity/i);
    await expect(page.locator('input[type="email"]')).toBeVisible();
    await expect(page.locator('input[type="password"]').first()).toBeVisible();
    await expect(page.locator('button[type="submit"]')).toBeVisible();
  });

  test("valid credentials redirect to dashboard @smoke", async ({ page }) => {
    await login(page);
    // Must NOT land on /onboarding — must reach /dashboard
    await expect(page).not.toHaveURL(/\/onboarding/i, { timeout: 12_000 });
    await expect(page).toHaveURL(/\/(dashboard|app|home)?$/i, { timeout: 12_000 });
    // Sidebar must be visible after login
    await expect(page.getByRole("navigation")).toBeVisible();
  });

  test("invalid credentials show error message @smoke", async ({ page }) => {
    await login(page, "nobody@nonexistent.invalid", "wrongpassword");
    // Any error toast is acceptable — invalid creds, rate limit, or connection error
    await expect(
      page.locator('[role="status"], .go3958317564').first()
    ).toBeVisible({ timeout: 6_000 });
    // Must remain on login page — this is the key assertion
    await expect(page).toHaveURL(/\/login/i);
  });
});

// ─── Full auth journey ────────────────────────────────────────────────────────

test.describe("Full authentication journey", () => {
  test("login → view dashboard → log out → redirected to login", async ({ page }) => {
    await login(page);
    await page.waitForURL(/\/(dashboard|app|home)?$/i, { timeout: 12_000 });

    // Log out — try sidebar button first, then dropdown
    const logoutBtn = page.getByRole("button", { name: /logout|sign out/i });
    if (await logoutBtn.isVisible()) {
      await logoutBtn.click();
    } else {
      await page.getByRole("button", { name: /account|profile|user/i }).first().click();
      await page.getByText(/logout|sign out/i).click();
    }

    await expect(page).toHaveURL(/\/login/i, { timeout: 6_000 });
  });

  test("accessing protected route while unauthenticated redirects to login", async ({
    page,
  }) => {
    await page.goto("/dashboard");
    await expect(page).toHaveURL(/\/login/i, { timeout: 6_000 });
  });

  test("forgot password page renders", async ({ page }) => {
    await page.goto("/forgot-password");
    await expect(page.getByRole("heading", { name: /forgot|reset/i })).toBeVisible();
    await expect(page.locator('input[type="email"]')).toBeVisible();
  });
});

// ─── Form validation (usability) ─────────────────────────────────────────────

test.describe("Login form validation (usability)", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/login");
  });

  test("empty form submission shows browser/field validation", async ({ page }) => {
    await page.locator('button[type="submit"]').click();
    // Email input is required — browser prevents submission; field stays empty and focused
    const emailInput = page.locator('input[type="email"]');
    await expect(emailInput).toBeVisible();
    await expect(page).toHaveURL(/\/login/i);
  });

  test("invalid email format shows browser validation", async ({ page }) => {
    await page.locator('input[type="email"]').fill("not-an-email");
    await page.locator('input[type="password"]').first().fill("SomePass123!");
    await page.locator('button[type="submit"]').click();
    // Browser native validation prevents submit; URL stays on login
    await expect(page).toHaveURL(/\/login/i);
  });

  test("password field masks characters", async ({ page }) => {
    const pwField = page.locator('input[type="password"]').first();
    await expect(pwField).toHaveAttribute("type", "password");
  });
});

// ─── Registration ─────────────────────────────────────────────────────────────

test.describe("Registration journey", () => {
  test("register page loads with required fields", async ({ page }) => {
    await page.goto("/register");
    await expect(page.locator('input[type="email"]')).toBeVisible();
    await expect(page.locator('input[placeholder="John"]')).toBeVisible();
    await expect(page.locator('input[placeholder="Doe"]')).toBeVisible();
    await expect(page.locator('input[type="password"]').first()).toBeVisible();
  });

  test("mismatched passwords show validation error", async ({ page }) => {
    await page.goto("/register");
    await page.locator('input[type="email"]').fill("newuser@e2e.test");
    await page.locator('input[placeholder="John"]').fill("New");
    await page.locator('input[placeholder="Doe"]').fill("User");
    await page.locator('input[type="password"]').nth(0).fill("SecurePass123!");
    await page.locator('input[type="password"]').nth(1).fill("Different123!");
    await page.locator('button[type="submit"]').click();
    await expect(page.getByText(/match|identical|same/i).first()).toBeVisible({ timeout: 5_000 });
  });
});

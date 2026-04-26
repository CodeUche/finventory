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
  await page.getByLabel(/email/i).fill(email);
  await page.getByLabel(/password/i).fill(password);
  await page.getByRole("button", { name: /sign in|log in/i }).click();
}

// ─── Smoke tests ─────────────────────────────────────────────────────────────

test.describe("@smoke Authentication", () => {
  test("login page loads", async ({ page }) => {
    await page.goto("/login");
    await expect(page).toHaveTitle(/Audity/i);
    await expect(page.getByLabel(/email/i)).toBeVisible();
    await expect(page.getByLabel(/password/i)).toBeVisible();
    await expect(page.getByRole("button", { name: /sign in|log in/i })).toBeVisible();
  });

  test("valid credentials redirect to dashboard @smoke", async ({ page }) => {
    await login(page);
    await expect(page).toHaveURL(/\/(dashboard|app|home)?$/i, { timeout: 10_000 });
    // Sidebar must be visible after login
    await expect(page.getByRole("navigation")).toBeVisible();
  });

  test("invalid credentials show error message @smoke", async ({ page }) => {
    await login(page, TEST_EMAIL, "wrongpassword");
    await expect(
      page.getByText(/invalid|incorrect|wrong|not found/i)
    ).toBeVisible({ timeout: 5_000 });
    // Must remain on login page
    await expect(page).toHaveURL(/\/login/i);
  });
});

// ─── Full auth journey ────────────────────────────────────────────────────────

test.describe("Full authentication journey", () => {
  test("login → view dashboard → log out → redirected to login", async ({ page }) => {
    await login(page);
    await page.waitForURL(/\/(dashboard|app|home)?$/i, { timeout: 10_000 });

    // Log out
    const logoutBtn = page.getByRole("button", { name: /logout|sign out/i });
    if (await logoutBtn.isVisible()) {
      await logoutBtn.click();
    } else {
      // Find logout in a dropdown/menu
      await page.getByRole("button", { name: /account|profile|user/i }).first().click();
      await page.getByText(/logout|sign out/i).click();
    }

    await expect(page).toHaveURL(/\/login/i, { timeout: 5_000 });
  });

  test("accessing protected route while unauthenticated redirects to login", async ({
    page,
  }) => {
    await page.goto("/dashboard");
    await expect(page).toHaveURL(/\/login/i, { timeout: 5_000 });
  });

  test("forgot password page renders", async ({ page }) => {
    await page.goto("/forgot-password");
    await expect(page.getByRole("heading", { name: /forgot|reset/i })).toBeVisible();
    await expect(page.getByLabel(/email/i)).toBeVisible();
  });
});

// ─── Form validation (usability) ─────────────────────────────────────────────

test.describe("Login form validation (usability)", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/login");
  });

  test("empty form submission shows field errors", async ({ page }) => {
    await page.getByRole("button", { name: /sign in|log in/i }).click();
    // At least one validation error should appear
    const errors = page.getByText(/required|invalid|enter/i);
    await expect(errors.first()).toBeVisible();
  });

  test("invalid email format shows error", async ({ page }) => {
    await page.getByLabel(/email/i).fill("not-an-email");
    await page.getByLabel(/password/i).fill("SomePass123!");
    await page.getByRole("button", { name: /sign in|log in/i }).click();
    await expect(page.getByText(/valid email|invalid email/i)).toBeVisible();
  });

  test("password field masks characters", async ({ page }) => {
    const pwField = page.getByLabel(/password/i);
    await expect(pwField).toHaveAttribute("type", "password");
  });
});

// ─── Registration ─────────────────────────────────────────────────────────────

test.describe("Registration journey", () => {
  test("register page loads with required fields", async ({ page }) => {
    await page.goto("/register");
    await expect(page.getByLabel(/email/i)).toBeVisible();
    await expect(page.getByLabel(/first name/i)).toBeVisible();
    await expect(page.getByLabel(/last name/i)).toBeVisible();
    await expect(page.getByLabel(/^password$/i)).toBeVisible();
  });

  test("mismatched passwords show validation error", async ({ page }) => {
    await page.goto("/register");
    await page.getByLabel(/email/i).fill("newuser@e2e.test");
    await page.getByLabel(/first name/i).fill("New");
    await page.getByLabel(/last name/i).fill("User");
    await page.getByLabel(/^password$/i).fill("SecurePass123!");
    await page.getByLabel(/confirm password/i).fill("Different123!");
    await page.getByRole("button", { name: /register|sign up|create/i }).click();
    await expect(page.getByText(/match|identical|same/i)).toBeVisible();
  });
});

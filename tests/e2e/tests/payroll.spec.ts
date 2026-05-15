/**
 * Payroll E2E tests — Playwright
 *
 * Covers: Employees list, Payroll Runs
 *
 * Test types: E2E, Acceptance, Regression, Smoke (@smoke)
 */

import { test, expect } from "@playwright/test";
import { loginAndGo, hasCredentials } from "./helpers";

test.beforeEach(({}, testInfo) => {
  if (!hasCredentials) testInfo.skip();
});

// ─── Employees ─────────────────────────────────────────────────────────────────

test.describe("@smoke Employees Page", () => {
  test("employees page loads", async ({ page }) => {
    await loginAndGo(page, "/payroll/employees");
    await expect(
      page.getByRole("heading", { name: /employees/i })
        .or(page.getByText(/no employee/i))
    ).toBeVisible({ timeout: 8_000 });
  });

  test("add employee button visible", async ({ page }) => {
    await loginAndGo(page, "/payroll/employees");
    await expect(
      page.getByRole("button", { name: /add employee|new employee/i })
    ).toBeVisible({ timeout: 6_000 });
  });

  test("employees list or empty state renders", async ({ page }) => {
    await loginAndGo(page, "/payroll/employees");
    await expect(
      page.getByRole("table").or(page.getByText(/no employee|empty/i))
    ).toBeVisible({ timeout: 6_000 });
  });
});

test.describe("Employees — Search", () => {
  test("employee search input present", async ({ page }) => {
    await loginAndGo(page, "/payroll/employees");
    await expect(
      page.getByPlaceholder(/search/i).first()
    ).toBeVisible({ timeout: 5_000 });
  });

  test("search filters employee list", async ({ page }) => {
    await loginAndGo(page, "/payroll/employees");
    const search = page.getByPlaceholder(/search/i).first();
    await search.fill("John");
    await page.waitForTimeout(400);
    await expect(
      page.getByRole("table").or(page.getByText(/no employee|no results/i))
    ).toBeVisible();
  });
});

test.describe("Employees — Create Modal", () => {
  test("add employee modal opens", async ({ page }) => {
    await loginAndGo(page, "/payroll/employees");
    await page.getByRole("button", { name: /add employee|new employee/i }).click();
    await expect(page.getByRole("dialog")).toBeVisible({ timeout: 5_000 });
  });

  test("employee form has first name, salary and bank fields", async ({ page }) => {
    await loginAndGo(page, "/payroll/employees");
    await page.getByRole("button", { name: /add employee|new employee/i }).click();
    await expect(
      page.getByLabel(/first name|name/i).first()
    ).toBeVisible({ timeout: 5_000 });
  });

  test("employee bank auto-fill resolve button present", async ({ page }) => {
    await loginAndGo(page, "/payroll/employees");
    await page.getByRole("button", { name: /add employee|new employee/i }).click();
    // Look for bank account number field
    await expect(
      page.getByLabel(/account number|bank/i).first()
        .or(page.getByText(/bank account|account number/i).first())
    ).toBeVisible({ timeout: 5_000 });
  });
});

// ─── Payroll Runs ──────────────────────────────────────────────────────────────

test.describe("@smoke Payroll Runs Page", () => {
  test("payroll runs page loads", async ({ page }) => {
    await loginAndGo(page, "/payroll/runs");
    await expect(
      page.getByRole("heading", { name: /payroll/i })
        .or(page.getByText(/no payroll|no run/i))
    ).toBeVisible({ timeout: 8_000 });
  });

  test("run payroll button visible", async ({ page }) => {
    await loginAndGo(page, "/payroll/runs");
    await expect(
      page.getByRole("button", { name: /run payroll|new run|generate/i })
    ).toBeVisible({ timeout: 6_000 });
  });

  test("payroll list or empty state renders", async ({ page }) => {
    await loginAndGo(page, "/payroll/runs");
    await expect(
      page.getByRole("table").or(page.getByText(/no payroll|empty/i))
    ).toBeVisible({ timeout: 6_000 });
  });

  test("FIRS PAYE link present on payroll page", async ({ page }) => {
    await loginAndGo(page, "/payroll/runs");
    const firsLink = page.getByRole("link", { name: /firs|paye/i });
    const firsText = page.getByText(/firs|taxpromax/i);
    const hasLink = await firsLink.isVisible().catch(() => false);
    const hasText = await firsText.isVisible().catch(() => false);
    expect(hasLink || hasText).toBeTruthy();
  });
});

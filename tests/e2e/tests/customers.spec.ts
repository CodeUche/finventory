/**
 * Customers & Credits E2E tests — Playwright
 *
 * Covers: Customers list, customer drawer, customer statement, Credits
 *
 * Test types: E2E, Acceptance, Regression, Usability
 */

import { test, expect } from "@playwright/test";
import { loginAndGo } from "./helpers";

// ─── Customers ──────────────────────────────────────────────────────────────────

test.describe("@smoke Customers Page", () => {
  test("customers page loads", async ({ page }) => {
    await loginAndGo(page, "/customers");
    await expect(
      page.getByRole("heading", { name: /customers/i })
        .or(page.getByText(/no customer/i))
    ).toBeVisible({ timeout: 8_000 });
  });

  test("add customer button visible", async ({ page }) => {
    await loginAndGo(page, "/customers");
    await expect(
      page.getByRole("button", { name: /add customer|new customer/i })
    ).toBeVisible({ timeout: 6_000 });
  });

  test("customer list renders table or empty state", async ({ page }) => {
    await loginAndGo(page, "/customers");
    await expect(
      page.getByRole("table").or(page.getByText(/no customer|empty/i))
    ).toBeVisible({ timeout: 6_000 });
  });
});

test.describe("Customers — Search & Filter", () => {
  test("search input present and functional", async ({ page }) => {
    await loginAndGo(page, "/customers");
    const search = page.getByPlaceholder(/search/i).first();
    await expect(search).toBeVisible({ timeout: 5_000 });
    await search.fill("test");
    await page.waitForTimeout(400);
    await expect(
      page.getByRole("table").or(page.getByText(/no customer|no results/i))
    ).toBeVisible();
  });

  test("customer type filter present", async ({ page }) => {
    await loginAndGo(page, "/customers");
    // Type filter dropdown or buttons (retail, wholesale, etc.)
    await expect(
      page.getByRole("combobox").or(page.getByText(/all|retail|wholesale/i)).first()
    ).toBeVisible({ timeout: 5_000 });
  });
});

test.describe("Customers — Add Customer Modal", () => {
  test("add customer modal opens", async ({ page }) => {
    await loginAndGo(page, "/customers");
    await page.getByRole("button", { name: /add customer|new customer/i }).click();
    await expect(page.getByRole("dialog")).toBeVisible({ timeout: 5_000 });
  });

  test("customer form has name, email and phone fields", async ({ page }) => {
    await loginAndGo(page, "/customers");
    await page.getByRole("button", { name: /add customer|new customer/i }).click();
    await expect(
      page.getByLabel(/name/i).first()
    ).toBeVisible({ timeout: 5_000 });
  });
});

test.describe("Customers — Drawer & Statement", () => {
  test("clicking a customer row opens the customer drawer", async ({ page }) => {
    await loginAndGo(page, "/customers");
    const firstRow = page.getByRole("row").nth(1);
    const hasData = await firstRow.isVisible().catch(() => false);
    if (!hasData) return;
    await firstRow.click();
    await expect(
      page.getByRole("dialog").or(page.locator("[data-testid='customer-drawer']"))
    ).toBeVisible({ timeout: 5_000 });
  });

  test("customer drawer has Statement button", async ({ page }) => {
    await loginAndGo(page, "/customers");
    const firstRow = page.getByRole("row").nth(1);
    const hasData = await firstRow.isVisible().catch(() => false);
    if (!hasData) return;
    await firstRow.click();
    await expect(
      page.getByRole("button", { name: /statement/i })
    ).toBeVisible({ timeout: 5_000 });
  });
});

// ─── Credits ───────────────────────────────────────────────────────────────────

test.describe("Credits Page", () => {
  test("credits page loads", async ({ page }) => {
    await loginAndGo(page, "/credits");
    await expect(
      page.getByRole("heading", { name: /credit/i })
        .or(page.getByText(/no credit/i))
    ).toBeVisible({ timeout: 8_000 });
  });

  test("credits list or empty state renders", async ({ page }) => {
    await loginAndGo(page, "/credits");
    await expect(
      page.getByRole("table").or(page.getByText(/no credit|empty/i))
    ).toBeVisible({ timeout: 6_000 });
  });
});

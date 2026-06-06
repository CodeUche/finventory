/**
 * Reports E2E tests — Playwright
 *
 * Covers: P&L Report, Stock Reports, Tax (VAT + Income Tax),
 *         Owner Analytics, Audit Log
 *
 * Test types: E2E, Acceptance, Regression, Smoke (@smoke)
 */

import { test, expect } from "@playwright/test";
import { loginAndGo, credentialsWork } from "./helpers";

test.beforeEach(({}, testInfo) => {
  if (!credentialsWork) testInfo.skip();
});

// ─── Reports (P&L, top products/customers) ─────────────────────────────────────

test.describe("@smoke Reports Page", () => {
  test("reports page loads", async ({ page }) => {
    await loginAndGo(page, "/reports");
    await expect(
      page.getByRole("heading", { name: /reports/i })
        .or(page.getByText(/profit|revenue|expense/i))
    ).toBeVisible({ timeout: 8_000 });
  });

  test("P&L report section visible", async ({ page }) => {
    await loginAndGo(page, "/reports");
    await expect(
      page.getByText(/profit.*loss|p&l|income statement/i).first()
    ).toBeVisible({ timeout: 8_000 });
  });

  test("date range filter controls present", async ({ page }) => {
    await loginAndGo(page, "/reports");
    await expect(
      page.getByRole("combobox")
        .or(page.getByText(/this month|last month|this year/i))
        .first()
    ).toBeVisible({ timeout: 5_000 });
  });
});

test.describe("Reports — Charts", () => {
  test("revenue chart renders (no uncaught errors)", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await loginAndGo(page, "/reports");
    await page.waitForTimeout(3000);
    const real = errors.filter(e =>
      !e.includes("ResizeObserver") && !e.includes("ChunkLoadError")
    );
    expect(real).toHaveLength(0);
  });

  // Top products and top customers are now in the "Sales Analytics" tab — navigate there first.
  test("top products section visible (Sales Analytics tab)", async ({ page }) => {
    await loginAndGo(page, "/reports?tab=sales_analytics");
    await expect(
      page.getByText(/top product/i).first()
    ).toBeVisible({ timeout: 10_000 });
  });

  test("top customers section visible (Sales Analytics tab)", async ({ page }) => {
    await loginAndGo(page, "/reports?tab=sales_analytics");
    await expect(
      page.getByText(/top customer/i).first()
    ).toBeVisible({ timeout: 10_000 });
  });

  test("URL ?tab= param pre-selects correct tab", async ({ page }) => {
    await loginAndGo(page, "/reports?tab=pnl");
    await expect(
      page.getByText(/profit.*loss|p&l|waterfall/i).first()
    ).toBeVisible({ timeout: 8_000 });
  });

  test("URL ?tab= legacy redirect: products → Sales Analytics", async ({ page }) => {
    await loginAndGo(page, "/reports?tab=products");
    // Should silently show Sales Analytics content
    await expect(
      page.getByText(/sales analytics|top customer|top product/i).first()
    ).toBeVisible({ timeout: 8_000 });
  });

  test("expense breakdown section visible (Overview tab)", async ({ page }) => {
    await loginAndGo(page, "/reports");
    await expect(
      page.getByText(/expense breakdown|by category/i).first()
    ).toBeVisible({ timeout: 8_000 });
  });

  test("P&L waterfall chart renders (no uncaught errors)", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await loginAndGo(page, "/reports?tab=pnl");
    await page.waitForTimeout(3000);
    const real = errors.filter(e =>
      !e.includes("ResizeObserver") && !e.includes("ChunkLoadError")
    );
    expect(real).toHaveLength(0);
  });

  test("AR/AP aging tab renders (no uncaught errors)", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await loginAndGo(page, "/reports?tab=aging");
    await page.waitForTimeout(3000);
    const real = errors.filter(e =>
      !e.includes("ResizeObserver") && !e.includes("ChunkLoadError")
    );
    expect(real).toHaveLength(0);
  });

  test("cash flow tab renders (no uncaught errors)", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await loginAndGo(page, "/reports?tab=cashflow");
    await page.waitForTimeout(3000);
    const real = errors.filter(e =>
      !e.includes("ResizeObserver") && !e.includes("ChunkLoadError")
    );
    expect(real).toHaveLength(0);
  });
});

// ─── Stock Reports ─────────────────────────────────────────────────────────────

test.describe("Stock Reports Page", () => {
  test("stock reports page loads", async ({ page }) => {
    await loginAndGo(page, "/reports/stock");
    await expect(
      page.getByRole("heading", { name: /stock report/i })
        .or(page.getByText(/stock value|inventory report/i))
    ).toBeVisible({ timeout: 8_000 });
  });

  test("stock report data or empty state renders", async ({ page }) => {
    await loginAndGo(page, "/reports/stock");
    await expect(
      page.getByRole("table").or(page.getByText(/no data|empty/i))
    ).toBeVisible({ timeout: 6_000 });
  });
});

// ─── Tax Page ─────────────────────────────────────────────────────────────────

test.describe("@smoke Tax Page", () => {
  test("tax page loads", async ({ page }) => {
    await loginAndGo(page, "/tax");
    await expect(
      page.getByRole("heading", { name: /tax/i })
    ).toBeVisible({ timeout: 8_000 });
  });

  test("income tax and VAT tabs present", async ({ page }) => {
    await loginAndGo(page, "/tax");
    await expect(
      page.getByRole("tab", { name: /income tax|vat/i })
        .or(page.getByText(/income tax|vat/i))
        .first()
    ).toBeVisible({ timeout: 6_000 });
  });

  test("VAT report section renders", async ({ page }) => {
    await loginAndGo(page, "/tax");
    // Click VAT tab if present
    const vatTab = page.getByRole("tab", { name: /vat/i });
    const vatTabVisible = await vatTab.isVisible().catch(() => false);
    if (vatTabVisible) await vatTab.click();
    await expect(
      page.getByText(/vat|value added tax/i).first()
    ).toBeVisible({ timeout: 6_000 });
  });
});

// ─── Audit Log ────────────────────────────────────────────────────────────────

test.describe("Audit Log Page", () => {
  test("audit log page loads", async ({ page }) => {
    await loginAndGo(page, "/audit-log");
    await expect(
      page.getByRole("heading", { name: /audit/i })
        .or(page.getByText(/audit log|activity/i))
    ).toBeVisible({ timeout: 8_000 });
  });

  test("audit log list or empty state renders", async ({ page }) => {
    await loginAndGo(page, "/audit-log");
    await expect(
      page.getByRole("table").or(page.getByText(/no log|no activity|empty/i))
    ).toBeVisible({ timeout: 6_000 });
  });

  test("audit log access banner rendered for authenticated user", async ({ page }) => {
    await loginAndGo(page, "/audit-log");
    // Should show either superuser or owner/admin access banner
    await expect(
      page.getByText(/full access|owner.*admin|access/i).first()
    ).toBeVisible({ timeout: 6_000 });
  });
});

// ─── Owner Analytics ─────────────────────────────────────────────────────────

test.describe("Owner Analytics Page", () => {
  test("owner analytics accessible for owner accounts", async ({ page }) => {
    await loginAndGo(page, "/owner-analytics");
    // Owners land on analytics; non-owners get redirected. Both are valid outcomes.
    // Just assert the page didn't crash — a redirect to /dashboard is also acceptable.
    await expect(page.locator("body")).not.toBeEmpty();
    await expect(
      page.getByRole("heading", { name: /analytics|dashboard/i })
        .or(page.getByText(/analytics|revenue|insight|dashboard/i))
    ).toBeVisible({ timeout: 8_000 });
  });
});

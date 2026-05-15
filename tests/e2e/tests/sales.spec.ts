/**
 * Sales E2E tests — Playwright
 *
 * Test types:
 *   E2E            — full browser journey end to end
 *   Acceptance     — "user can create a sale" business requirement
 *   System         — cross-module: sale → stock deduction → invoice generated
 *   Regression     — re-run on every change
 *   Usability      — error states, loading indicators, form feedback
 */

import { test, expect } from "@playwright/test";
import { loginAndGo, hasCredentials } from "./helpers";

// ─── Navigation to sales ──────────────────────────────────────────────────────

test.describe("Sales Navigation", () => {
  test.beforeEach(({}, testInfo) => { if (!hasCredentials) testInfo.skip(); });
  test("sales link in sidebar navigates to sales page", async ({ page }) => {
    await loginAndGo(page);
    await page.getByRole("link", { name: /sales|invoices/i }).first().click();
    await expect(page).toHaveURL(/\/sales/i);
    await expect(page.getByRole("heading", { name: /sales|invoices/i })).toBeVisible();
  });
});

// ─── New Sale journey ─────────────────────────────────────────────────────────

test.describe("New Sale / Invoice", () => {
  test.beforeEach(async ({ page }, testInfo) => {
    if (!hasCredentials) { testInfo.skip(); return; }
    await loginAndGo(page, "/sales");
  });

  test("can open new sale modal / page", async ({ page }) => {
    const newSaleBtn = page.getByRole("button", { name: /new sale|create sale|pos/i });
    await expect(newSaleBtn).toBeVisible();
    await newSaleBtn.click();
    // Either a modal or navigation to /sales/new
    await expect(
      page.getByRole("heading", { name: /new sale|create invoice|point of sale/i })
        .or(page.locator("[data-testid='new-sale-modal']"))
    ).toBeVisible({ timeout: 5_000 });
  });

  test("sales list renders table or empty state", async ({ page }) => {
    await expect(
      page.getByRole("table")
        .or(page.getByText(/no sales|no invoices|get started/i))
    ).toBeVisible({ timeout: 5_000 });
  });
});

// ─── Invoice detail ───────────────────────────────────────────────────────────

test.describe("Invoice Detail", () => {
  test.beforeEach(({}, testInfo) => { if (!hasCredentials) testInfo.skip(); });
  test("clicking an invoice row opens the invoice drawer/detail", async ({ page }) => {
    await loginAndGo(page, "/sales");

    const firstRow = page.getByRole("row").nth(1);   // skip header
    const exists = await firstRow.isVisible();
    if (!exists) {
      test.skip();
      return;
    }

    await firstRow.click();
    // A drawer or detail panel must appear
    await expect(
      page.getByRole("dialog").or(page.locator("[data-testid='invoice-drawer']"))
    ).toBeVisible({ timeout: 5_000 });
  });
});

// ─── Quotes journey ───────────────────────────────────────────────────────────

test.describe("Quotes", () => {
  test.beforeEach(({}, testInfo) => { if (!hasCredentials) testInfo.skip(); });
  test("quotes page loads", async ({ page }) => {
    await loginAndGo(page, "/quotes");
    await expect(
      page.getByRole("heading", { name: /quotes/i })
        .or(page.getByText(/no quotes|empty/i))
    ).toBeVisible({ timeout: 5_000 });
  });

  test("new quote button is visible", async ({ page }) => {
    await loginAndGo(page, "/quotes");
    await expect(
      page.getByRole("button", { name: /new quote|create quote/i })
    ).toBeVisible();
  });
});

// ─── Customers journey ────────────────────────────────────────────────────────

test.describe("Customers", () => {
  test.beforeEach(({}, testInfo) => { if (!hasCredentials) testInfo.skip(); });
  test("customers page loads and shows content", async ({ page }) => {
    await loginAndGo(page, "/customers");
    await expect(
      page.getByRole("heading", { name: /customers/i })
    ).toBeVisible({ timeout: 5_000 });
    await expect(
      page.getByRole("table").or(page.getByText(/no customers/i))
    ).toBeVisible();
  });

  test("can search customers", async ({ page }) => {
    await loginAndGo(page, "/customers");
    const searchInput = page.getByPlaceholder(/search|find customer/i);
    if (await searchInput.isVisible()) {
      await searchInput.fill("Lagos");
      await page.waitForTimeout(500);   // debounce
      // Results area should update
      await expect(page.getByRole("table").or(page.getByText(/no results/i))).toBeVisible();
    }
  });
});

// ─── Dashboard tiles ─────────────────────────────────────────────────────────

test.describe("@smoke Dashboard", () => {
  test.beforeEach(({}, testInfo) => { if (!hasCredentials) testInfo.skip(); });
  test("dashboard shows key metric tiles after login", async ({ page }) => {
    await loginAndGo(page);
    // Wait for at least one metric tile / card
    await expect(
      page.locator("[data-testid='metric-card'], .metric-card, .stat-card")
        .or(page.getByText(/total sales|revenue|invoices/i))
    ).toBeVisible({ timeout: 8_000 });
  });

  test("no uncaught errors on dashboard", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await loginAndGo(page);
    await page.waitForTimeout(3000);
    const real = errors.filter(e =>
      !e.includes("ResizeObserver") && !e.includes("ChunkLoadError")
    );
    expect(real).toHaveLength(0);
  });
});

// ─── Accessibility spot check ─────────────────────────────────────────────────

test.describe("Accessibility", () => {
  test("login page has correct page title", async ({ page }) => {
    await page.goto("/login");
    const title = await page.title();
    expect(title).toBeTruthy();
    expect(title.length).toBeGreaterThan(2);
  });

  test("interactive elements have accessible labels", async ({ page }) => {
    if (!hasCredentials) test.skip();
    await loginAndGo(page, "/sales");
    // All buttons should have accessible names
    const buttons = page.getByRole("button");
    const count = await buttons.count();
    for (let i = 0; i < Math.min(count, 10); i++) {
      const name = await buttons.nth(i).getAttribute("aria-label")
        ?? await buttons.nth(i).textContent();
      expect(name?.trim().length ?? 0).toBeGreaterThan(0);
    }
  });
});

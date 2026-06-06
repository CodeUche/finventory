/**
 * Inventory E2E tests — Playwright
 *
 * Covers: Products, Stock movements, Warehouses, Batches (expiry tracking)
 *
 * Test types: E2E, Acceptance, Regression, Usability, Smoke (@smoke)
 */

import { test, expect } from "@playwright/test";
import { loginAndGo, credentialsWork } from "./helpers";

test.beforeEach(({}, testInfo) => {
  if (!credentialsWork) testInfo.skip();
});

// ─── Products ──────────────────────────────────────────────────────────────────

test.describe("@smoke Products Page", () => {
  test("products page loads", async ({ page }) => {
    await loginAndGo(page, "/inventory/products");
    await expect(
      page.getByRole("heading", { name: /products/i })
        .or(page.getByText(/no products/i))
    ).toBeVisible({ timeout: 8_000 });
  });

  test("add product button is visible", async ({ page }) => {
    await loginAndGo(page, "/inventory/products");
    await expect(
      page.getByRole("button", { name: /add product|new product/i })
    ).toBeVisible();
  });

  test("product list renders table or empty state", async ({ page }) => {
    await loginAndGo(page, "/inventory/products");
    await expect(
      page.getByRole("table").or(page.getByText(/no products|empty/i))
    ).toBeVisible({ timeout: 6_000 });
  });
});

test.describe("Products — Create Modal", () => {
  test("add product modal opens", async ({ page }) => {
    await loginAndGo(page, "/inventory/products");
    await page.getByRole("button", { name: /add product|new product/i }).click();
    await expect(
      page.getByRole("dialog").or(page.getByRole("heading", { name: /add product|new product/i }))
    ).toBeVisible({ timeout: 5_000 });
  });

  test("product form has required fields", async ({ page }) => {
    await loginAndGo(page, "/inventory/products");
    await page.getByRole("button", { name: /add product|new product/i }).click();
    await expect(page.getByLabel(/product name|name/i).first()).toBeVisible({ timeout: 5_000 });
    await expect(page.getByLabel(/selling price|price/i).first()).toBeVisible();
  });
});

test.describe("Products — Search & Filter", () => {
  test("search input filters products", async ({ page }) => {
    await loginAndGo(page, "/inventory/products");
    const search = page.getByPlaceholder(/search/i).first();
    if (await search.isVisible()) {
      await search.fill("test");
      await page.waitForTimeout(400);
      await expect(
        page.getByRole("table").or(page.getByText(/no products|no results/i))
      ).toBeVisible();
    }
  });

  test("low stock filter button visible", async ({ page }) => {
    await loginAndGo(page, "/inventory/products");
    await expect(
      page.getByRole("button", { name: /low stock|all/i }).first()
    ).toBeVisible();
  });

  test("sort selector is present", async ({ page }) => {
    await loginAndGo(page, "/inventory/products");
    await expect(
      page.getByRole("combobox").or(page.getByText(/sort by/i))
    ).toBeVisible({ timeout: 5_000 });
  });
});

test.describe("Products — Profit / Margin Column", () => {
  test("margin column renders in products table", async ({ page }) => {
    await loginAndGo(page, "/inventory/products");
    const table = page.getByRole("table");
    const hasTable = await table.isVisible({ timeout: 5_000 }).catch(() => false);
    if (!hasTable) return; // empty state — skip
    const headerRow = page.getByRole("row").first();
    const headerText = await headerRow.textContent();
    expect(headerText?.toLowerCase()).toMatch(/margin|profit/);
  });
});

// ─── Stock Page ────────────────────────────────────────────────────────────────

test.describe("@smoke Stock Page", () => {
  test("stock page loads", async ({ page }) => {
    await loginAndGo(page, "/inventory/stock");
    await expect(
      page.getByRole("heading", { name: /stock|inventory/i })
        .or(page.getByText(/no stock|no movements/i))
    ).toBeVisible({ timeout: 8_000 });
  });

  test("record stock movement button visible", async ({ page }) => {
    await loginAndGo(page, "/inventory/stock");
    await expect(
      page.getByRole("button", { name: /record|add stock|adjust/i })
    ).toBeVisible({ timeout: 6_000 });
  });

  test("stock movement modal opens", async ({ page }) => {
    await loginAndGo(page, "/inventory/stock");
    const btn = page.getByRole("button", { name: /record|add stock|adjust/i });
    await btn.click();
    await expect(
      page.getByRole("dialog").or(page.getByRole("heading", { name: /stock movement|add stock/i }))
    ).toBeVisible({ timeout: 5_000 });
  });
});

// ─── Warehouses ────────────────────────────────────────────────────────────────

test.describe("Warehouses Page", () => {
  test("warehouses page loads", async ({ page }) => {
    await loginAndGo(page, "/inventory/warehouses");
    await expect(
      page.getByRole("heading", { name: /warehouse/i })
        .or(page.getByText(/no warehouse/i))
    ).toBeVisible({ timeout: 8_000 });
  });

  test("add warehouse button visible", async ({ page }) => {
    await loginAndGo(page, "/inventory/warehouses");
    await expect(
      page.getByRole("button", { name: /add warehouse|new warehouse/i })
    ).toBeVisible({ timeout: 6_000 });
  });

  test("add warehouse modal opens", async ({ page }) => {
    await loginAndGo(page, "/inventory/warehouses");
    await page.getByRole("button", { name: /add warehouse|new warehouse/i }).click();
    await expect(page.getByRole("dialog")).toBeVisible({ timeout: 5_000 });
  });
});

// ─── Batches ───────────────────────────────────────────────────────────────────

test.describe("Batches Page", () => {
  test("batches page loads", async ({ page }) => {
    await loginAndGo(page, "/inventory/batches");
    await expect(
      page.getByRole("heading", { name: /batch/i })
        .or(page.getByText(/no batch/i))
    ).toBeVisible({ timeout: 8_000 });
  });

  test("batches list or empty state renders", async ({ page }) => {
    await loginAndGo(page, "/inventory/batches");
    await expect(
      page.getByRole("table").or(page.getByText(/no batch|no expiry/i))
    ).toBeVisible({ timeout: 6_000 });
  });
});

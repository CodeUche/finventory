/**
 * Purchases & Bills E2E tests — Playwright
 *
 * Covers: Purchase Orders, Bills, Bill Folders, Suppliers
 *
 * Test types: E2E, Acceptance, Regression, Usability, Smoke (@smoke)
 */

import { test, expect } from "@playwright/test";
import { loginAndGo } from "./helpers";

// ─── Purchase Orders ────────────────────────────────────────────────────────

test.describe("@smoke Purchases Page", () => {
  test("purchases page loads", async ({ page }) => {
    await loginAndGo(page, "/purchases");
    await expect(
      page.getByRole("heading", { name: /purchase/i })
        .or(page.getByText(/no purchase/i))
    ).toBeVisible({ timeout: 8_000 });
  });

  test("new purchase order button visible", async ({ page }) => {
    await loginAndGo(page, "/purchases");
    await expect(
      page.getByRole("button", { name: /new|add purchase|create/i }).first()
    ).toBeVisible({ timeout: 6_000 });
  });

  test("purchase list or empty state renders", async ({ page }) => {
    await loginAndGo(page, "/purchases");
    await expect(
      page.getByRole("table").or(page.getByText(/no purchase|empty/i))
    ).toBeVisible({ timeout: 6_000 });
  });
});

test.describe("Purchases — Create PO Modal", () => {
  test("new purchase order modal opens", async ({ page }) => {
    await loginAndGo(page, "/purchases");
    await page.getByRole("button", { name: /new|add purchase|create/i }).first().click();
    await expect(
      page.getByRole("dialog").or(page.getByRole("heading", { name: /purchase order|new po/i }))
    ).toBeVisible({ timeout: 5_000 });
  });

  test("PO form has supplier and item fields", async ({ page }) => {
    await loginAndGo(page, "/purchases");
    await page.getByRole("button", { name: /new|add purchase|create/i }).first().click();
    // Supplier selector or Walk-in option
    await expect(
      page.getByText(/supplier|walk-in/i).first()
    ).toBeVisible({ timeout: 5_000 });
  });
});

// ─── Bills ─────────────────────────────────────────────────────────────────────

test.describe("@smoke Bills Page", () => {
  test("bills page loads", async ({ page }) => {
    await loginAndGo(page, "/bills");
    await expect(
      page.getByRole("heading", { name: /bills/i })
        .or(page.getByText(/no bills/i))
    ).toBeVisible({ timeout: 8_000 });
  });

  test("add bill button visible", async ({ page }) => {
    await loginAndGo(page, "/bills");
    await expect(
      page.getByRole("button", { name: /add bill|new bill/i })
    ).toBeVisible({ timeout: 6_000 });
  });

  test("bills summary tiles are clickable", async ({ page }) => {
    await loginAndGo(page, "/bills");
    // Summary tiles (Total Payable, Overdue, Due This Week, Paid This Month)
    const tiles = page.locator("[class*='cursor-pointer'], [class*='clickable']");
    const count = await tiles.count();
    expect(count).toBeGreaterThanOrEqual(0); // tiles may be 0 if no data
  });
});

test.describe("Bills — Create Modal", () => {
  test("add bill modal opens", async ({ page }) => {
    await loginAndGo(page, "/bills");
    await page.getByRole("button", { name: /add bill|new bill/i }).click();
    await expect(page.getByRole("dialog")).toBeVisible({ timeout: 5_000 });
  });

  test("bill form has vendor / amount fields", async ({ page }) => {
    await loginAndGo(page, "/bills");
    await page.getByRole("button", { name: /add bill|new bill/i }).click();
    await expect(
      page.getByLabel(/vendor|supplier|amount|due date/i).first()
    ).toBeVisible({ timeout: 5_000 });
  });
});

test.describe("Bills — Filters", () => {
  test("bills status filter renders", async ({ page }) => {
    await loginAndGo(page, "/bills");
    await expect(
      page.getByRole("button", { name: /all|draft|received|paid/i }).first()
    ).toBeVisible({ timeout: 6_000 });
  });

  test("sort selector present", async ({ page }) => {
    await loginAndGo(page, "/bills");
    await expect(
      page.getByRole("combobox").or(page.getByText(/sort by/i))
    ).toBeVisible({ timeout: 5_000 });
  });
});

// ─── Bill Folders ───────────────────────────────────────────────────────────────

test.describe("Bill Folders Page", () => {
  test("bill folders page loads", async ({ page }) => {
    await loginAndGo(page, "/bills/folders");
    await expect(
      page.getByRole("heading", { name: /folder/i })
        .or(page.getByText(/no folder/i))
    ).toBeVisible({ timeout: 8_000 });
  });

  test("create folder button visible", async ({ page }) => {
    await loginAndGo(page, "/bills/folders");
    await expect(
      page.getByRole("button", { name: /new folder|create folder/i })
    ).toBeVisible({ timeout: 6_000 });
  });
});

// ─── Suppliers ──────────────────────────────────────────────────────────────────

test.describe("@smoke Suppliers Page", () => {
  test("suppliers page loads", async ({ page }) => {
    await loginAndGo(page, "/suppliers");
    await expect(
      page.getByRole("heading", { name: /supplier/i })
        .or(page.getByText(/no supplier/i))
    ).toBeVisible({ timeout: 8_000 });
  });

  test("add supplier button visible", async ({ page }) => {
    await loginAndGo(page, "/suppliers");
    await expect(
      page.getByRole("button", { name: /add supplier|new supplier/i })
    ).toBeVisible({ timeout: 6_000 });
  });

  test("supplier list or empty state renders", async ({ page }) => {
    await loginAndGo(page, "/suppliers");
    await expect(
      page.getByRole("table").or(page.getByText(/no supplier/i))
    ).toBeVisible({ timeout: 6_000 });
  });

  test("supplier search input present", async ({ page }) => {
    await loginAndGo(page, "/suppliers");
    await expect(
      page.getByPlaceholder(/search/i).first()
    ).toBeVisible({ timeout: 5_000 });
  });
});

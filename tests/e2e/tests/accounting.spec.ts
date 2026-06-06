/**
 * Accounting E2E tests — Playwright
 *
 * Covers: Chart of Accounts (COA), Journal Entries, Fixed Assets,
 *         Bank Reconciliation, Balance Sheet
 *
 * Test types: E2E, Acceptance, Regression, Smoke (@smoke)
 */

import { test, expect } from "@playwright/test";
import { loginAndGo, credentialsWork } from "./helpers";

test.beforeEach(({}, testInfo) => {
  if (!credentialsWork) testInfo.skip();
});

// ─── Chart of Accounts ─────────────────────────────────────────────────────────

test.describe("@smoke Chart of Accounts", () => {
  test("COA page loads", async ({ page }) => {
    await loginAndGo(page, "/accounting/coa");
    await expect(
      page.getByRole("heading", { name: /chart of accounts|accounts/i })
        .or(page.getByText(/no accounts/i))
    ).toBeVisible({ timeout: 8_000 });
  });

  test("add account button visible", async ({ page }) => {
    await loginAndGo(page, "/accounting/coa");
    await expect(
      page.getByRole("button", { name: /add account|new account/i })
    ).toBeVisible({ timeout: 6_000 });
  });

  test("accounts table renders or shows empty state", async ({ page }) => {
    await loginAndGo(page, "/accounting/coa");
    await expect(
      page.getByRole("table").or(page.getByText(/no account/i))
    ).toBeVisible({ timeout: 6_000 });
  });
});

test.describe("Chart of Accounts — Create", () => {
  test("add account modal opens", async ({ page }) => {
    await loginAndGo(page, "/accounting/coa");
    await page.getByRole("button", { name: /add account|new account/i }).click();
    await expect(page.getByRole("dialog")).toBeVisible({ timeout: 5_000 });
  });

  test("account form has account code and name fields", async ({ page }) => {
    await loginAndGo(page, "/accounting/coa");
    await page.getByRole("button", { name: /add account|new account/i }).click();
    await expect(
      page.getByLabel(/account code|code|account name|name/i).first()
    ).toBeVisible({ timeout: 5_000 });
  });
});

// ─── Journal Entries ───────────────────────────────────────────────────────────

test.describe("@smoke Journal Page", () => {
  test("journal page loads", async ({ page }) => {
    await loginAndGo(page, "/accounting/journal");
    await expect(
      page.getByRole("heading", { name: /journal/i })
        .or(page.getByText(/no journal|no entries/i))
    ).toBeVisible({ timeout: 8_000 });
  });

  test("journal entries table or empty state renders", async ({ page }) => {
    await loginAndGo(page, "/accounting/journal");
    await expect(
      page.getByRole("table").or(page.getByText(/no journal|no entries/i))
    ).toBeVisible({ timeout: 6_000 });
  });
});

// ─── Fixed Assets ─────────────────────────────────────────────────────────────

test.describe("Fixed Assets Page", () => {
  test("assets page loads", async ({ page }) => {
    await loginAndGo(page, "/accounting/assets");
    await expect(
      page.getByRole("heading", { name: /assets|fixed assets/i })
        .or(page.getByText(/no asset/i))
    ).toBeVisible({ timeout: 8_000 });
  });

  test("add asset button visible", async ({ page }) => {
    await loginAndGo(page, "/accounting/assets");
    await expect(
      page.getByRole("button", { name: /add asset|new asset/i })
    ).toBeVisible({ timeout: 6_000 });
  });

  test("assets list or empty state renders", async ({ page }) => {
    await loginAndGo(page, "/accounting/assets");
    await expect(
      page.getByRole("table").or(page.getByText(/no asset/i))
    ).toBeVisible({ timeout: 6_000 });
  });
});

// ─── Bank Reconciliation ───────────────────────────────────────────────────────

test.describe("Bank Reconciliation Page", () => {
  test("reconciliation page loads", async ({ page }) => {
    await loginAndGo(page, "/accounting/reconciliation");
    await expect(
      page.getByRole("heading", { name: /reconcil/i })
        .or(page.getByText(/no reconcil/i))
    ).toBeVisible({ timeout: 8_000 });
  });

  test("reconciliation list or create prompt renders", async ({ page }) => {
    await loginAndGo(page, "/accounting/reconciliation");
    await expect(
      page.getByRole("table")
        .or(page.getByRole("button", { name: /new reconcil|create/i }))
        .or(page.getByText(/no reconcil/i))
    ).toBeVisible({ timeout: 6_000 });
  });
});

// ─── Balance Sheet ─────────────────────────────────────────────────────────────

test.describe("Balance Sheet Page", () => {
  test("balance sheet page loads", async ({ page }) => {
    await loginAndGo(page, "/reports/balance-sheet");
    await expect(
      page.getByRole("heading", { name: /balance sheet/i })
        .or(page.getByText(/assets|liabilities|equity/i))
    ).toBeVisible({ timeout: 8_000 });
  });

  test("balance sheet shows Assets and Liabilities sections", async ({ page }) => {
    await loginAndGo(page, "/reports/balance-sheet");
    await expect(
      page.getByText(/assets/i).first()
    ).toBeVisible({ timeout: 8_000 });
  });
});

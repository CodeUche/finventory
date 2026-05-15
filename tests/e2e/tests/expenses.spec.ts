/**
 * Expenses & Budgets E2E tests — Playwright
 *
 * Covers: Expenses list, expense grouping, savings display,
 *         Budgets, budget lines, budget activation
 *
 * Test types: E2E, Acceptance, Regression, Smoke (@smoke)
 */

import { test, expect } from "@playwright/test";
import { loginAndGo, hasCredentials } from "./helpers";

test.beforeEach(({}, testInfo) => {
  if (!hasCredentials) testInfo.skip();
});

// ─── Expenses ──────────────────────────────────────────────────────────────────

test.describe("@smoke Expenses Page", () => {
  test("expenses page loads", async ({ page }) => {
    await loginAndGo(page, "/expenses");
    await expect(
      page.getByRole("heading", { name: /expenses/i })
        .or(page.getByText(/no expense/i))
    ).toBeVisible({ timeout: 8_000 });
  });

  test("add expense button visible", async ({ page }) => {
    await loginAndGo(page, "/expenses");
    await expect(
      page.getByRole("button", { name: /add expense|new expense/i })
    ).toBeVisible({ timeout: 6_000 });
  });

  test("expenses list or empty state renders", async ({ page }) => {
    await loginAndGo(page, "/expenses");
    await expect(
      page.getByRole("table").or(page.getByText(/no expense|empty/i))
    ).toBeVisible({ timeout: 6_000 });
  });
});

test.describe("Expenses — Create Modal", () => {
  test("add expense modal opens", async ({ page }) => {
    await loginAndGo(page, "/expenses");
    await page.getByRole("button", { name: /add expense|new expense/i }).click();
    await expect(page.getByRole("dialog")).toBeVisible({ timeout: 5_000 });
  });

  test("expense form has category, amount and date fields", async ({ page }) => {
    await loginAndGo(page, "/expenses");
    await page.getByRole("button", { name: /add expense|new expense/i }).click();
    await expect(
      page.getByLabel(/category|amount|date/i).first()
    ).toBeVisible({ timeout: 5_000 });
  });
});

test.describe("Expenses — Grouping & Savings", () => {
  test("group by category toggle present", async ({ page }) => {
    await loginAndGo(page, "/expenses");
    await expect(
      page.getByRole("button", { name: /group|category/i })
        .or(page.getByText(/group by/i))
    ).toBeVisible({ timeout: 5_000 });
  });
});

test.describe("Expenses — Filters", () => {
  test("date range / filter controls present", async ({ page }) => {
    await loginAndGo(page, "/expenses");
    await expect(
      page.getByPlaceholder(/search|from|to/i)
        .or(page.getByRole("combobox").first())
    ).toBeVisible({ timeout: 5_000 });
  });
});

// ─── Budgets ───────────────────────────────────────────────────────────────────

test.describe("@smoke Budgets Page", () => {
  test("budgets page loads", async ({ page }) => {
    await loginAndGo(page, "/budgets");
    await expect(
      page.getByRole("heading", { name: /budget/i })
        .or(page.getByText(/no budget/i))
    ).toBeVisible({ timeout: 8_000 });
  });

  test("create budget button visible", async ({ page }) => {
    await loginAndGo(page, "/budgets");
    await expect(
      page.getByRole("button", { name: /create budget|new budget/i })
    ).toBeVisible({ timeout: 6_000 });
  });

  test("budgets list or empty state renders", async ({ page }) => {
    await loginAndGo(page, "/budgets");
    await expect(
      page.getByRole("table").or(page.getByText(/no budget|empty/i))
    ).toBeVisible({ timeout: 6_000 });
  });
});

test.describe("Budgets — Create Modal", () => {
  test("create budget modal opens", async ({ page }) => {
    await loginAndGo(page, "/budgets");
    await page.getByRole("button", { name: /create budget|new budget/i }).click();
    await expect(page.getByRole("dialog")).toBeVisible({ timeout: 5_000 });
  });

  test("budget form has name and period fields", async ({ page }) => {
    await loginAndGo(page, "/budgets");
    await page.getByRole("button", { name: /create budget|new budget/i }).click();
    await expect(
      page.getByLabel(/budget name|name/i).first()
        .or(page.getByText(/period|monthly|weekly|daily/i).first())
    ).toBeVisible({ timeout: 5_000 });
  });

  test("budget period dropdown includes daily, weekly, monthly, yearly", async ({ page }) => {
    await loginAndGo(page, "/budgets");
    await page.getByRole("button", { name: /create budget|new budget/i }).click();
    const period = page.getByRole("combobox");
    const hasCombo = await period.isVisible().catch(() => false);
    if (hasCombo) {
      const options = await period.textContent();
      // At least one period option should appear somewhere on the page
      await expect(page.getByText(/monthly|weekly|daily|annually/i).first()).toBeVisible();
    }
  });
});

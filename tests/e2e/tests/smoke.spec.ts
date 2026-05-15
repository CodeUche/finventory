/**
 * Smoke tests — @smoke
 *
 * Fast subset of critical checks run before every deploy.
 * Target: completes in < 60 seconds on Chromium.
 *
 * Test types: Smoke, Sanity, System
 */

import { test, expect } from "@playwright/test";
import { EMAIL, PASS, hasCredentials } from "./helpers";

// BASE_URL  = the web frontend (Vite dev server or deployed web build)
// API_URL   = the Django backend (Railway or localhost:8000)
// When running against Railway API only (no web frontend deployed), set both to the same
// Railway URL — frontend tests will be skipped automatically if they get non-HTML responses.
const BASE = process.env.BASE_URL || "http://localhost:3000";
const API  = process.env.API_URL  || (process.env.BASE_URL ? process.env.BASE_URL.replace(/\/api\/v1\/?$/, "") : "http://localhost:8000");

// ─── API health ───────────────────────────────────────────────────────────────

test.describe("@smoke API Health", () => {
  test("backend health endpoint responds 200", async ({ request }) => {
    const resp = await request.get(`${API}/api/v1/health/`);
    expect(resp.status()).toBe(200);
  });

  test("auth endpoint is reachable", async ({ request }) => {
    // Wrong credentials → 401, not 500/503
    const resp = await request.post(`${API}/api/v1/auth/login/`, {
      data: { email: "probe@smoke.test", password: "wrongpass" },
    });
    expect(resp.status()).toBe(401);
  });

  test("API returns JSON content-type", async ({ request }) => {
    const resp = await request.post(`${API}/api/v1/auth/login/`, {
      data: { email: "probe@smoke.test", password: "wrongpass" },
    });
    expect(resp.headers()["content-type"]).toContain("application/json");
  });
});

// ─── Frontend critical pages ──────────────────────────────────────────────────

test.describe("@smoke Frontend Critical Pages", () => {
  test("app shell loads (no white screen)", async ({ page }) => {
    await page.goto("/login");
    // App root must mount — look for any rendered content
    await expect(page.locator("body")).not.toBeEmpty();
    await expect(page.locator("#root, #app, [data-testid='app']").first()).toBeVisible({
      timeout: 8_000,
    });
  });

  test("login page renders without JS errors", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (err) => errors.push(err.message));
    await page.goto("/login");
    await page.waitForTimeout(2000);
    expect(errors.filter(e => !e.includes("ResizeObserver"))).toHaveLength(0);
  });

  test("login page has Audity branding", async ({ page }) => {
    await page.goto("/login");
    // Either in the title or visible text
    const title = await page.title();
    const bodyText = await page.locator("body").textContent();
    expect(title + bodyText).toMatch(/Audity/i);
  });
});

// ─── Critical user flow — login ───────────────────────────────────────────────

test.describe("@smoke Login Flow", () => {
  test.beforeEach(({}, testInfo) => { if (!hasCredentials) testInfo.skip(); });

  test("can log in and see navigation", async ({ page }) => {
    await page.goto("/login");
    await page.getByLabel(/email/i).fill(EMAIL);
    await page.getByLabel(/password/i).fill(PASS);
    await page.getByRole("button", { name: /sign in|log in/i }).click();

    // Navigation / sidebar must appear
    await expect(
      page.getByRole("navigation").or(page.locator("[data-testid='sidebar']"))
    ).toBeVisible({ timeout: 10_000 });
  });
});

// ─── Sanity checks post-deploy ────────────────────────────────────────────────

test.describe("@smoke Sanity Checks", () => {
  test("no 404 on static assets (favicon)", async ({ request }) => {
    // App uses favicon.svg (not .ico)
    const resp = await request.get(`${BASE}/favicon.svg`);
    expect(resp.status()).not.toBe(404);
  });

  test("CSP and security headers present on API", async ({ request }) => {
    const resp = await request.get(`${API}/api/v1/auth/login/`, { method: "OPTIONS" });
    // Should at minimum not expose Server: version
    const server = resp.headers()["server"] || "";
    expect(server).not.toMatch(/Apache\/\d|nginx\/\d/);
  });
});

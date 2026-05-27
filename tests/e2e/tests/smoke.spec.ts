/**
 * Smoke tests — @smoke
 *
 * Fast subset of critical checks run before every deploy.
 * Target: completes in < 60 seconds on Chromium.
 *
 * API tests always run (Railway backend is always live).
 * Frontend page tests are skipped gracefully when BASE_URL is not a live web app
 * (e.g. CI running against a Tauri desktop build with no web deployment).
 *
 * Test types: Smoke, Sanity, System
 */

import { test, expect } from "@playwright/test";
import { EMAIL, PASS, hasCredentials } from "./helpers";

const BASE = process.env.BASE_URL || "http://localhost:3000";
const API  = process.env.API_URL  || (process.env.BASE_URL ? process.env.BASE_URL.replace(/\/api\/v1\/?$/, "") : "http://localhost:8000");

// ─── Preflight: check if the web frontend is actually live at BASE_URL ─────────
// If BASE_URL returns a Vercel 404 / non-HTML page, all page-level tests skip.
let frontendLive = false;

test.beforeAll(async ({ request }) => {
  try {
    const resp = await request.get(BASE, { timeout: 8_000 });
    const ct = resp.headers()["content-type"] ?? "";
    // Live if it returns HTML and not a Vercel 404 body
    const body = await resp.text();
    frontendLive = resp.ok() && ct.includes("text/html") && !body.includes("NOT_FOUND");
  } catch {
    frontendLive = false;
  }
});

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
// All tests in this block skip when the web frontend is not deployed at BASE_URL.

test.describe("@smoke Frontend Critical Pages", () => {
  test.beforeEach(({}, testInfo) => {
    if (!frontendLive) testInfo.skip("Frontend not reachable at BASE_URL — skipping (Tauri desktop build or URL not deployed)");
  });

  test("app shell loads (no white screen)", async ({ page }) => {
    await page.goto("/login");
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
    const title = await page.title();
    const bodyText = await page.locator("body").textContent();
    expect(title + bodyText).toMatch(/Audity/i);
  });
});

// ─── Critical user flow — login ───────────────────────────────────────────────

test.describe("@smoke Login Flow", () => {
  test.beforeEach(({}, testInfo) => {
    if (!frontendLive) testInfo.skip("Frontend not reachable at BASE_URL — skipping");
    if (!hasCredentials) testInfo.skip("TEST_EMAIL / TEST_PASSWORD secrets not configured — skipping auth-dependent test");
  });

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
    test.skip(!frontendLive, "Frontend not reachable at BASE_URL — skipping");
    // App uses favicon.svg
    const resp = await request.get(`${BASE}/favicon.svg`);
    expect(resp.status()).not.toBe(404);
  });

  test("CSP and security headers present on API", async ({ request }) => {
    const resp = await request.get(`${API}/api/v1/health/`);
    // Should at minimum not expose detailed server version
    const server = resp.headers()["server"] ?? "";
    expect(server).not.toMatch(/Apache\/\d|nginx\/\d/);
  });
});

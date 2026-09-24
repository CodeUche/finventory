import { defineConfig, devices } from "@playwright/test";
import * as path from "path";

const BASE_URL = process.env.BASE_URL || "http://localhost:3000";

export default defineConfig({
  testDir: "./tests",
  globalSetup: "./global-setup",
  fullyParallel: true,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 2 : undefined,
  reporter: [
    ["list"],
    ["html", { outputFolder: "playwright-report", open: "never" }],
  ],
  timeout: 60_000,       // 60 s — covers Railway cold-start (~20 s) + auth + page load
  expect: { timeout: 10_000 },

  use: {
    baseURL: BASE_URL,
    // The WAF on the ALB rejects requests with no User-Agent (the AWS managed
    // NoUserAgent rule) with a 403 that never reaches Django — so Playwright's
    // API client, which sends none, had its request.get() calls blocked while
    // the identical curl succeeded. That is why the "backend health endpoint
    // responds 200" test saw a 403 against an endpoint that is demonstrably up.
    extraHTTPHeaders: { "User-Agent": "audity-e2e-smoke (Playwright)" },

    // Start every test from the session global-setup signed in with, instead of
    // logging in per test. The API throttles login at 20/minute per IP, and a
    // full suite of per-test logins produced 91 HTTP 429s in one run. Tests
    // that exercise the login screen itself opt out with
    // test.use({ storageState: { cookies: [], origins: [] } }).
    storageState: path.join(__dirname, ".auth", "state.json"),
    trace: "on-first-retry",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
    // Ignore HTTPS errors when testing against local or Railway staging
    ignoreHTTPSErrors: true,
  },

  projects: [
    // ── What CI runs on every push ───────────────────────────────────────────
    // A deliberately small slice of @smoke: sign-in, navigation, the sales
    // path, customers, and the API-level checks.
    //
    // The full smoke project below is too expensive to run against production.
    // It loads 68 pages that fire 30-40 API calls each — 2,594 requests in 8
    // minutes, measured 2026-09-24 — which trips the WAF's own RateLimitPerIP
    // rule (2000 requests per IP per 5 minutes) partway through. The suite then
    // fails on 403s the WAF produced, i.e. CI gets blocked as an attacker by
    // the very system it is testing, and the failures look like broken pages.
    //
    // Cutting the page count is the fix, rather than widening a DDoS rule for
    // the convenience of a test run. Keep this list short on purpose: if you
    // add files here, re-measure the request volume before merging.
    {
      name: "core",
      grep: /@smoke/,
      testMatch: [
        "**/smoke.spec.ts",
        "**/auth.spec.ts",
        "**/navigation.spec.ts",
        "**/sales.spec.ts",
        "**/customers.spec.ts",
      ],
      use: { ...devices["Desktop Chrome"] },
    },

    // ── Full smoke suite — run by hand, or against a non-production stack ────
    // Exceeds the production WAF's per-IP rate limit in a single run; see the
    // note on the core project above before pointing this at production.
    {
      name: "smoke",
      grep: /@smoke/,
      use: { ...devices["Desktop Chrome"] },
    },

    // ── Full compatibility matrix ────────────────────────────────────────────
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
    {
      name: "firefox",
      use: { ...devices["Desktop Firefox"] },
    },
    {
      name: "webkit",
      use: { ...devices["Desktop Safari"] },
    },

    // ── Mobile compatibility ──────────────────────────────────────────────────
    {
      name: "mobile-chrome",
      use: { ...devices["Pixel 5"] },
    },
    {
      name: "mobile-safari",
      use: { ...devices["iPhone 13"] },
    },
  ],
});

/**
 * Playwright global setup — runs once before any worker starts.
 *
 * Checks whether the TEST_EMAIL / TEST_PASSWORD credentials can actually
 * authenticate against the live backend.  If they can't, writes a sentinel
 * file that helpers.ts reads in each worker: every credential-dependent test
 * then skips with a clear message instead of timing out 25 s × 3 retries.
 *
 * The sentinel file is removed at the start of each run so a previously
 * failing run doesn't permanently disable tests.
 */

import { FullConfig, chromium } from "@playwright/test";
import * as fs from "fs";
import * as path from "path";

const SENTINEL = path.join(__dirname, ".login-failed");
// One signed-in session, reused by every test — see saveSignedInState below.
const AUTH_STATE = path.join(__dirname, ".auth", "state.json");

export default async function globalSetup(config: FullConfig) {
  // Always clean up the sentinel from a previous run first.
  try { fs.unlinkSync(SENTINEL); } catch { /* didn't exist */ }
  // playwright.config.ts points every context at AUTH_STATE, and a context
  // fails to create if the file is missing — so write an empty one up front
  // and overwrite it below when we actually sign in.
  writeEmptyState();

  const EMAIL = process.env.TEST_EMAIL    || "";
  const PASS  = process.env.TEST_PASSWORD || "";
  const API   = process.env.API_URL || "http://localhost:8000";

  // No credentials configured — nothing to pre-check.
  if (!EMAIL || !PASS) return;

  // ── Fast HTTP-level credential check ──────────────────────────────────────
  // We POST directly to the auth endpoint; no browser needed.
  // If the backend rejects the credentials (non-200) we write the sentinel.
  try {
    const resp = await fetch(`${API}/api/v1/auth/login/`, {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify({ email: EMAIL, password: PASS }),
      signal:  AbortSignal.timeout(15_000),
    });

    if (resp.ok) {
      console.log("  ✓ test credentials validated against production API");
      await saveSignedInState(EMAIL, PASS);
      return;
    }

    // Credentials are CONFIGURED but REJECTED. This used to write the sentinel
    // and skip every login-dependent test, which is how the suite spent weeks
    // guarding nothing: the secrets stopped matching a real account (most
    // likely at the 2026-09-06 AWS cutover, which re-keyed every JWT and signed
    // everyone out), every meaningful test quietly skipped, and the only red in
    // the run came from the partner specs timing out at a login form for the
    // same reason — so the failure never pointed at its own cause.
    //
    // Configured-but-wrong is a broken pipeline, not an absent one. Fail here,
    // immediately and legibly, instead of running a suite that cannot test
    // anything. Missing credentials still skip (above): that is a fork or a
    // local checkout, not rot.
    const body = await resp.text().catch(() => "");
    throw new Error(
      `Test credentials were rejected by ${API} (HTTP ${resp.status}).\n` +
      `  Response: ${body.slice(0, 200)}\n` +
      `  TEST_EMAIL is currently: ${EMAIL || "(empty)"}\n\n` +
      `  Every login-dependent smoke test would otherwise skip and this run\n` +
      `  would look healthy. Point TEST_EMAIL / TEST_PASSWORD at a real account\n` +
      `  on the AWS production database (Aurora) and re-run.`
    );

  } catch (err) {
    // A rejection we raised ourselves must not be swallowed by this catch,
    // which exists only for network-level failures.
    if (err instanceof Error && err.message.startsWith("Test credentials were rejected")) throw err;

    // Backend genuinely unreachable — a transient outage, not rot. Skip the
    // login-dependent tests rather than failing the build for it.
    console.warn(`  ⚠ Credential pre-check: backend unreachable (${err}) — login-dependent tests will be SKIPPED`);
    fs.writeFileSync(SENTINEL, new Date().toISOString());
    return;
  }
}

/** An anonymous storage state, so contexts can always be created. */
function writeEmptyState() {
  fs.mkdirSync(path.dirname(AUTH_STATE), { recursive: true });
  fs.writeFileSync(AUTH_STATE, JSON.stringify({ cookies: [], origins: [] }));
}

/**
 * Sign in ONCE and save the session for every test to reuse.
 *
 * Each test used to sign in for itself. The API throttles login at 20/minute
 * per IP, so a 68-test suite generated 91 HTTP 429s in a single run
 * (measured 2026-09-24) and the throttled tests failed as "page didn't load"
 * — reading like a broken app rather than a rate limit. One login for the
 * whole suite removes the cause instead of raising the limit.
 *
 * This also catches something the HTTP pre-check above cannot: the API
 * accepting credentials over curl while the BROWSER cannot sign in, which is
 * what a missing CORS origin looks like. That exact gap hid here for weeks.
 */
async function saveSignedInState(email: string, password: string) {
  const BASE = process.env.BASE_URL || "http://localhost:3000";
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage({ ignoreHTTPSErrors: true });
    await page.goto(`${BASE}/login`, { waitUntil: "domcontentloaded" });
    await page.locator('input[type="email"]').first().fill(email);
    await page.locator('input[type="password"]').first().fill(password);
    await page.locator('button[type="submit"]').first().click();
    await page.waitForURL((u) => !u.pathname.includes("/login"), { timeout: 30_000 });
    await page.context().storageState({ path: AUTH_STATE });
    console.log("  ✓ signed in once at " + BASE + " — session shared by all tests");
  } catch (err) {
    throw new Error(
      [
        `The API accepted these credentials but the browser could not sign in at ${BASE}.`,
        `  ${err}`,
        ``,
        `  The usual cause is CORS: that origin is not in CORS_ALLOWED_ORIGINS, so the`,
        `  browser blocks the login request while curl succeeds. Check`,
        `  additional_cors_origins in infra/terraform/variables.tf.`,
      ].join("\n")
    );
  } finally {
    await browser.close();
  }
}

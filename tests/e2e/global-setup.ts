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

import { FullConfig } from "@playwright/test";
import * as fs from "fs";
import * as path from "path";

const SENTINEL = path.join(__dirname, ".login-failed");

export default async function globalSetup(config: FullConfig) {
  // Always clean up the sentinel from a previous run first.
  try { fs.unlinkSync(SENTINEL); } catch { /* didn't exist */ }

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
      // Credentials are valid — no sentinel, tests run normally.
      console.log("  ✓ test credentials validated against production API");
      return;
    }

    const body = await resp.text().catch(() => "");
    console.warn(
      `  ⚠ Credential pre-check failed (HTTP ${resp.status}): ${body.slice(0, 200)}`
    );
    console.warn(
      "  ⚠ All login-dependent smoke tests will be SKIPPED."
    );
    console.warn(
      "  ⚠ Fix: ensure TEST_EMAIL / TEST_PASSWORD GitHub secrets match a real user"
    );
    console.warn(
      "  ⚠ on the Railway production database, then re-run the CI pipeline."
    );

  } catch (err) {
    // Backend unreachable — could be Railway sleeping.  Don't write sentinel:
    // let the apiLive pre-flight in smoke.spec.ts handle it.
    console.warn(`  ⚠ Credential pre-check: backend unreachable (${err}) — skipping credential validation`);
    return;
  }

  // Write sentinel so all workers know to skip login-dependent tests.
  fs.writeFileSync(SENTINEL, new Date().toISOString());
}

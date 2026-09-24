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

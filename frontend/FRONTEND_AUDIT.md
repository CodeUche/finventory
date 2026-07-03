# Audity Finventory — Frontend Audit
**Scope:** `finventory/frontend` — React 18 + TypeScript + Vite, Tauri (desktop) / Capacitor (Android) / web (cloud). 110 source files, ~47,500 lines.
**Date:** 2026-07-03 · **Method:** full read of core infra (`api.ts`, `authStore.ts`, `main.tsx`, sync/cache libs), targeted review of pages, `tsc` + `eslint` + `npm audit` runs.

**Baseline:** `tsc --noEmit` passes clean. ESLint: 2 trivial errors. The offline/sync architecture is unusually well-engineered and well-commented for a codebase this young. The findings below are mostly design-level, not sloppiness.

---

## P1 — Security & data integrity

### 1. `xlsx` 0.18.5 — HIGH severity, no fix on npm
`npm audit`: Prototype Pollution (GHSA-4r6h-8v6p-xvw6) and ReDoS (GHSA-5pgg-2g8v-p4x9). The npm package is abandoned; the app parses **user-supplied spreadsheet files** (ImportPage), which is exactly the attack surface these CVEs target.
**Fix:** Migrate to the maintained SheetJS CDN distribution (`https://cdn.sheetjs.com/xlsx-latest/xlsx-latest.tgz` in package.json) or switch to `exceljs`.

### 2. `react-router-dom` 7.1.5 — 4 high CVEs, fix available
XSS via `javascript:` redirect targets, stored XSS via Location header, DoS, CSRF (GHSA-8646…, GHSA-f22v…, GHSA-8x6r…, GHSA-rxv8…). Some apply mainly to framework/SSR mode, but the fix is a version bump.
**Fix:** `npm audit fix` → verify routes still work. Low-risk upgrade within v7.

### 3. Cross-user media cache leak (`authStore.ts` lines 9–24, 113–123)
`audity-media` (logo/stamp/avatar data URLs) deliberately survives `logout()` and is **not scoped to user or org**. On a shared machine, User B logging in inherits User A's organisation logo, stamp, and avatar into their session state — and the stamp presumably lands on generated PDFs until overwritten.
**Fix:** Key the media cache by `org.id` (`audity-media:<orgId>`) and read it only when the logged-in org matches.

### 4. Axios `timeout: 10000` is dead config — requests can hang forever
The custom Tauri adapter (`buildTauriAdapter`) never implements timeout: no `AbortController`, no `signal` passed to `tauriHttpFetch` or the native `fetch` fallback (verified — zero matches in `api.ts`). Axios timeouts are enforced *by adapters*; replacing the adapter silently discarded it. On a stalled connection (common on Nigerian mobile networks) a request neither fails nor completes — the offline machinery never triggers because no error is thrown.
**Fix:** `const ctrl = new AbortController(); setTimeout(() => ctrl.abort(), config.timeout ?? 10000)` and pass `signal: ctrl.signal` to both fetch paths.

### 5. Offline pagination `count` corruption
`_mergeLocalStore` and `_patchCacheList` (api.ts ~277, ~374) set `count: mergedResults.length` — the length of **one page**, overwriting the server's total-across-pages count. Any pagination UI that trusts `count` after an offline merge or cache patch will show wrong totals / drop pages.
**Fix:** Preserve the original `count`, adjusting only by the delta of added/removed optimistic records.

---

## P2 — Broken or misleading features

### 6. "Remember me on this device" does nothing
Verified end-to-end: the checkbox sets `REMEMBER_FLAG_KEY`, **nothing anywhere reads it** (grep: zero consumers outside authStore), `main.tsx` calls `logout()` on every launch which deletes the flag, tokens are never persisted, and the saved-credentials key is purged as legacy at module load (authStore line 7). The comment in main.tsx line 65 ("Saved credentials are kept for auto-fill") describes code that no longer exists.
**Fix:** Either remove the checkbox (honest) or implement it properly — on desktop, store the refresh token in the OS keychain via a Tauri secure-storage plugin, not localStorage.

### 7. Offline-first dies on app restart
`main.tsx` calls `logout()` on every launch → `offlineCache.clearAll()` wipes the response cache; login itself is (correctly) never handled offline. Net effect: a user who loses connectivity and restarts the app **cannot get in at all**, and even the localStore entity fallback is unreachable behind the login wall. All of api.ts's offline engineering only works mid-session. For a market where connectivity drops are routine, this is an architectural gap, not an edge case.
**Fix:** This requires a deliberate decision — offline re-auth (verify last-known credentials against a locally stored hash, short-lived offline grace session) is the standard pattern for desktop accounting software. Not a small change; flagging it as the biggest product-level risk in this audit.

---

## P3 — Performance

### 8. Zero code splitting — 4.9 MB main bundle (~0.9 MB gzipped)
`React.lazy` count in App.tsx: 0. All ~35 pages, recharts, jspdf, html2canvas ship in one `index-*.js`. Irrelevant for Tauri (local disk), but the **cloud build serves this on every cold load** — ~0.9 MB gzip + full parse/compile of 4.9 MB JS on low-end Android/laptops is multi-second startup.
**Fix:** `React.lazy` per route + manual chunks for recharts/jspdf/xlsx in `vite.config.ts` (`build.rollupOptions.output.manualChunks`). The xlsx chunk (848 KB) is already split — extend the pattern.

### 9. Monster components
`SettingsPage.tsx` 4,007 lines, `TaxPage.tsx` 2,635, `ReportsPage.tsx` 1,896, `SalesPage.tsx` 1,663. Beyond maintainability: any state change re-renders the whole page tree, and code review of tax logic buried at line 2,000 is where compliance bugs hide.
**Fix:** Extract tab panels/modals into child components incrementally — start with SettingsPage tabs.

---

## P4 — Code health (systemic, not urgent)

10. **296 silent `catch {}` blocks.** The pattern is deliberate ("non-fatal") and often right for cache ops, but it also swallows real failures — e.g. `offlineCache.set` failures mean a user believes data is available offline when it isn't. Recommend a `debugLog()` in every silent catch, surfaced in a diagnostics screen (you already have PostHog — send counts there).
11. **149 `: any` annotations**, concentrated in API response handling (`const all: any[] = ...` repeated per page). One typed `unwrapList<T>()` helper would eliminate most and catch response-shape drift at compile time.
12. **ESLint errors (2):** `ProductsPage.tsx` 581, 588 — ternaries used as statements; convert to if/else and lint gate stays green (`--max-warnings 0` is already configured — good).
13. **Accessibility is thin:** 8 `aria-label`s across the app, 2 `<img>` without `alt`, no focus management audit done in modals. Acceptable for beta; schedule before any enterprise/government customer with procurement requirements.
14. **Org ID as `?org=` query param** (Tauri header-drop workaround): UUIDs end up in server access logs and any URL-based tooling. Documented, backend-supported, defensible — just ensure logs are treated as sensitive.

---

## What's notably good
Atomic login commit to avoid redirect races; token rotation handled correctly (rotated refresh saved); refresh-mutex with queued retries; dedupe-map cleanup on HTTP errors (the classic hang bug — already handled); auth endpoints excluded from offline optimism; tokens kept memory-only; legacy plaintext-credential purge; DOMPurify on the single `dangerouslySetInnerHTML`; conflict states + retry/dismiss in syncEngine; committed `.env` files contain no secrets (verified — only `.env.example` and a public PostHog key in git).

## Fix order
1 · 2 (dependency CVEs — an afternoon) → 4 (hanging requests) → 3 · 5 (data integrity) → 6 (remove or rebuild) → 8 (before cloud marketing push) → 7 (schedule as a product decision, not a patch).

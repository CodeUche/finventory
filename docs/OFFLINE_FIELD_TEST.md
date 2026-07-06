# Offline Field Test — Manual E2E Script

**Product requirement under test** (verbatim):

> "A lot of our users are local traders selling inside the local markets and
> internet in these places are highly unstable. Login should require internet
> access but using the app should have offline access and all should sync up
> with the cloud when internet access is restored. They should have CRUD
> access offline and should sync with the cloud when internet is restored."

This script covers what the automated suite cannot: real connectivity
toggles, a real Tauri process restart, and the offline unlock UI. The
automated halves live in `frontend/src/test/offlineSync.test.ts` (queue
persistence, exactly-once flush, temp-ID rewrite, conflict lifecycle, org
scoping) and `frontend/src/test/cacheWarm.test.ts` (warm priority,
permission/plan gating, abort/resume). Run `npm test` in `frontend/` first —
all must pass before starting this script.

## Setup

- Windows machine with the Audity desktop app (cloud build: `npm run tauri:build:cloud`).
- A test organisation on Railway prod (or staging) with at least: 5 products,
  3 customers, 1 prior invoice. A brand-new org works after Step 2's warm.
- A second browser session logged into the same org (for the conflict step).
- To "go offline", disable Wi-Fi **and** unplug Ethernet (or disable the
  network adapter). Airplane mode is the cleanest. Note: WebView2 sometimes
  keeps `navigator.onLine === true` — the app detects real unreachability by
  probing, so allow up to ~15 s for banners to react.

---

## Part 1 — Online login and cache warm

| # | Step | Expected result |
|---|------|-----------------|
| 1.1 | Launch the app with internet ON. Sign in with email + password. | Dashboard loads. Toast "Welcome back!". |
| 1.2 | Stay on the dashboard ~30 s. Don't navigate anywhere. | Nothing visible — the cache warm runs silently in the background (starts ~3 s after the sidebar modules appear, 3 requests at a time). No spinners, no toasts. |
| 1.3 | (Verification) DevTools → Application → IndexedDB → `audity-offline-cache` → `responses`. | Entries exist for `/sales/invoices/`, `/inventory/products/`, `/customers/`, `/bills/`, `/expenses/` … — screens you never opened. Entries are keyed `<orgId>\|\|<url>`. |
| 1.4 | Below the password field on the login screen (log out and back in to see it): | "Offline access available" hint appears once a verifier has been issued (it is issued automatically in the background after every successful online login). |

## Part 2 — Go offline, full CRUD

| # | Step | Expected result |
|---|------|-----------------|
| 2.1 | Kill the internet (airplane mode). Try navigating: Sales, Products, Customers, Bills. | Amber banner: "You're offline. Showing cached data from Xm ago…". Every list renders from cache — including screens never opened while online (that's the warm). Allow one 10 s timeout on the first request if WebView2 lies about connectivity. |
| 2.2 | Create **3 sales** (New Sale → pick cached products/customers → Save). | Each save succeeds instantly (optimistic). Invoices appear in the Sales list with temporary IDs. The TopBar shows the sync badge with a spinner and count **3**. |
| 2.3 | **Edit a product** (change its selling price). | Saves instantly; new price visible in the list. Badge count **4**. |
| 2.4 | **Delete a customer** (one with no queued sale against them). | Row disappears. Badge count **5**. |
| 2.5 | Click the sync badge in the TopBar. | Drawer lists all 5 operations ("Create Invoices", "Update Products", "Delete Customers") with timestamps, each marked pending. |

## Part 3 — Restart offline, unlock with password

| # | Step | Expected result |
|---|------|-----------------|
| 3.1 | Quit the app completely (system tray too). Internet still OFF. Relaunch. | Login screen shows with the "Offline access available — works without internet if server is unreachable" hint. |
| 3.2 | Enter the same email + password. Submit. | Button shows "Verifying offline…" (~0.5–1 s PBKDF2), then toast "Signed in offline. Your changes will sync when you reconnect." Dashboard renders from cache. |
| 3.3 | Open the sync badge. | **All 5 queued operations survived the restart.** |
| 3.4 | Wrong-password check: log out of the grace session is not possible via TopBar? It is — but instead: quit, relaunch, and enter a WRONG password. | "Incorrect password. 4 offline attempts remaining." After 5 wrong attempts the verifier is wiped and only online login works. (Do this check LAST or on a second machine — it consumes the verifier.) |
| 3.5 | Create one more sale during the grace session. | Queues as before. Badge count **6**. |

## Part 4 — Reconnect: silent resume, then exactly-once sync

| # | Step | Expected result |
|---|------|-----------------|
| 4.1 | While mid-way through filling a New Sale form, turn internet back ON. Wait ≤15 s (probe interval). | **The screen does NOT change. No logout. No sign-in prompt.** The session silently upgrades itself (the password typed at unlock also unwrapped a stored refresh pass). Toast: "Back online — reconnected." followed by "Syncing 6 queued operations…" then "Synced 6 operations successfully." Badge disappears. Your half-filled form is untouched. |
| 4.2 | Finish and save that sale. | Saves **directly to the server** now (real session) — no queueing. |
| 4.3 | (Exactly-once verification) Check the Sales list and the backend (Django admin or a second session): | Exactly the invoices you created — **no duplicates**. Temp IDs are gone; invoices carry real server IDs and org-prefixed invoice numbers. The product shows the edited price; the deleted customer is gone. Totals match what you entered offline. |
| 4.4 | Toggle internet OFF and ON once more with an empty queue. | Toast "Back online" only. No sync toast, no duplicate submissions. |

### Part 4b — Banner fallback (when silent resume can't work)

The blue "sign in to sync" banner is now the FALLBACK, reached only when the
stored refresh pass is unusable. To test it, pick any one of:
(a) simulate 7+ days offline — delete the `audity-offline-refresh`
localStorage key while offline; (b) change the account password from another
device while this machine is offline; (c) unlock offline on a device whose
last online login pre-dates this build.

| # | Step | Expected result |
|---|------|-----------------|
| 4b.1 | With the refresh pass unusable (see above), reconnect during a grace session. | No logout, screen keeps working. After ~2.5 s a blue banner appears: "Back online — sign in to sync your N offline changes. You can keep working; nothing will be lost." with a "Sign in now" button. |
| 4b.2 | Keep working; save another sale. | Still queues (no tokens). Badge count grows. |
| 4b.3 | Click **Sign in now**, log in with email + password. | Normal online login. Immediately after the dashboard loads: "Syncing N queued operations…" → "Synced N operations successfully." A fresh refresh pass is stored for next time. |

## Part 5 — Conflict surfacing

| # | Step | Expected result |
|---|------|-----------------|
| 5.1 | Go offline. Edit product P's price in the app (queues an update). | Badge count 1. |
| 5.2 | From the second (online) session, **delete product P** (or void/modify the same record so the queued PATCH becomes invalid server-side). | — |
| 5.3 | Reconnect the test machine and sign back in when the banner appears. | Sync toast reports "Sync complete — 0 succeeded, 1 conflict needs attention." The TopBar badge turns **orange** with an alert triangle. |
| 5.4 | Click the badge. | The failed operation shows "Server rejected (4xx)" with **Retry** and **Dismiss** buttons. Footer notes conflicts are not retried automatically. |
| 5.5 | Click **Dismiss**. | Item removed; badge disappears. (Retry would re-queue it — with the record deleted server-side it would conflict again, which is correct.) |

## Part 6 — Session-boundary safety checks

| # | Step | Expected result |
|---|------|-----------------|
| 6.1 | With internet ON and an empty queue, press the TopBar **Sign out** button. Then go offline and relaunch. | Offline unlock is **NOT** available (explicit logout wipes the verifier and cached data — that's the hand-the-device-away path). Online login required. |
| 6.2 | Log in online, then leave the app idle past the inactivity timeout (Settings → default 30 m), or relaunch after 12 h. | You're locked out to the login screen — but offline unlock still works and cached data + any queued items survive (inactivity/expiry use `clearSession`, not the full wipe). |
| 6.3 | Change the account password from another device while the test machine is offline with a stored verifier. Reconnect the test machine (while signed in online). | Within one reconnect cycle the app checks verifier status and silently discards the stale local verifier. Offline unlock stops working until the next online login (which issues a fresh verifier for the new password). |

---

## Pass criteria

Every "Expected result" above holds, and specifically the product owner's
sentence maps to: **1.1** (login requires internet) + **2.x/3.x** (offline
CRUD incl. restart) + **4.x** (automatic, exactly-once sync on restore) +
**5.x** (conflicts surfaced, never silently dropped) — with **no queued
operation ever lost** at any step.

## Known limitations (by design)

- Offline unlock requires one prior **online** login on that device (the
  verifier is issued at login and expires after 14 days).
- Silent resume works while the password-wrapped refresh pass is valid
  (7 days since the device last reached the server, sliding). Beyond that —
  or after a password change on any device — the sign-in banner is the
  fallback. The refresh pass only ever exists on disk encrypted under the
  user's password; no password, no server credential.
- 5 wrong offline passwords wipe the verifier and the wrapped refresh pass
  (brute-force guard).
- Reports/analytics are computed server-side and are excluded from the
  offline warm; they load on demand when online.

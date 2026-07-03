# Offline Re-Authentication — Backend Handoff

**Audience:** frontend engineer implementing the client half in the Tauri desktop app.
**Status:** backend complete (`apps/authentication`), migration `0007_offline_verifier`.

## Problem this solves

The desktop app clears all auth state on every launch and tokens are memory-only,
so a user who restarts the app **while offline** cannot get past the login wall —
even though IndexedDB caches and the optimistic mutation queue would let them work.
The backend now lets the client obtain, during a normal online session, a
**password verifier** it can check typed passwords against with no network,
granting a client-enforced "offline grace session".

## The verifier, in one paragraph

On request (and only after re-proving the password), the server derives
`PBKDF2-HMAC-SHA256(password, salt=16 random bytes, iterations=600000)` and
returns the salt + hash **once**. The server keeps **no copy of the salt or
hash** — only bookkeeping metadata (expiry, revoked flag, and a snapshot of
`User.token_version`). The client stores the blob encrypted at rest (OS keychain
via Tauri, or equivalent), and offline login = re-deriving PBKDF2 from the typed
password with WebCrypto and constant-time-comparing the result.

---

## API contract

All endpoints are under `/api/v1/auth/` and require a **valid Bearer access
token** (15-minute lifetime — issuance is therefore always tied to a fresh
online session). Error responses use the project-wide shape
`{"error": {"code": "...", "message": "..."}}`.

### 1. Issue / rotate — `POST /api/v1/auth/offline-verifier/`

Call right after a successful online login (and on reconnect when the cached
verifier is nearing expiry). Re-issuing rotates: the old record is deleted,
fresh salt + hash are returned.

Request body:

```json
{
  "password": "the user's current password",
  "device_label": "Ade's ThinkPad"        // optional, ≤100 chars, audit only
}
```

Success — `200 OK`:

```json
{
  "verifier": {
    "algorithm": "pbkdf2_sha256",
    "iterations": 600000,
    "salt": "<base64, 16 bytes>",
    "hash": "<base64, 32 bytes>",
    "user_id": "<uuid>",
    "email": "user@example.com",
    "mfa_enabled": false,
    "token_version": 3,
    "issued_at": "2026-07-03T10:15:00+00:00",
    "expires_at": "2026-07-17T10:15:00+00:00",
    "organisations": [ { "id": "<uuid>", "name": "...", "slug": "...",
                         "account_type": "...", "currency": "NGN",
                         "country": "NG", "is_active": true,
                         "onboarding_completed": true } ]
  }
}
```

`organisations` is the same shape LoginView returns — snapshot it so the
offline grace session can restore tenant context (X-Organisation-ID) with no
network call.

Errors:

| Status | `error.code`       | Meaning                                        |
|--------|--------------------|------------------------------------------------|
| 400    | `invalid_password` | Password did not match — nothing was issued.   |
| 400    | (DRF validation)   | `password` missing / too long.                 |
| 401    | —                  | Missing/expired access token.                  |
| 429    | `throttled`        | Rate limit hit (5/hour per user, see below).   |

**Rate limit:** 5 requests/hour per authenticated user
(`OfflineVerifierRateThrottle`, scope `offline_verifier`). This is deliberate:
the endpoint accepts a password, so the throttle makes it useless as a
password-guessing oracle for someone holding a stolen access token. Don't
call it in a retry loop.

### 2. Status — `GET /api/v1/auth/offline-verifier/status/`

Call on every reconnect (e.g. alongside the existing `/auth/ping/` probe
transition to online). Decides whether the locally cached verifier is still
trustworthy.

`200 OK`:

```json
{
  "token_version": 4,
  "active": false,
  "reason": "password_changed",   // null | "not_issued" | "revoked" | "password_changed" | "expired"
  "issued_at": "2026-07-03T10:15:00+00:00",   // null when not_issued
  "expires_at": "2026-07-17T10:15:00+00:00"   // null when not_issued
}
```

Client rules on reconnect:

- `active: true` **and** `token_version` equals the `token_version` stored in
  your cached verifier blob → keep it.
- Anything else → **purge the local verifier immediately** and re-issue after
  the next successful online login. `password_changed` means the password was
  changed on another device while this one was offline.

### 3. Revoke — `DELETE /api/v1/auth/offline-verifier/`

`200 OK`: `{ "message": "Offline verifier revoked.", "revoked": true }`
(`revoked: false` when there was nothing active to revoke — idempotent, safe
to call defensively on explicit logout / "remove this device").

### Server-side invalidation (no client action needed)

`POST /auth/change-password/` and `POST /auth/password-reset/confirm/` both:

1. increment `User.token_version` (already existing behaviour — kills JWTs), and
2. explicitly revoke the offline verifier.

Either signal alone is sufficient: the verifier stores
`token_version_at_issue`, so even if the explicit revoke were skipped, the
status endpoint reports `password_changed`.

---

## What the frontend must implement

1. **After successful online login:** `POST /offline-verifier/` with the
   password the user just typed (you have it in memory at that moment — do not
   persist the plaintext). Store the whole `verifier` object **encrypted at
   rest** (Tauri: OS keychain / stronghold; at minimum encrypt with a key held
   in the keychain — plain IndexedDB/localStorage is NOT acceptable for this
   blob).
2. **Offline login path (startup guard):** if the server is unreachable and a
   non-expired verifier exists for the typed email:
   - derive `PBKDF2-HMAC-SHA256(typedPassword, base64decode(salt), iterations)`
     via `crypto.subtle.importKey("raw", ...)` + `deriveBits` (native in the
     webview, ~0.5 s at 600k iterations);
   - constant-time compare against `base64decode(hash)`;
   - on match, start a **limited offline grace session**: restore org context
     from the snapshot, mark the session `offline: true`, keep the mid-session
     offline machinery (IndexedDB caches, mutation queue) as-is.
   - enforce `expires_at` locally: past expiry, refuse offline login and
     require a network login.
   - apply a local attempt counter (e.g. 5 tries then wipe the verifier) —
     the server can't rate-limit offline guesses, so the client must.
3. **On reconnect:** call `GET /offline-verifier/status/`; purge/re-issue per
   the rules above. Then let the normal token-refresh/login flow take over —
   the offline grace session never mints real JWTs; queued mutations sync only
   after a genuine online authentication.
4. **On logout / "sign out on this device":** `DELETE /offline-verifier/` and
   wipe the local blob.
5. **MFA accounts:** the payload includes `mfa_enabled`. Offline verification
   is single-factor by nature. Current backend policy is to issue the verifier
   for MFA users too; if product wants stricter behaviour, gate the offline
   grace session client-side (e.g. read-only) or ask backend to refuse
   issuance when `mfa_enabled` — one-line change in `OfflineVerifierView.post`.

## Security rationale (why it's shaped this way)

- **No second server-side password hash.** The derived hash exists only in the
  one-time response. A DB breach yields the same attack surface as before
  (the primary Argon2 hash), plus non-secret metadata.
- **Independent salt/KDF.** The verifier can't be correlated with, or replayed
  against, the `authentication_user` hash. We never return the user-table hash.
- **Issuance needs token + password.** The access token proves a fresh session
  (15-min lifetime); the password proves the caller knows the credential now.
  A stolen token can't mint a verifier; a stolen verifier blob can't call the
  API.
- **Throttled at 5/hour/user** so the password check isn't a guessing oracle.
- **PBKDF2 over Argon2** solely because the client must re-derive offline and
  WebCrypto supports PBKDF2 natively; 600k iterations is the OWASP figure for
  PBKDF2-HMAC-SHA256. If the frontend later ships an Argon2 WASM/rust path,
  the `algorithm` field is there to version the migration.
- **14-day expiry + rotation on every issuance** bounds the useful life of a
  stolen (still encrypted) blob; **token_version snapshot + explicit revoke**
  guarantee password changes invalidate it server-side.
- **The offline grace session is client-enforced and limited by design.** It
  never produces server credentials; the server trusts nothing about it.

## Files

- `apps/authentication/models.py` — `OfflineVerifier` model (metadata only).
- `apps/authentication/migrations/0007_offline_verifier.py`
- `apps/authentication/serializers.py` — `OfflineVerifierRequestSerializer`.
- `apps/authentication/views.py` — `OfflineVerifierView`,
  `OfflineVerifierStatusView`; revoke hooks in `ChangePasswordView` and
  `PasswordResetConfirmView`.
- `apps/authentication/urls.py` — routes `auth-offline-verifier`,
  `auth-offline-verifier-status`.
- `apps/core/throttles.py` + `config/settings/base.py` — `offline_verifier`
  throttle scope (5/hour).
- `apps/authentication/tests.py` — `OfflineVerifierIssueTests`,
  `OfflineVerifierStatusAndRevokeTests`, `OfflineVerifierInvalidationTests`.

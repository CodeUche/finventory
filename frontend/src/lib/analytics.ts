// ── PostHog analytics wrapper ────────────────────────────────────────────────
// Thin, fail-safe wrapper around posthog-js used for product monitoring.
//
// Hardened for a financial application handling PII and money data. The config
// follows PostHog's security guidance for sensitive products:
//   • Session replay is DISABLED — even with input masking, replay renders
//     account balances, customer names and invoice amounts as DOM text, which
//     is too high-risk to ship for a finance app.
//   • Autocapture is ON but masks all text and element attributes, so usage
//     funnels are captured without leaking any rendered financial content.
//   • URLs are sanitized before every event so auth tokens that live in the
//     URL (invite tokens, ?token=…) are never sent to PostHog.
//   • Person profiles are created for identified (logged-in) users only.
//   • Do-Not-Track is respected.
//
// Everything no-ops gracefully when VITE_POSTHOG_KEY is unset (e.g. local dev
// builds), so analytics never blocks the app from running. PostHog is loaded
// lazily on init so it stays out of the critical render path.
//
// Configure via env (see .env.cloud):
//   VITE_POSTHOG_KEY   — your PostHog project API key (required to enable)
//   VITE_POSTHOG_HOST  — ingestion host (default https://us.i.posthog.com)
import type { PostHog } from 'posthog-js'
import type { Organisation, User } from '@/types'

const KEY = import.meta.env.VITE_POSTHOG_KEY as string | undefined
const HOST = (import.meta.env.VITE_POSTHOG_HOST as string | undefined) ?? 'https://us.i.posthog.com'

let client: PostHog | null = null

// ── URL sanitization ─────────────────────────────────────────────────────────
// Auth tokens appear both as path segments (/accept-invite/<token>) and as
// query params (?token=…). We redact both so no secret ever reaches PostHog.
const TOKEN_PATH_PREFIXES = ['/accept-invite/', '/reject-invite/']
const SENSITIVE_QUERY_PARAMS = ['token', 'code', 'access', 'refresh', 'email', 'key', 'password', 'otp', 'uid']

export function sanitizeUrl(raw: string): string {
  if (!raw || typeof raw !== 'string') return raw
  try {
    const hasScheme = /^[a-z]+:\/\//i.test(raw)
    const base = 'http://app.local'
    const url = new URL(raw, hasScheme ? undefined : base)

    // Redact token-bearing path segments.
    let path = url.pathname
    for (const prefix of TOKEN_PATH_PREFIXES) {
      if (path.toLowerCase().startsWith(prefix)) { path = `${prefix}:token`; break }
    }

    // Redact sensitive query params (keep the key so funnels still group).
    for (const p of SENSITIVE_QUERY_PARAMS) {
      if (url.searchParams.has(p)) url.searchParams.set(p, ':redacted')
    }

    const qs = url.searchParams.toString()
    const tail = `${path}${qs ? `?${qs}` : ''}`
    // Bare-path input → return a bare path; absolute input → keep host.
    if (!hasScheme || url.origin === base) return tail
    return url.host ? `${url.protocol}//${url.host}${tail}` : tail
  } catch {
    // If parsing fails, drop everything after the first '?' to be safe.
    return raw.split('?')[0]
  }
}

// PostHog attaches the raw URL to many events (incl. autocaptured ones), so we
// scrub every URL-bearing property centrally rather than only on pageviews.
const URL_PROPS = [
  '$current_url', '$pathname', '$referrer',
  '$initial_current_url', '$initial_pathname', '$initial_referrer',
]

/** True once PostHog has been initialised with a valid key. */
export const analyticsEnabled = () => client !== null

/**
 * Initialise PostHog. Safe to call once at app startup. If no key is configured
 * the function returns immediately and every other helper becomes a no-op.
 */
export async function initAnalytics(): Promise<void> {
  if (client || !KEY) return
  try {
    const { default: posthog } = await import('posthog-js')
    posthog.init(KEY, {
      api_host: HOST,
      // SPA with a custom router — we send $pageview manually on route change.
      capture_pageview: false,
      capture_pageleave: true,
      // Capture interactions, but never the rendered text or element attributes
      // (which on a finance UI can hold balances, names, amounts, etc.).
      autocapture: true,
      mask_all_text: true,
      mask_all_element_attributes: true,
      // Strip advertising IDs and other personal data from captured URLs.
      mask_personal_data_properties: true,
      // Session replay is too risky for a finance UI — keep it off entirely.
      disable_session_recording: true,
      // Only create person profiles for users we explicitly identify.
      person_profiles: 'identified_only',
      // No cookies — desktop WebView + web both persist fine in localStorage,
      // and this avoids third-party-cookie / cross-site exposure.
      persistence: 'localStorage',
      secure_cookie: true,
      // Respect Do-Not-Track.
      respect_dnt: true,
      // Final scrub: strip tokens from any URL property on any outgoing event.
      before_send: (event) => {
        if (!event) return event
        const props = event.properties as Record<string, unknown> | undefined
        if (props) {
          for (const k of URL_PROPS) {
            if (typeof props[k] === 'string') props[k] = sanitizeUrl(props[k] as string)
          }
        }
        return event
      },
      loaded: (ph) => { ph.debug(false) },
    })
    client = posthog
  } catch {
    // Network / import failure is non-fatal — analytics simply stays off.
    client = null
  }
}

/** Associate subsequent events with a logged-in user and their organisation. */
export function identifyUser(user: User, org?: Organisation | null): void {
  if (!client || !user?.id) return
  client.identify(user.id, {
    email: user.email,
    name: [user.first_name, user.last_name].filter(Boolean).join(' ').trim() || undefined,
    is_superuser: !!user.is_superuser,
    is_sub_account: !!user.is_sub_account,
  })
  if (org?.id) {
    // Group events by organisation so PostHog can report per-tenant usage.
    client.group('organisation', org.id, { name: org.name })
  }
}

/** Capture a custom product event. */
export function track(event: string, props?: Record<string, unknown>): void {
  client?.capture(event, props)
}

/** Send a manual pageview — call on every route change. */
export function trackPageview(path: string): void {
  client?.capture('$pageview', { $current_url: sanitizeUrl(path) })
}

/** Clear identity on logout so the next user starts a fresh session. */
export function resetAnalytics(): void {
  client?.reset()
}

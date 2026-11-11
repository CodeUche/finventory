/**
 * The web address customers can open, for links the owner copies and shares (e.g. the shop page).
 *
 * In a browser that is simply the page's own origin. Inside the desktop (Tauri) or Android
 * (Capacitor) app the page origin is an internal one such as http://tauri.localhost, which
 * nobody else can open, so there the address must come from VITE_PUBLIC_WEB_ORIGIN.
 * Returns null when no shareable address is known.
 */
export function publicWebOrigin(): string | null {
  const configured = import.meta.env.VITE_PUBLIC_WEB_ORIGIN?.trim().replace(/\/+$/, '')
  if (configured) return configured
  const { origin, protocol, hostname } = window.location
  const nativeShell =
    protocol !== 'http:' && protocol !== 'https:'
      ? true
      : hostname === 'tauri.localhost' || '__TAURI_INTERNALS__' in window || '__TAURI__' in window
        || !!(window as { Capacitor?: unknown }).Capacitor
  return nativeShell ? null : origin
}

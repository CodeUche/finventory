/**
 * Opens a URL in the system's default browser.
 *
 * Uses Tauri's shell plugin when available (required for WebView2 in the
 * desktop app — `window.open` opens a new WebView window instead of the
 * system browser). Falls back to `window.open` for web/dev mode.
 */
export async function openExternal(url: string): Promise<void> {
  try {
    const { open } = await import('@tauri-apps/plugin-shell')
    await open(url)
  } catch {
    // Fallback for web/browser mode or if plugin isn't available
    window.open(url, '_blank', 'noopener,noreferrer')
  }
}

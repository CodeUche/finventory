/**
 * Desktop auto-update.
 *
 * No-op in the browser (the hosted web build) — the Tauri updater plugin only
 * exists in the desktop app. Fully non-fatal: any failure is logged in dev and
 * swallowed so it can never block or crash app startup.
 *
 * Flow: check the update endpoint → if a newer signed version exists, ask the
 * user → download + install → relaunch.
 */
import toast from 'react-hot-toast'
import { confirmDialog } from '@/lib/dialog'

function isTauriRuntime(): boolean {
  return typeof window !== 'undefined' &&
    ('__TAURI_INTERNALS__' in window || '__TAURI__' in window)
}

export async function checkForUpdates(): Promise<void> {
  if (!isTauriRuntime()) return
  try {
    const { check } = await import('@tauri-apps/plugin-updater')
    const update = await check()
    if (!update) return

    const proceed = (await confirmDialog(
      `A new version of Audity (${update.version}) is available.\n\n` +
      `Update now? Audity will restart automatically when it's done.`,
    ))
    if (!proceed) return

    const id = toast.loading('Downloading update…')
    await update.downloadAndInstall()
    toast.success('Update installed — restarting…', { id })

    const { relaunch } = await import('@tauri-apps/plugin-process')
    await relaunch()
  } catch (err) {
    if (import.meta.env.DEV) console.error('[Audity] update check failed:', err)
  }
}

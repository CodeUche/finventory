import { useCallback, useEffect, useRef, useState } from 'react'
import toast from 'react-hot-toast'
import {
  MessageSquare, FileSpreadsheet, HardDrive, CalendarDays, Send, Mail,
  Loader2, CheckCircle2, LogOut, Pencil, RefreshCw,
} from 'lucide-react'
import { confirmDialog } from '@/lib/dialog'
import { openExternal } from '@/lib/openExternal'
import { loadPaystackScript } from '@/lib/paystack'
import {
  connectorsApi,
  type BillingInterval,
  type ConnectorCatalogEntry,
  type ConnectorGalleryResponse,
  type ConnectorKey,
} from '@/services/connectorsApi'

const isTauri = typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window

const ICONS: Record<ConnectorKey, React.ElementType> = {
  slack: MessageSquare,
  google_sheets: FileSpreadsheet,
  google_drive: HardDrive,
  google_calendar: CalendarDays,
  telegram: Send,
  gmail: Mail,
}
const ICON_STYLES: Record<ConnectorKey, string> = {
  slack: 'bg-gold-500/10 text-gold-400',
  google_sheets: 'bg-green-500/10 text-green-400',
  google_drive: 'bg-blue-500/10 text-blue-400',
  google_calendar: 'bg-purple-500/10 text-purple-400',
  telegram: 'bg-sky-500/10 text-sky-400',
  gmail: 'bg-red-500/10 text-red-400',
}

// Connectors with user-editable settings (shows the Pencil/config drawer).
// Telegram has none — its only "config" (chat_id) is set exclusively by the
// /start webhook handshake server-side, never through this UI (mirrors the
// backend's ConnectorConfigView.ALLOWED_KEYS, which has no telegram entry).
// Gmail DOES need one — its notify_email recipient address — same "connected
// but not yet configured" gap Drive's folder_id/Calendar's calendar_id have.
const CONFIGURABLE_CONNECTORS: ConnectorKey[] = ['slack', 'google_sheets', 'google_drive', 'google_calendar', 'gmail']

function errMsg(err: unknown, fallback: string): string {
  const apiErr = (err as { response?: { data?: { error?: unknown } } })?.response?.data?.error
  if (typeof apiErr === 'string') return apiErr
  if (apiErr && typeof apiErr === 'object' && 'message' in apiErr) {
    return String((apiErr as { message?: unknown }).message ?? fallback)
  }
  return fallback
}

function fmtNaira(amount: string): string {
  return '₦' + parseFloat(amount).toLocaleString('en-NG', { minimumFractionDigits: 0 })
}

/** Accepts either a raw Google Sheets spreadsheet ID or a full sheet URL. */
function extractSpreadsheetId(input: string): string {
  const trimmed = input.trim()
  const match = trimmed.match(/\/spreadsheets\/d\/([a-zA-Z0-9-_]+)/)
  return match ? match[1] : trimmed
}

interface ConfigDraft {
  channel_id?: string
  spreadsheet_id?: string
  sheet_range?: string
  folder_id?: string
  calendar_id?: string
  notify_email?: string
}

export default function ConnectorsPage() {
  const [data, setData] = useState<ConnectorGalleryResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const hasLoadedOnce = useRef(false)

  const [connectingKey, setConnectingKey] = useState<string | null>(null)
  const [restoringKey, setRestoringKey] = useState<string | null>(null)
  const [disconnectingKey, setDisconnectingKey] = useState<string | null>(null)
  const [addonPurchasingKey, setAddonPurchasingKey] = useState<string | null>(null)
  const [addonInterval, setAddonInterval] = useState<Record<string, BillingInterval>>({})

  const [configOpenKey, setConfigOpenKey] = useState<string | null>(null)
  const [configDraft, setConfigDraft] = useState<ConfigDraft>({})
  const [savingConfig, setSavingConfig] = useState(false)
  const [slackChannels, setSlackChannels] = useState<{ id: string; name: string }[]>([])
  const [driveFolders, setDriveFolders] = useState<{ id: string; name: string }[]>([])

  // Two independent poll timers per connector: one for the Nango connect
  // session, one for the ₦4,500/mo add-on's Paystack checkout — a user can
  // have both a connect attempt and an add-on purchase in flight if they
  // retry after closing the app mid-flow.
  const pollTimers = useRef<Record<string, ReturnType<typeof setInterval>>>({})
  const autoChecked = useRef<Set<string>>(new Set())

  const stopPolling = (pollKey: string) => {
    const t = pollTimers.current[pollKey]
    if (t) { clearInterval(t); delete pollTimers.current[pollKey] }
  }

  useEffect(() => {
    return () => { Object.keys(pollTimers.current).forEach(stopPolling) }
  }, [])

  const load = useCallback(async () => {
    // Only the very first load blocks the page with a spinner — a refetch
    // after an action must not unmount the tree (see IntegrationsPage's
    // identical `load()` comment: it was wiping a one-time reveal banner
    // off screen mid-read before this fix pattern was established).
    if (!hasLoadedOnce.current) setLoading(true)
    try {
      const res = await connectorsApi.gallery()
      setData(res.data)

      // Silent one-shot recovery, once per page visit: a connection stuck
      // PENDING (webhook hasn't landed yet, or the desktop OAuth tab was
      // closed before the app could detect completion) gets one quiet
      // restore attempt with no toast on failure — the "Restore" link
      // stays available either way. Same trio as IntegrationsPage's
      // pending-product auto-restore.
      res.data.connectors.forEach((entry) => {
        const connKey = `connect:${entry.connector_key}`
        if (entry.connection?.status === 'pending' && !autoChecked.current.has(connKey)) {
          autoChecked.current.add(connKey)
          connectorsApi.restore(entry.connector_key).then(() => load()).catch(() => {/* still pending — silent */})
        }
        const addonKey = `addon:${entry.connector_key}`
        if (entry.addon_subscription?.status === 'incomplete' && !autoChecked.current.has(addonKey)) {
          autoChecked.current.add(addonKey)
          connectorsApi.restoreAddonPayment(entry.connector_key).then(() => load()).catch(() => {/* still pending — silent */})
        }
      })
    } catch (err) {
      toast.error(errMsg(err, 'Failed to load connectors'))
    } finally {
      hasLoadedOnce.current = true
      setLoading(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => { load() }, [load])

  /** Background poll after opening the Nango Connect UI. Caps at 5 min (100 * 3s). */
  const startConnectPolling = (key: ConnectorKey) => {
    const pollKey = `connect:${key}`
    stopPolling(pollKey)
    let attempts = 0
    pollTimers.current[pollKey] = setInterval(async () => {
      attempts++
      if (attempts > 100) { stopPolling(pollKey); return }
      try {
        await connectorsApi.restore(key)
        stopPolling(pollKey)
        toast.success(`Connected! Events will start flowing shortly.`)
        load()
      } catch { /* not connected yet — keep polling */ }
    }, 3000)
  }

  /** Same pattern for the ₦4,500/mo add-on's Paystack checkout, chaining
   *  straight into the Nango Connect flow once the payment settles. */
  const startAddonPolling = (key: ConnectorKey) => {
    const pollKey = `addon:${key}`
    stopPolling(pollKey)
    let attempts = 0
    pollTimers.current[pollKey] = setInterval(async () => {
      attempts++
      if (attempts > 100) { stopPolling(pollKey); return }
      try {
        await connectorsApi.restoreAddonPayment(key)
        stopPolling(pollKey)
        toast.success('Add-on purchase confirmed! Continuing to connect…')
        await load()
        handleConnect(key)
      } catch { /* not paid yet — keep polling */ }
    }, 3000)
  }

  const handleConnect = async (key: ConnectorKey) => {
    setConnectingKey(key)
    try {
      const res = await connectorsApi.connect(key)
      const { connect_link } = res.data
      if (isTauri) {
        await openExternal(connect_link)
      } else {
        window.open(connect_link, '_blank', 'noopener,noreferrer')
      }
      // Telegram's connect_link opens the Telegram app/web to a chat with
      // Audity's bot rather than an OAuth sign-in screen — same
      // openExternal()/new-tab mechanism either way (see connectorsApi.ts's
      // module docstring), just different copy.
      toast(
        key === 'telegram'
          ? 'Telegram opened — send the pre-filled /start message to the bot. Come back here once done.'
          : 'Sign-in opened in your browser. Come back here once done — the connection activates automatically.',
        { duration: 8000 },
      )
      startConnectPolling(key)
      load() // refresh so the button flips to "Connecting…" while the poll runs
    } catch (err) {
      toast.error(errMsg(err, 'Failed to start the connection'))
    } finally {
      setConnectingKey(null)
    }
  }

  const handleRestore = async (key: ConnectorKey) => {
    setRestoringKey(key)
    try {
      await connectorsApi.restore(key)
      toast.success('Connected!')
      stopPolling(`connect:${key}`)
      load()
    } catch (err) {
      toast.error(errMsg(err, "Not connected yet. If you've finished signing in, wait a moment and try again."))
    } finally {
      setRestoringKey(null)
    }
  }

  const handleDisconnect = async (entry: ConnectorCatalogEntry) => {
    const label = entry.connection?.external_account_label
      ? `${entry.name} (${entry.connection.external_account_label})`
      : entry.name
    if (!(await confirmDialog(`Disconnect ${label}? Audity will stop sending events to it immediately.`))) return
    setDisconnectingKey(entry.connector_key)
    try {
      await connectorsApi.disconnect(entry.connector_key)
      toast.success(`${entry.name} disconnected.`)
      setConfigOpenKey((k) => (k === entry.connector_key ? null : k))
      load()
    } catch (err) {
      toast.error(errMsg(err, 'Failed to disconnect'))
    } finally {
      setDisconnectingKey(null)
    }
  }

  const handleAddonPurchase = async (key: ConnectorKey) => {
    setAddonPurchasingKey(key)
    try {
      const interval = addonInterval[key] ?? 'monthly'
      const res = await connectorsApi.initiateAddon(key, interval)
      const { access_code, reference, public_key, amount_kobo, email, authorization_url } = res.data

      if (!public_key) {
        toast.error('Paystack public key is not configured. Contact support.')
        return
      }

      if (isTauri) {
        await openExternal(authorization_url)
        toast('Payment page opened in your browser. Come back here once done — the connector activates automatically.', { duration: 8000 })
        startAddonPolling(key)
        load()
        return
      }

      await loadPaystackScript()
      const handler = window.PaystackPop.setup({
        key: public_key,
        email,
        amount: amount_kobo,
        ref: reference,
        ...(access_code ? { accessCode: access_code } : {}),
        currency: 'NGN',
        onClose: () => toast('Payment cancelled.', { icon: '🚫' }),
        callback: (response) => handleAddonPaymentSuccess(key, response.reference),
      })
      handler.openIframe()
    } catch (err) {
      toast.error(errMsg(err, 'Failed to initiate payment'))
    } finally {
      setAddonPurchasingKey(null)
    }
  }

  const handleAddonPaymentSuccess = async (key: ConnectorKey, reference: string) => {
    toast.loading('Confirming payment…', { id: 'connector-addon-verify' })
    try {
      await connectorsApi.verifyAddonPayment(reference)
      toast.success('Add-on activated! Continuing to connect…', { id: 'connector-addon-verify' })
      await load()
      handleConnect(key)
    } catch (err) {
      toast.error(errMsg(err, 'Payment verification failed'), { id: 'connector-addon-verify' })
    }
  }

  const openConfig = async (entry: ConnectorCatalogEntry) => {
    setConfigOpenKey(entry.connector_key)
    setConfigDraft({
      channel_id: entry.connection?.config?.channel_id ?? '',
      spreadsheet_id: entry.connection?.config?.spreadsheet_id ?? '',
      sheet_range: entry.connection?.config?.sheet_range ?? '',
      folder_id: entry.connection?.config?.folder_id ?? '',
      calendar_id: entry.connection?.config?.calendar_id ?? '',
      notify_email: entry.connection?.config?.notify_email ?? '',
    })
    if (entry.connector_key === 'slack' && slackChannels.length === 0) {
      try {
        const res = await connectorsApi.slackChannels()
        setSlackChannels(res.data.channels)
      } catch { /* fall back to manual channel-ID entry, no toast needed */ }
    }
    if (entry.connector_key === 'google_drive' && driveFolders.length === 0) {
      try {
        const res = await connectorsApi.googleDriveFolders()
        setDriveFolders(res.data.folders)
      } catch { /* fall back to manual folder-ID entry, no toast needed */ }
    }
  }

  const saveConfig = async (key: ConnectorKey) => {
    setSavingConfig(true)
    try {
      let payload: Record<string, string>
      if (key === 'slack') {
        payload = { channel_id: configDraft.channel_id ?? '' }
      } else if (key === 'google_sheets') {
        payload = {
          spreadsheet_id: extractSpreadsheetId(configDraft.spreadsheet_id ?? ''),
          sheet_range: configDraft.sheet_range || 'Sheet1',
        }
      } else if (key === 'google_drive') {
        payload = { folder_id: configDraft.folder_id ?? '' }
      } else if (key === 'google_calendar') {
        // "primary" (the org's own default calendar) if left blank
        payload = { calendar_id: configDraft.calendar_id || 'primary' }
      } else {
        // gmail — the only other configurable connector (telegram has no config UI)
        payload = { notify_email: (configDraft.notify_email ?? '').trim() }
      }
      await connectorsApi.updateConfig(key, payload)
      toast.success('Settings saved.')
      setConfigOpenKey(null)
      load()
    } catch (err) {
      toast.error(errMsg(err, 'Failed to save settings'))
    } finally {
      setSavingConfig(false)
    }
  }

  if (loading || !data) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 size={24} className="animate-spin text-gold-400" />
      </div>
    )
  }

  const { quota, connectors, addon_price } = data
  const quotaPct = quota.max > 0 ? Math.min(100, Math.round((quota.used / quota.max) * 100)) : 0

  return (
    <div className="space-y-8 w-full">
      <div className="flex items-start justify-between gap-5 flex-wrap">
        <div>
          <h1 className="text-2xl font-bold text-white">Connectors</h1>
          <p className="text-slate-400 text-sm mt-1 max-w-xl">
            Connect Audity to the apps you already use. Click Connect, sign in, done —
            no API keys, no webhook URLs.
          </p>
        </div>
        <div className="flex flex-col gap-2 bg-surface-800 border border-surface-700 rounded-xl px-4 py-3.5 min-w-[230px]">
          <div className="flex items-baseline justify-between gap-3">
            <span className="text-[11px] font-bold uppercase tracking-wider text-gold-400">
              {quota.plan_name ?? 'Free'} plan
            </span>
            <span className="text-xs text-slate-400">
              <b className="text-white tabular-nums">{quota.used}</b> of{' '}
              <b className="text-white tabular-nums">{quota.max}</b> used
            </span>
          </div>
          <div className="h-1.5 rounded-full bg-surface-700 overflow-hidden">
            <div
              className="h-full rounded-full bg-gradient-to-r from-gold-600 to-gold-400 transition-all"
              style={{ width: `${quotaPct}%` }}
            />
          </div>
        </div>
      </div>

      <div>
        <h2 className="text-[11px] font-semibold text-slate-500 uppercase tracking-widest mb-3">
          Available now
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {connectors.map((entry) => {
            const Icon = ICONS[entry.connector_key]
            const conn = entry.connection
            const isActive = conn?.status === 'active'
            const isPending = conn?.status === 'pending'
            const hasQuotaSlot = quota.used < quota.max
            const hasActiveAddon = entry.addon_subscription?.status === 'active'
            const needsAddon = !isActive && !isPending && !hasQuotaSlot && !hasActiveAddon
            const interval = addonInterval[entry.connector_key] ?? 'monthly'
            const price = interval === 'annual' ? addon_price.annual : addon_price.monthly

            return (
              <div key={entry.connector_key} className="bg-surface-800 border border-surface-700 rounded-2xl p-5 flex flex-col gap-4 hover:border-surface-600 transition-colors">
                <div className="flex items-start gap-3">
                  <div className={`w-[42px] h-[42px] rounded-xl flex items-center justify-center shrink-0 ${ICON_STYLES[entry.connector_key]}`}>
                    <Icon size={19} />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-[15px] font-bold text-white">{entry.name}</p>
                    <p className="text-xs text-slate-400 leading-relaxed mt-0.5">{entry.description}</p>
                  </div>
                </div>

                {needsAddon && (
                  <div className="flex items-center gap-1.5 text-xs">
                    <button
                      onClick={() => setAddonInterval((prev) => ({ ...prev, [entry.connector_key]: 'monthly' }))}
                      className={`px-2.5 py-1 rounded-full border transition-colors ${interval === 'monthly' ? 'border-gold-500 text-gold-400 bg-gold-500/10' : 'border-surface-600 text-slate-400 hover:text-slate-200'}`}
                    >
                      Monthly
                    </button>
                    <button
                      onClick={() => setAddonInterval((prev) => ({ ...prev, [entry.connector_key]: 'annual' }))}
                      className={`px-2.5 py-1 rounded-full border transition-colors ${interval === 'annual' ? 'border-gold-500 text-gold-400 bg-gold-500/10' : 'border-surface-600 text-slate-400 hover:text-slate-200'}`}
                    >
                      Annual
                    </button>
                  </div>
                )}

                <div className="flex items-center justify-between gap-3 pt-3 border-t border-surface-700 mt-auto">
                  {isActive ? (
                    <span className="inline-flex items-center gap-1.5 text-xs font-semibold px-2.5 py-1 rounded-full bg-green-500/10 text-green-400 border border-green-500/25">
                      <CheckCircle2 size={12} />
                      Connected{conn?.external_account_label ? ` as ${conn.external_account_label}` : ''}
                    </span>
                  ) : isPending ? (
                    <span className="text-xs text-slate-500">
                      {entry.connector_key === 'telegram' ? 'Waiting for /start in Telegram…' : 'Waiting for sign-in to complete…'}
                    </span>
                  ) : needsAddon ? (
                    <span className="text-xs text-slate-500">Beyond your plan's quota</span>
                  ) : (
                    <span className="text-xs text-slate-500">Included in your plan</span>
                  )}

                  <div className="flex items-center gap-2 shrink-0">
                    {isActive && (
                      <>
                        {CONFIGURABLE_CONNECTORS.includes(entry.connector_key) && (
                          <button
                            onClick={() => (configOpenKey === entry.connector_key ? setConfigOpenKey(null) : openConfig(entry))}
                            className="p-2 rounded-lg border border-surface-600 text-slate-400 hover:text-white hover:border-surface-500 transition-colors"
                            title="Configure"
                          >
                            <Pencil size={14} />
                          </button>
                        )}
                        <button
                          onClick={() => handleDisconnect(entry)}
                          disabled={disconnectingKey === entry.connector_key}
                          className="px-3.5 py-2 rounded-lg text-xs font-semibold border border-surface-600 text-slate-300 hover:text-red-400 hover:border-red-500/40 transition-colors flex items-center gap-1.5 disabled:opacity-50"
                        >
                          {disconnectingKey === entry.connector_key ? <Loader2 size={13} className="animate-spin" /> : <LogOut size={13} />}
                          Disconnect
                        </button>
                      </>
                    )}

                    {isPending && (
                      <button
                        onClick={() => handleRestore(entry.connector_key)}
                        disabled={restoringKey === entry.connector_key}
                        className="px-4 py-2 rounded-lg text-sm font-semibold bg-surface-700 text-slate-300 cursor-default flex items-center gap-1.5 disabled:opacity-70"
                        title="Restore connection — re-check if sign-in already completed"
                      >
                        {restoringKey === entry.connector_key
                          ? <Loader2 size={13} className="animate-spin" />
                          : <RefreshCw size={13} />}
                        Connecting…
                      </button>
                    )}

                    {!isActive && !isPending && !needsAddon && (
                      <button
                        onClick={() => handleConnect(entry.connector_key)}
                        disabled={connectingKey === entry.connector_key}
                        className="px-4 py-2 rounded-lg text-sm font-semibold bg-gold-500 hover:bg-gold-400 text-surface-950 transition-colors disabled:opacity-60 disabled:cursor-not-allowed flex items-center gap-1.5"
                      >
                        {connectingKey === entry.connector_key && <Loader2 size={13} className="animate-spin" />}
                        Connect
                      </button>
                    )}

                    {needsAddon && (
                      <button
                        onClick={() => handleAddonPurchase(entry.connector_key)}
                        disabled={addonPurchasingKey === entry.connector_key}
                        className="px-4 py-2 rounded-lg text-sm font-semibold border border-gold-600/40 text-gold-400 hover:bg-gold-500/10 transition-colors disabled:opacity-60 flex items-center gap-1.5"
                      >
                        {addonPurchasingKey === entry.connector_key && <Loader2 size={13} className="animate-spin" />}
                        Add connector — {fmtNaira(price)}/{interval === 'annual' ? 'yr' : 'mo'}
                      </button>
                    )}
                  </div>
                </div>

                {isActive && configOpenKey === entry.connector_key && (
                  <div className="pt-3 border-t border-surface-700 space-y-2.5">
                    {entry.connector_key === 'slack' ? (
                      <>
                        <label className="text-xs text-slate-400 block">Channel to post updates to</label>
                        {slackChannels.length > 0 ? (
                          <select
                            className="input"
                            value={configDraft.channel_id ?? ''}
                            onChange={(e) => setConfigDraft((d) => ({ ...d, channel_id: e.target.value }))}
                          >
                            <option value="">Select a channel…</option>
                            {slackChannels.map((c) => (
                              <option key={c.id} value={c.id}>#{c.name}</option>
                            ))}
                          </select>
                        ) : (
                          <input
                            className="input"
                            placeholder="Slack channel ID (e.g. C0123456789)"
                            value={configDraft.channel_id ?? ''}
                            onChange={(e) => setConfigDraft((d) => ({ ...d, channel_id: e.target.value }))}
                          />
                        )}
                      </>
                    ) : entry.connector_key === 'google_sheets' ? (
                      <>
                        <label className="text-xs text-slate-400 block">Google Sheet URL or ID</label>
                        <input
                          className="input"
                          placeholder="https://docs.google.com/spreadsheets/d/…"
                          value={configDraft.spreadsheet_id ?? ''}
                          onChange={(e) => setConfigDraft((d) => ({ ...d, spreadsheet_id: e.target.value }))}
                        />
                      </>
                    ) : entry.connector_key === 'google_drive' ? (
                      <>
                        <label className="text-xs text-slate-400 block">Folder to save PDFs into</label>
                        {driveFolders.length > 0 ? (
                          <select
                            className="input"
                            value={configDraft.folder_id ?? ''}
                            onChange={(e) => setConfigDraft((d) => ({ ...d, folder_id: e.target.value }))}
                          >
                            <option value="">Select a folder…</option>
                            {driveFolders.map((f) => (
                              <option key={f.id} value={f.id}>{f.name}</option>
                            ))}
                          </select>
                        ) : (
                          <input
                            className="input"
                            placeholder="Google Drive folder ID"
                            value={configDraft.folder_id ?? ''}
                            onChange={(e) => setConfigDraft((d) => ({ ...d, folder_id: e.target.value }))}
                          />
                        )}
                        <p className="text-[11px] text-slate-500">Invoice, payslip, and report PDFs will be saved here automatically.</p>
                      </>
                    ) : entry.connector_key === 'google_calendar' ? (
                      <>
                        <label className="text-xs text-slate-400 block">Calendar to add deadlines to</label>
                        <input
                          className="input"
                          placeholder="primary (your default calendar), or a calendar's email address"
                          value={configDraft.calendar_id ?? ''}
                          onChange={(e) => setConfigDraft((d) => ({ ...d, calendar_id: e.target.value }))}
                        />
                        <p className="text-[11px] text-slate-500">Leave blank to use your main Google Calendar.</p>
                      </>
                    ) : (
                      <>
                        <label className="text-xs text-slate-400 block">Email address to notify</label>
                        <input
                          type="email"
                          className="input"
                          placeholder="accountant@yourbusiness.com"
                          value={configDraft.notify_email ?? ''}
                          onChange={(e) => setConfigDraft((d) => ({ ...d, notify_email: e.target.value }))}
                        />
                        <p className="text-[11px] text-slate-500">
                          Sent from your own connected Gmail account when invoices are created and payments land.
                        </p>
                      </>
                    )}
                    <div className="flex items-center gap-2">
                      <button
                        onClick={() => saveConfig(entry.connector_key)}
                        disabled={savingConfig}
                        className="px-3.5 py-1.5 rounded-lg text-xs font-semibold bg-gold-500 hover:bg-gold-400 text-surface-950 transition-colors disabled:opacity-60 flex items-center gap-1.5"
                      >
                        {savingConfig && <Loader2 size={12} className="animate-spin" />}
                        Save
                      </button>
                      <button
                        onClick={() => setConfigOpenKey(null)}
                        className="px-3.5 py-1.5 rounded-lg text-xs text-slate-400 hover:text-slate-200 transition-colors"
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

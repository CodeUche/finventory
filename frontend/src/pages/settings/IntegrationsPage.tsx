import { useEffect, useState, useCallback, useRef } from 'react'
import toast from 'react-hot-toast'
import { Globe, Loader2, CheckCircle, ExternalLink, Trash2, Send, Key, Copy, Plus, RefreshCw } from 'lucide-react'
import { confirmDialog } from '@/lib/dialog'
import { openExternal } from '@/lib/openExternal'
import { loadPaystackScript } from '@/lib/paystack'
import {
  integrationsApi,
  unwrapList,
  EVENT_TYPES,
  type IntegrationProduct,
  type WebhookSubscription,
  type OrganisationAPIKey,
} from '@/services/integrationsApi'

const isTauri = typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window

function fmt(amount: string) {
  return '₦' + parseFloat(amount).toLocaleString('en-NG', { minimumFractionDigits: 2 })
}

function errMsg(err: any, fallback: string) {
  const apiErr = err?.response?.data?.error
  return typeof apiErr === 'string' ? apiErr : (apiErr?.message ?? fallback)
}

export default function IntegrationsPage() {
  const [products, setProducts] = useState<IntegrationProduct[]>([])
  const [webhooks, setWebhooks] = useState<WebhookSubscription[]>([])
  const [apiKeys, setApiKeys] = useState<OrganisationAPIKey[]>([])
  const [loading, setLoading] = useState(true)
  const [purchasing, setPurchasing] = useState<string | null>(null)
  const [restoring, setRestoring] = useState<string | null>(null)
  const hasLoadedOnce = useRef(false)
  // One poll interval per product key — a user can have both Webhooks and
  // Zapier purchases in flight at once, each needs its own timer.
  const pollTimers = useRef<Record<string, ReturnType<typeof setInterval>>>({})
  // Products we've already silently auto-restore-checked once this page
  // visit, so re-renders/refetches don't re-fire it in a loop.
  const autoChecked = useRef<Set<string>>(new Set())

  const stopPolling = (productKey: string) => {
    const t = pollTimers.current[productKey]
    if (t) { clearInterval(t); delete pollTimers.current[productKey] }
  }

  useEffect(() => {
    // Stop every in-flight poll on unmount so a closed page never leaks timers.
    return () => { Object.keys(pollTimers.current).forEach(stopPolling) }
  }, [])

  const load = useCallback(async () => {
    // Only show the full-page blocking spinner on the very first load.
    // Refetching after an action (e.g. onChange() from WebhooksSection right
    // after creating a webhook) must NOT unmount the page — doing so was
    // wiping the one-time-secret reveal banner off screen before the user
    // could read it, since `if (loading) return <spinner/>` replaced the
    // whole tree the instant this ran.
    if (!hasLoadedOnce.current) setLoading(true)
    try {
      const [productsRes, webhooksRes, keysRes] = await Promise.allSettled([
        integrationsApi.products(),
        integrationsApi.listWebhooks(),
        integrationsApi.listApiKeys(),
      ])
      if (productsRes.status === 'fulfilled') {
        const fresh = unwrapList(productsRes.value.data)
        setProducts(fresh)
        // Silent one-shot recovery: if a product is still 'pending' (e.g. the
        // desktop checkout was completed in the system browser in an earlier
        // session and the app was closed before it could be detected), try
        // once per page visit — no toast on failure, the "Restore access"
        // button stays available either way.
        fresh
          .filter((p) => p.entitlement_status === 'pending' && !autoChecked.current.has(p.key))
          .forEach((p) => {
            autoChecked.current.add(p.key)
            integrationsApi.restorePurchase(p.key).then(() => load()).catch(() => {/* still pending — silent */})
          })
      }
      if (webhooksRes.status === 'fulfilled') setWebhooks(unwrapList(webhooksRes.value.data))
      if (keysRes.status === 'fulfilled') setApiKeys(unwrapList(keysRes.value.data))
    } finally {
      hasLoadedOnce.current = true
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const handlePaymentSuccess = useCallback(async (reference: string) => {
    toast.loading('Confirming payment…', { id: 'int-pay-verify' })
    try {
      await integrationsApi.verifyPurchase(reference)
      toast.success('Purchase confirmed! The integration is now active.', { id: 'int-pay-verify' })
      load()
    } catch (err: any) {
      toast.error(errMsg(err, 'Payment verification failed'), { id: 'int-pay-verify' })
    }
  }, [load])

  /** Background poll after opening the external checkout — no user action needed
   *  if they return to the app while it's still open. Caps at 5 min (100 * 3s). */
  const startPolling = (product: IntegrationProduct) => {
    stopPolling(product.key)
    let attempts = 0
    pollTimers.current[product.key] = setInterval(async () => {
      attempts++
      if (attempts > 100) { stopPolling(product.key); return }
      try {
        await integrationsApi.restorePurchase(product.key)
        stopPolling(product.key)
        toast.success(`${product.name} purchase confirmed! It's now active.`)
        load()
      } catch { /* not paid yet — keep polling */ }
    }, 3000)
  }

  /** Manual fallback ("Restore access") — for when the poll already timed out,
   *  or payment was completed in an earlier app session entirely. */
  const handleRestore = async (product: IntegrationProduct) => {
    setRestoring(product.id)
    try {
      await integrationsApi.restorePurchase(product.key)
      toast.success(`${product.name} is now active.`)
      stopPolling(product.key)
      load()
    } catch (err: any) {
      toast.error(errMsg(err, "No completed payment found yet. If you've already paid, wait a moment and try again."))
    } finally {
      setRestoring(null)
    }
  }

  const handlePurchase = async (product: IntegrationProduct) => {
    setPurchasing(product.id)
    try {
      const res = await integrationsApi.purchase(product.key)
      const { access_code, reference, public_key, amount_kobo, email, authorization_url } = res.data

      if (!public_key) {
        toast.error('Paystack public key is not configured. Contact support.')
        return
      }

      if (isTauri) {
        await openExternal(authorization_url)
        toast('Payment page opened in your browser. Come back here once done — access is granted automatically.', { duration: 8000 })
        startPolling(product)
        load()  // refresh so the button flips to "Restore access" while the poll runs
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
        callback: (response) => handlePaymentSuccess(response.reference),
      })
      handler.openIframe()
    } catch (err: any) {
      const errData = err?.response?.data?.error
      if (!errData?.message) toast.error(errMsg(err, 'Failed to initiate payment'))
    } finally {
      setPurchasing(null)
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 size={24} className="animate-spin text-brand-400" />
      </div>
    )
  }

  return (
    <div className="space-y-8 w-full">
      <div>
        <h1 className="text-2xl font-bold text-white">Integrations</h1>
        <p className="text-slate-400 text-sm mt-1">
          Connect Audity to external apps and tools via outbound webhooks or Zapier.
        </p>
      </div>

      {/* Marketplace catalog */}
      <div>
        <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wide mb-3">Available Integrations</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {products.map((product) => {
            const isActive = product.entitlement_status === 'active'
            const isPending = product.entitlement_status === 'pending'
            return (
              <div key={product.id} className="card flex flex-col gap-3">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-xl bg-brand-500/10 flex items-center justify-center shrink-0">
                    <Globe size={18} className="text-brand-400" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-white font-semibold">{product.name}</p>
                    <p className="text-xs text-slate-500">{product.description}</p>
                  </div>
                  {isActive && (
                    <span className="text-xs font-medium px-2 py-0.5 rounded-full text-green-400 bg-green-400/10 flex items-center gap-1 shrink-0">
                      <CheckCircle size={12} /> Purchased
                    </span>
                  )}
                  {isPending && (
                    <span className="text-xs font-medium px-2 py-0.5 rounded-full text-amber-400 bg-amber-400/10 flex items-center gap-1 shrink-0">
                      Payment pending
                    </span>
                  )}
                </div>
                {isPending && (
                  <p className="text-xs text-slate-500 -mt-1">
                    Already paid? Click "Restore access" below — no need to pay again.
                  </p>
                )}
                <div className="flex items-center justify-between">
                  <span className="text-lg font-bold text-white tabular-nums">{fmt(product.price)}</span>
                  {!isActive && isPending && (
                    <button
                      onClick={() => handleRestore(product)}
                      disabled={restoring === product.id}
                      className="btn-primary text-sm flex items-center gap-1.5"
                      title="Already paid? Re-check your payment status and grant access."
                    >
                      {restoring === product.id ? (
                        <Loader2 size={14} className="animate-spin" />
                      ) : (
                        <RefreshCw size={14} />
                      )}
                      Restore access
                    </button>
                  )}
                  {!isActive && !isPending && (
                    <button
                      onClick={() => handlePurchase(product)}
                      disabled={purchasing === product.id}
                      className="btn-primary text-sm flex items-center gap-1.5"
                    >
                      {purchasing === product.id ? (
                        <Loader2 size={14} className="animate-spin" />
                      ) : (
                        <ExternalLink size={14} />
                      )}
                      {`Purchase — ${fmt(product.price)}`}
                    </button>
                  )}
                </div>
              </div>
            )
          })}
          {products.length === 0 && (
            <p className="text-sm text-slate-500">No integrations are available right now.</p>
          )}
        </div>
      </div>

      <WebhooksSection webhooks={webhooks} products={products} onChange={load} />
      <ApiKeysSection apiKeys={apiKeys} onChange={load} />
    </div>
  )
}

function WebhooksSection({
  webhooks,
  products,
  onChange,
}: {
  webhooks: WebhookSubscription[]
  products: IntegrationProduct[]
  onChange: () => void
}) {
  const [targetUrl, setTargetUrl] = useState('')
  const [selectedEvents, setSelectedEvents] = useState<string[]>([])
  const [creating, setCreating] = useState(false)
  const [revealedSecret, setRevealedSecret] = useState<{ id: string; secret: string } | null>(null)
  const [testingId, setTestingId] = useState<string | null>(null)

  const toggleEvent = (value: string) => {
    setSelectedEvents((prev) => (prev.includes(value) ? prev.filter((v) => v !== value) : [...prev, value]))
  }

  const handleCreate = async () => {
    if (!targetUrl.trim()) { toast.error('Enter a target URL.'); return }
    if (selectedEvents.length === 0) { toast.error('Select at least one event type.'); return }
    setCreating(true)
    try {
      const res = await integrationsApi.createWebhook({ target_url: targetUrl.trim(), event_types: selectedEvents })
      setRevealedSecret({ id: res.data.id, secret: res.data.secret })
      setTargetUrl('')
      setSelectedEvents([])
      toast.success('Webhook created.')
      onChange()
    } catch (err: any) {
      toast.error(errMsg(err, 'Failed to create webhook'))
    } finally {
      setCreating(false)
    }
  }

  const handleDelete = async (webhook: WebhookSubscription) => {
    if (!(await confirmDialog(`Delete this webhook (${webhook.target_url})? It will stop receiving events immediately.`))) return
    try {
      await integrationsApi.deleteWebhook(webhook.id)
      toast.success('Webhook deleted.')
      onChange()
    } catch (err: any) {
      toast.error(errMsg(err, 'Failed to delete webhook'))
    }
  }

  const handleTest = async (webhook: WebhookSubscription) => {
    setTestingId(webhook.id)
    try {
      const res = await integrationsApi.testWebhook(webhook.id)
      const { status } = res.data as { status: string }
      if (status === 'delivered') toast.success('Test event delivered successfully.')
      else if (status === 'pending') toast('Test event queued for retry — target did not respond as expected.', { icon: '⏳' })
      else toast.error('Test event failed to deliver. Check the target URL and try again.')
    } catch (err: any) {
      toast.error(errMsg(err, 'Failed to send test event'))
    } finally {
      setTestingId(null)
    }
  }

  const handleCopySecret = async (secret: string) => {
    try {
      await navigator.clipboard.writeText(secret)
      toast.success('Secret copied to clipboard.')
    } catch {
      toast.error('Could not copy — select and copy manually.')
    }
  }

  return (
    <div>
      <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wide mb-3">Webhook Subscriptions</h2>

      {revealedSecret && (
        <div className="card mb-4 border-amber-500/40 space-y-2">
          <p className="text-sm text-amber-400 font-medium">Save this signing secret now — it will not be shown again.</p>
          <div className="flex items-center gap-2">
            <code className="flex-1 text-xs bg-surface-900 border border-surface-700 rounded-lg px-3 py-2 text-slate-300 overflow-x-auto tabular-nums">
              {revealedSecret.secret}
            </code>
            <button onClick={() => handleCopySecret(revealedSecret.secret)} className="btn-ghost text-xs shrink-0">
              <Copy size={13} /> Copy
            </button>
          </div>
          <button onClick={() => setRevealedSecret(null)} className="text-xs text-slate-500 hover:text-slate-300">
            Dismiss
          </button>
        </div>
      )}

      <div className="card space-y-3 mb-4">
        <p className="text-sm text-white font-medium">Add a new webhook</p>
        <input
          type="url"
          placeholder="https://your-app.example.com/webhooks/audity"
          value={targetUrl}
          onChange={(e) => setTargetUrl(e.target.value)}
          className="input w-full"
        />
        <div className="flex flex-wrap gap-2">
          {EVENT_TYPES.map((et) => (
            <label
              key={et.value}
              className="flex items-center gap-1.5 text-xs text-slate-300 bg-surface-700/40 border border-surface-600 rounded-lg px-2.5 py-1.5 cursor-pointer"
            >
              <input
                type="checkbox"
                checked={selectedEvents.includes(et.value)}
                onChange={() => toggleEvent(et.value)}
                className="accent-brand-500"
              />
              {et.label}
            </label>
          ))}
        </div>
        <button onClick={handleCreate} disabled={creating} className="btn-primary text-sm flex items-center gap-1.5">
          {creating ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
          Add webhook
        </button>
        {products.some((p) => p.entitlement_status !== 'active') && (
          <p className="text-xs text-slate-500">
            Note: webhooks tied to a specific integration require that integration's purchase to be active first.
          </p>
        )}
      </div>

      <div className="space-y-2">
        {webhooks.map((webhook) => (
          <div key={webhook.id} className="card flex items-center gap-3">
            <div className="flex-1 min-w-0">
              <p className="text-sm text-white truncate">{webhook.target_url}</p>
              <p className="text-xs text-slate-500">{webhook.event_types.join(', ')}</p>
            </div>
            <span className={`text-xs font-medium px-2 py-0.5 rounded-full shrink-0 ${webhook.is_active ? 'text-green-400 bg-green-400/10' : 'text-slate-400 bg-slate-400/10'}`}>
              {webhook.is_active ? 'Active' : 'Inactive'}
            </span>
            <button
              onClick={() => handleTest(webhook)}
              disabled={testingId === webhook.id}
              className="btn-ghost text-xs flex items-center gap-1 shrink-0"
            >
              {testingId === webhook.id ? <Loader2 size={13} className="animate-spin" /> : <Send size={13} />}
              Send test event
            </button>
            <button
              onClick={() => handleDelete(webhook)}
              className="btn-ghost text-xs text-red-400 hover:text-red-300 flex items-center gap-1 shrink-0"
            >
              <Trash2 size={13} /> Delete
            </button>
          </div>
        ))}
        {webhooks.length === 0 && <p className="text-sm text-slate-500">No webhook subscriptions yet.</p>}
      </div>
    </div>
  )
}

function ApiKeysSection({ apiKeys, onChange }: { apiKeys: OrganisationAPIKey[]; onChange: () => void }) {
  const [creating, setCreating] = useState(false)
  const [revealedKey, setRevealedKey] = useState<string | null>(null)

  const handleCreate = async () => {
    setCreating(true)
    try {
      const res = await integrationsApi.createApiKey('Zapier')
      setRevealedKey(res.data.key)
      toast.success('API key created.')
      onChange()
    } catch (err: any) {
      toast.error(errMsg(err, 'Failed to create API key'))
    } finally {
      setCreating(false)
    }
  }

  const handleRevoke = async (key: OrganisationAPIKey) => {
    if (!(await confirmDialog(`Revoke API key "${key.name}"? Any integration using it will stop working immediately.`))) return
    try {
      await integrationsApi.revokeApiKey(key.id)
      toast.success('API key revoked.')
      onChange()
    } catch (err: any) {
      toast.error(errMsg(err, 'Failed to revoke API key'))
    }
  }

  const handleCopyKey = async (key: string) => {
    try {
      await navigator.clipboard.writeText(key)
      toast.success('API key copied to clipboard.')
    } catch {
      toast.error('Could not copy — select and copy manually.')
    }
  }

  return (
    <div>
      <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wide mb-3">API Keys (Zapier)</h2>

      {revealedKey && (
        <div className="card mb-4 border-amber-500/40 space-y-2">
          <p className="text-sm text-amber-400 font-medium">Save this API key now — it will not be shown again.</p>
          <div className="flex items-center gap-2">
            <code className="flex-1 text-xs bg-surface-900 border border-surface-700 rounded-lg px-3 py-2 text-slate-300 overflow-x-auto tabular-nums">
              {revealedKey}
            </code>
            <button onClick={() => handleCopyKey(revealedKey)} className="btn-ghost text-xs shrink-0">
              <Copy size={13} /> Copy
            </button>
          </div>
          <button onClick={() => setRevealedKey(null)} className="text-xs text-slate-500 hover:text-slate-300">
            Dismiss
          </button>
        </div>
      )}

      <button onClick={handleCreate} disabled={creating} className="btn-primary text-sm flex items-center gap-1.5 mb-4">
        {creating ? <Loader2 size={14} className="animate-spin" /> : <Key size={14} />}
        Generate Zapier API key
      </button>

      <div className="space-y-2">
        {apiKeys.map((key) => (
          <div key={key.id} className="card flex items-center gap-3">
            <div className="flex-1 min-w-0">
              <p className="text-sm text-white">{key.name}</p>
              <p className="text-xs text-slate-500 tabular-nums">{key.key_prefix}…</p>
            </div>
            <span className={`text-xs font-medium px-2 py-0.5 rounded-full shrink-0 ${key.is_active ? 'text-green-400 bg-green-400/10' : 'text-slate-400 bg-slate-400/10'}`}>
              {key.is_active ? 'Active' : 'Revoked'}
            </span>
            {key.is_active && (
              <button
                onClick={() => handleRevoke(key)}
                className="btn-ghost text-xs text-red-400 hover:text-red-300 flex items-center gap-1 shrink-0"
              >
                <Trash2 size={13} /> Revoke
              </button>
            )}
          </div>
        ))}
        {apiKeys.length === 0 && <p className="text-sm text-slate-500">No API keys yet.</p>}
      </div>
    </div>
  )
}

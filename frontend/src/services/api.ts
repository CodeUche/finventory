/**
 * Axios API client with JWT auth + tenant header injection.
 *
 * Automatically:
 *   - Injects Bearer token from Zustand auth store
 *   - Injects X-Organisation-ID from Zustand org store
 *   - Handles 401 by refreshing the access token
 *   - Redirects to /login on refresh failure
 */

import axios, { AxiosError, type AxiosAdapter, type AxiosResponse, type InternalAxiosRequestConfig } from 'axios'
import { fetch as tauriHttpFetch } from '@tauri-apps/plugin-http'
import toast from 'react-hot-toast'
import { useAuthStore } from '@/store/authStore'
import { offlineCache } from '@/lib/offlineCache'
import { syncEngine, isActionEndpoint, buildListUrl, _extractEntityType, _extractRecordId } from '@/lib/syncEngine'
import { localStore } from '@/lib/localStore'

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '/api/v1'

// ─── Tauri HTTP adapter ───────────────────────────────────────────────────────
// Uses @tauri-apps/plugin-http's fetch() which routes through Rust reqwest via
// Tauri IPC, bypassing WebView2 CORS entirely.  Falls back to native fetch()
// in web-browser contexts (plugin throws when __TAURI_INTERNALS__ is absent).
//
// Static import (not dynamic) so Vite bundles it at compile time — no silent
// failures like the dynamic-import approach that caused the original 401 bug.

// Resolved immediately — kept so the interceptor can await it symmetrically.
const _tauriReady: Promise<void> = Promise.resolve()

// ── Effective-offline tracking (Tauri workaround) ─────────────────────────────
// navigator.onLine is unreliable in Tauri/WebView2 — it may stay `true` even
// when the internet is cut and Railway is unreachable. We track actual API
// reachability here and dispatch synthetic offline/online events so the rest of
// the app (useNetworkStatus, offline banner) works correctly.
let _effectivelyOffline = false

function _signalOffline() {
  if (_effectivelyOffline) return          // already signalled
  _effectivelyOffline = true
  if (navigator.onLine) window.dispatchEvent(new Event('offline'))  // synthetic
  _startProbe()  // begin polling so we know when connectivity is restored
}

function _signalOnline() {
  if (!_effectivelyOffline) return         // wasn't offline
  _effectivelyOffline = false
  window.dispatchEvent(new Event('online'))  // triggers flush in useNetworkStatus
  _stopProbe()
}

// ── Background connectivity probe (Tauri workaround) ──────────────────────────
// When _effectivelyOffline is true the app serves all reads from cache and never
// makes a real network request — so _signalOnline() would never fire on its own.
// This probe pings a lightweight endpoint every 15 s until the request succeeds,
// then calls _signalOnline() to trigger a sync flush.
let _probeTimer: ReturnType<typeof setInterval> | null = null

function _startProbe() {
  if (_probeTimer) return  // already running
  const runProbe = async () => {
    if (!_effectivelyOffline) { _stopProbe(); return }
    try {
      const base = (import.meta.env.VITE_API_BASE_URL ?? '/api/v1').replace(/\/+$/, '')
      // Use the Tauri IPC fetch in the desktop app; native fetch in a browser
      // (where tauriHttpFetch would always throw and the probe could never
      // recover from a transient offline blip).
      const isTauriRuntime = typeof window !== 'undefined' &&
        ('__TAURI_INTERNALS__' in window || '__TAURI__' in window)
      const ping = isTauriRuntime ? tauriHttpFetch : fetch
      await ping(`${base}/auth/ping/`, { method: 'GET' } as RequestInit)
      _signalOnline()
    } catch {
      // Still offline — keep probing
    }
  }
  runProbe()  // fire immediately so recovery doesn't wait a full 15 s
  _probeTimer = setInterval(runProbe, 15_000)
}

function _stopProbe() {
  if (_probeTimer) { clearInterval(_probeTimer); _probeTimer = null }
}

// ── In-flight GET deduplication ───────────────────────────────────────────────
// Prevents duplicate network requests when two components call the same endpoint
// simultaneously (e.g. on first mount before cache exists).
interface Deferred {
  resolve: (v: AxiosResponse) => void
  reject: (e: unknown) => void
  promise: Promise<AxiosResponse>
}
function makeDeferred(): Deferred {
  let resolve!: (v: AxiosResponse) => void
  let reject!: (e: unknown) => void
  const promise = new Promise<AxiosResponse>((res, rej) => { resolve = res; reject = rej })
  return { resolve, reject, promise }
}
const _inflightGets = new Map<string, Deferred>()

// ── Cache-bypass flags ────────────────────────────────────────────────────────
// _pendingCacheBypass: URLs whose list cache was just invalidated by a mutation
//   but the async invalidation hasn't completed yet.  Set synchronously before
//   the first `await` in _writeThroughCache so the component's .then() callback
//   always bypasses the fresh-cache gate even if it runs before invalidation done.
// _bypassCacheUntil: epoch ms set by bypassNextGets(); all GETs skip fresh-cache
//   for that window — used by manual Refresh buttons across every module page.
const _pendingCacheBypass = new Set<string>()
let _bypassCacheUntil = 0

/** Call before triggering a manual reload — next 800 ms of GETs bypass the 5-min cache. */
export function bypassNextGets(ms = 800) {
  _bypassCacheUntil = Date.now() + ms
}

// ── Shared response converter (Response → AxiosResponse) ──────────────────
async function responseToAxios(resp: Response, config: InternalAxiosRequestConfig): Promise<AxiosResponse> {
  const respHeaders: Record<string, string> = {}
  resp.headers.forEach((v, k) => { respHeaders[k.toLowerCase()] = v })
  const ct = respHeaders['content-type'] ?? ''
  let data: unknown
  if (ct.includes('application/json')) {
    try { data = await resp.json() } catch { data = await resp.text() }
  } else if (config.responseType === 'blob') {
    data = await resp.blob()
  } else if (config.responseType === 'arraybuffer') {
    data = await resp.arrayBuffer()
  } else {
    data = await resp.text()
  }
  const axiosResp: AxiosResponse = {
    data, status: resp.status, statusText: resp.statusText,
    headers: respHeaders as never, config,
  }
  if (resp.ok) return axiosResp
  throw new AxiosError(`Request failed with status code ${resp.status}`, 'ERR_BAD_RESPONSE', config, null, axiosResp)
}

function buildTauriAdapter(): AxiosAdapter {
  return async (config): Promise<AxiosResponse> => {
    const method = (config.method ?? 'GET').toUpperCase()

    // Build absolute URL + query string
    const base = (config.baseURL ?? '').replace(/\/+$/, '')
    const path = (config.url ?? '').replace(/^\/+/, '')
    let url = path.startsWith('http') ? path : `${base}/${path}`
    if (config.params) {
      const qs = Object.entries(config.params as Record<string, unknown>)
        .filter(([, v]) => v !== undefined && v !== null)
        .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
        .join('&')
      if (qs) url += (url.includes('?') ? '&' : '?') + qs
    }

    // Extract headers via toJSON(true) — most reliable way to flatten an
    // AxiosHeaders instance to a plain { key: string } object.
    // toJSON(true) joins multi-value headers with ', ' and skips null/false entries.
    const rawHeaders = (config.headers?.toJSON?.(true) ?? config.headers ?? {}) as Record<string, unknown>
    const headers: Record<string, string> = {}
    for (const [k, v] of Object.entries(rawHeaders)) {
      if (typeof v === 'string' && v) headers[k] = v
    }
    // Zustand always wins for auth + org when it has values.
    // Using !hasX as the gate (old behaviour) allowed a stale api.defaults value
    // to silently persist once set, causing 403s mid-session when defaults drifted.
    // Now: if Zustand has the value, OVERRIDE whatever toJSON() produced.
    // Exception: during finishLogin() Zustand is empty (setAuth not called yet) —
    // in that case we keep what was explicitly passed in config.headers (bootstrapped
    // via api.defaults in finishLogin before setAuth runs).
    const _auth = getStoredAuth()
    const _orgId = getStoredOrgId()
    if (_auth.access)  headers['Authorization']     = `Bearer ${_auth.access}`
    if (_orgId)        headers['X-Organisation-ID'] = _orgId
    else               delete headers['X-Organisation-ID']
    // Last line of defense against a stale/re-merged Content-Type on a
    // FormData body. The request interceptor already tries to strip this
    // (config.headers.delete('Content-Type') when config.data is FormData),
    // but axios re-merges instance.defaults.headers (this client defaults to
    // 'application/json') back into the per-request AxiosHeaders at dispatch
    // time in a way the interceptor's edit doesn't survive — confirmed live:
    // a real multipart upload still carried Content-Type through to this
    // point despite the interceptor's delete, and the boundary-less/wrong
    // Content-Type made Django reject it with a 415. Since `headers` here is
    // the actual plain object hitting fetch()/tauriHttpFetch(), stripping it
    // at this final point is the one place guaranteed not to be re-merged.
    if (config.data instanceof FormData) delete headers['Content-Type']
    // Second fallback: also send org as ?org= query param.
    // Tauri's reqwest layer can silently drop custom request headers on some
    // platforms/OS versions.  RLSMiddleware checks the header first, then falls
    // back to ?org= so tenant context is always set regardless of header delivery.
    if (_orgId && !url.includes('org=') && !url.includes('/auth/')) {
      url += (url.includes('?') ? '&' : '?') + `org=${encodeURIComponent(_orgId)}`
    }
    if (import.meta.env.DEV) console.debug('[Audity] adapter headers:', JSON.stringify(Object.keys(headers)))

    const body = !['GET', 'HEAD'].includes(method) && config.data != null
      ? (config.data instanceof FormData ? config.data : config.data as string)
      : undefined

    // ── Timeout enforcement ──────────────────────────────────────────────────
    // Axios timeouts are implemented BY adapters — replacing the default adapter
    // silently discarded `timeout: 10000`, so stalled requests hung forever and
    // the offline machinery never triggered (no error was ever thrown).
    // AbortController covers both the Tauri IPC path and the native fetch fallback.
    const timeoutMs = typeof config.timeout === 'number' && config.timeout > 0 ? config.timeout : 10_000
    const ctrl = new AbortController()
    const timer = setTimeout(() => ctrl.abort(), timeoutMs)
    const timeoutError = () =>
      new AxiosError(`timeout of ${timeoutMs}ms exceeded`, 'ECONNABORTED', config, null, undefined)

    try {
      // ── Pure web-browser context (no Tauri IPC available) ────────────────────
      // When the app runs as a normal web page (e.g. the hosted review build)
      // there is no __TAURI_INTERNALS__, so tauriHttpFetch would always throw and
      // fall into the "Connection error" warning path on every single request.
      // Detect that once and go straight to native fetch — cleanly, with no
      // spurious toast. This branch is NEVER taken inside the desktop app, so the
      // existing Tauri behaviour below is completely unchanged.
      const isTauriRuntime = typeof window !== 'undefined' &&
        ('__TAURI_INTERNALS__' in window || '__TAURI__' in window)
      if (!isTauriRuntime) {
        try {
          const resp = await fetch(url, { method, headers, body, signal: ctrl.signal } as RequestInit)
          return await responseToAxios(resp, config)
        } catch (webErr) {
          // Real HTTP errors (401/403/500…) from responseToAxios propagate as-is.
          if (webErr instanceof AxiosError) throw webErr
          if (ctrl.signal.aborted) throw timeoutError()
          // Truly unreachable — AxiosError with config so interceptors can handle it.
          throw new AxiosError('Network Error', 'ERR_NETWORK', config, null, undefined)
        }
      }

      // Try Tauri IPC fetch first (routes through Rust reqwest, no CORS).
      // Only catch IPC-level errors (plugin not available / scope mismatch).
      // AxiosErrors thrown by responseToAxios for non-2xx MUST propagate directly —
      // they are real HTTP errors, not IPC failures.
      let ipcResponse: Response | null = null
      try {
        ipcResponse = await tauriHttpFetch(url, { method, headers, body, signal: ctrl.signal } as RequestInit)
      } catch (ipcErr) {
        // Timed out — throw with no error.response so the interceptor routes it
        // through the network-failure path (cache fallback / offline queue).
        // Intent: a server that won't answer within the deadline is effectively offline.
        if (ctrl.signal.aborted) throw timeoutError()
        // Tauri IPC threw — try native fetch as fallback.
        // Two sub-cases:
        //   A) native fetch succeeds → IPC scope/config issue → show connection warning
        //   B) native fetch also fails → device is truly offline → throw AxiosError with
        //      config attached so the error interceptor can serve cached data / queue the
        //      mutation optimistically. A plain TypeError from fetch() does NOT have
        //      error.config, which would silently bypass all offline handling.
        if (import.meta.env.DEV) console.error('[Audity] tauriHttpFetch threw:', String(ipcErr))
        try {
          const resp = await fetch(url, { method, headers, body, signal: ctrl.signal } as RequestInit)
          // Case A: IPC issue but network is reachable — warn and continue
          toast.error('Connection error — check your internet and try again.', { id: 'ipc-err', duration: 6000 })
          return await responseToAxios(resp, config)
        } catch (fallbackErr) {
          // Real HTTP errors from responseToAxios (401/403/500…) must propagate
          // as-is — converting them to ERR_NETWORK would misroute them into the
          // offline path instead of the auth-refresh / error-toast handlers.
          if (fallbackErr instanceof AxiosError) throw fallbackErr
          if (ctrl.signal.aborted) throw timeoutError()
          // Case B: truly offline — throw AxiosError so interceptors handle it correctly
          throw new AxiosError('Network Error', 'ERR_NETWORK', config, null, undefined)
        }
      }
      // IPC succeeded — convert and return (throws AxiosError for non-2xx, propagates up)
      return await responseToAxios(ipcResponse, config)
    } finally {
      clearTimeout(timer)
    }
  }
}

export const api = axios.create({
  baseURL: API_BASE,
  headers: { 'Content-Type': 'application/json' },
  timeout: 10000,
  // Always use the Tauri adapter. It detects __TAURI_INTERNALS__ at request
  // time (not module init) to avoid a race in tauri dev where the IPC object
  // is injected after modules are evaluated. Falls back to native fetch in
  // pure web browser contexts.
  adapter: buildTauriAdapter(),
})

// ─── Storage helpers ──────────────────────────────────────────────────────────
// Read directly from Zustand in-memory state — always reflects the latest
// setAuth() call instantly, with no localStorage serialisation/timing gap.
function getStoredAuth(): { access?: string; refresh?: string } {
  return useAuthStore.getState().tokens ?? {}
}
function getStoredOrgId(): string | null {
  return useAuthStore.getState().organisation?.id ?? null
}

// ─── Offline mutation helpers ─────────────────────────────────────────────────

/** Strip internal _meta fields before returning data to components. */
function _stripMetaFields(r: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  for (const [k, v] of Object.entries(r)) {
    if (!k.startsWith('_')) out[k] = v
  }
  return out
}

/**
 * Merge optimistic localStore records into an offlineCache list response.
 * Handles both paginated `{ results: [...] }` and plain array formats.
 */
async function _mergeLocalStore(orgId: string, url: string, cacheData: unknown): Promise<unknown> {
  try {
    const entityType = _extractEntityType(url)
    if (!entityType) return cacheData
    const localRecords = await localStore.getAll(orgId, entityType)
    if (localRecords.length === 0) return cacheData

    const localMap = new Map(localRecords.map((r) => [r._recordId, _stripMetaFields(r as Record<string, unknown>)]))

    const merge = (list: unknown[]): unknown[] => {
      const merged = list.map((item) => {
        const id = (item as { id?: string })?.id
        return id && localMap.has(id) ? localMap.get(id)! : item
      })
      // Append new optimistic records not yet in the server list
      for (const [id, rec] of localMap) {
        if (String(id).startsWith('tmp_') && !merged.some((i) => (i as { id?: string })?.id === id)) {
          merged.unshift(rec)
        }
      }
      return merged
    }

    if (Array.isArray(cacheData)) return merge(cacheData)
    const paged = cacheData as { results?: unknown[]; count?: number }
    if (Array.isArray(paged?.results)) {
      const mergedResults = merge(paged.results)
      // Preserve the server's TOTAL count (across all pages), adjusted only by
      // the optimistic records added to this page. Overwriting it with the page
      // length corrupted pagination totals after offline merges.
      const delta = mergedResults.length - paged.results.length
      const baseCount = typeof paged.count === 'number' ? paged.count : paged.results.length
      return { ...paged, results: mergedResults, count: Math.max(0, baseCount + delta) }
    }
  } catch { /* non-fatal */ }
  return cacheData
}

/**
 * Build an Axios adapter that applies the mutation optimistically and queues it.
 * Called from both the request interceptor and the error interceptor.
 */
function _buildOfflineMutationAdapter(config: InternalAxiosRequestConfig): AxiosAdapter {
  return async (): Promise<AxiosResponse> => {
    const method = config.method?.toLowerCase() ?? 'post'
    const url = config.url ?? ''
    const isPost = method === 'post'
    const isDelete = method === 'delete'
    const orgId = getStoredOrgId() ?? 'anonymous'

    let rawData: Record<string, unknown> = {}
    try {
      rawData = typeof config.data === 'string' ? JSON.parse(config.data) : (config.data ?? {})
    } catch { /* non-fatal */ }

    // Generate temp ID for creates
    const tempId = isPost ? `tmp_${Date.now()}_${Math.random().toString(36).slice(2, 7)}` : undefined
    const responseData = isDelete ? null : (isPost ? { ...rawData, id: tempId } : rawData)
    const status = isDelete ? 204 : isPost ? 201 : 200

    // Update localStore immediately (offline reads will see this change)
    const entityType = isActionEndpoint(url) ? null : _extractEntityType(url)
    if (entityType) {
      if (isDelete) {
        const recordId = _extractRecordId(url)
        if (recordId) await localStore.remove(orgId, entityType, recordId)
      } else if (isPost && tempId && responseData) {
        await localStore.upsert(orgId, entityType, tempId, responseData as Record<string, unknown>)
      } else if (!isPost && !isDelete && responseData) {
        const recordId = _extractRecordId(url)
        if (recordId) await localStore.upsert(orgId, entityType, recordId, responseData as Record<string, unknown>)
      }
      // Patch the offlineCache list so the fresh-cache gate serves updated data
      await _patchCacheList(orgId, url, method, responseData, tempId)
    }

    // Enqueue for sync — don't await, fire and forget
    syncEngine.enqueue({ method: config.method!, url, data: config.data, tempId })
      .catch(() => {/* non-fatal */})

    toast('Saved offline — will sync when back online', { icon: '📋', id: 'offline-save', duration: 3000 })
    window.dispatchEvent(new CustomEvent('audity:data-changed'))

    return {
      data: responseData,
      status,
      statusText: isPost ? 'Created (offline)' : isDelete ? 'No Content (offline)' : 'OK (offline)',
      headers: {},
      config,
    } as AxiosResponse
  }
}

/**
 * Patch the offlineCache list entry after a mutation.
 * This keeps the fresh-cache gate serving current data after creates/edits/deletes.
 */
async function _patchCacheList(
  orgId: string,
  url: string,
  method: string,
  responseData: unknown,
  tempId?: string,
): Promise<void> {
  try {
    const listUrl = buildListUrl(url)
    if (listUrl === url) return  // this IS the list URL — nothing to patch
    const entry = await offlineCache.get(listUrl)
    if (!entry) return

    const isPost = method === 'post'
    const isPatch = method === 'put' || method === 'patch'
    const isDelete = method === 'delete'
    const recordId = tempId ?? _extractRecordId(url) ?? ''

    const update = (list: unknown[]): unknown[] => {
      if (isPost && responseData) return [responseData, ...list]
      if (isPatch && responseData) return list.map((i) => ((i as { id?: string })?.id === recordId ? { ...(i as object), ...(responseData as object) } : i))
      if (isDelete) return list.filter((i) => (i as { id?: string })?.id !== recordId)
      return list
    }

    let newData: unknown
    if (Array.isArray(entry.data)) {
      newData = update(entry.data)
    } else {
      const paged = entry.data as { results?: unknown[]; count?: number }
      if (Array.isArray(paged?.results)) {
        const newResults = update(paged.results)
        // Preserve the server's TOTAL count, adjusted by this patch's delta —
        // page length is NOT the total when the list spans multiple pages.
        const delta = newResults.length - paged.results.length
        const baseCount = typeof paged.count === 'number' ? paged.count : paged.results.length
        newData = { ...paged, results: newResults, count: Math.max(0, baseCount + delta) }
      } else {
        return
      }
    }

    await offlineCache.set(listUrl, newData)
    // Also invalidate the org-prefixed key so fresh-cache reads pick up the new data
    void orgId  // used implicitly via offlineCache.set which calls currentOrgId() internally
  } catch { /* non-fatal */ }
}

/**
 * Write-through after a successful ONLINE mutation.
 * Patches the cached list so offline reads stay current.
 */
async function _writeThroughCache(url: string, method: string, responseData: unknown, requestData: unknown): Promise<void> {
  const orgId = getStoredOrgId() ?? 'anonymous'
  const recordId = _extractRecordId(url) ?? ''

  // Update localStore
  const entityType = _extractEntityType(url)
  if (entityType && !isActionEndpoint(url)) {
    if (method === 'delete') {
      await localStore.remove(orgId, entityType, recordId)
    } else if (responseData && typeof responseData === 'object') {
      const dataId = (responseData as { id?: string })?.id ?? recordId
      if (dataId) await localStore.upsert(orgId, entityType, dataId, responseData as Record<string, unknown>)
    } else if (method === 'post' && requestData && typeof requestData === 'object') {
      // Some endpoints return minimal data — use request body as fallback
      const d = requestData as Record<string, unknown>
      const dataId = (responseData as { id?: string })?.id
      if (dataId) await localStore.upsert(orgId, entityType, dataId, { ...d, id: dataId })
    }
  }

  // Invalidate the list cache so the next GET always hits the network for fresh data.
  // _patchCacheList cannot reliably find the cached list because cache keys include
  // ?org=<uuid> query params that _patchCacheList doesn't know about.
  // invalidatePrefix wipes all variants (with and without params) so the next request
  // goes straight to the server and re-caches the authoritative server response.
  //
  // buildListUrl only strips a trailing UUID (e.g. /x/{id}/ → /x/), so it is a
  // no-op for a COLLECTION-level RPC action with no UUID anywhere in the path,
  // e.g. POST /messaging/conversations/get_or_create_direct/. Detected here:
  // (a) nothing was stripped, (b) this is a POST, and (c) the URL has more
  // than one segment, so the actual list root is that URL with its last
  // segment dropped (…/get_or_create_direct/ → …/conversations/). Without
  // this, such an action's invalidatePrefix call targets a URL nothing else
  // ever requests, and the real list (fetched moments later by the caller,
  // e.g. MessagesPage.startConversationWith's refreshList()) keeps serving
  // its pre-mutation fresh-cache entry — the new row silently doesn't appear
  // until the cache naturally expires 5 minutes later. Confirmed live via a
  // real browser: get_or_create_direct returned 201 with the new conversation,
  // but the sidebar list stayed empty until this fix.
  let listUrl = buildListUrl(url)
  if (listUrl === url && method === 'post') {
    const withoutTrailingSlash = url.replace(/\/$/, '')
    const lastSlash = withoutTrailingSlash.lastIndexOf('/')
    if (lastSlash > 0) listUrl = withoutTrailingSlash.slice(0, lastSlash + 1)
  }
  // Set bypass flag SYNCHRONOUSLY before any await — the component's .then() runs
  // before async invalidation completes, so the flag must be present immediately.
  _pendingCacheBypass.add(listUrl)
  await offlineCache.invalidatePrefix(listUrl)
  _pendingCacheBypass.delete(listUrl)
  window.dispatchEvent(new CustomEvent('audity:data-changed'))
}

// ─── Request interceptor ──────────────────────────────────────────────────────
api.interceptors.request.use(async (config: InternalAxiosRequestConfig) => {
  await _tauriReady  // no-op (resolved immediately) — kept for symmetry

  const auth = getStoredAuth()
  const orgId = getStoredOrgId()

  if (auth.access) {
    config.headers.Authorization = `Bearer ${auth.access}`
  }
  if (orgId) {
    config.headers['X-Organisation-ID'] = orgId
    // The Tauri IPC layer can silently drop custom headers before they reach
    // reqwest. Send org ID as a query param too — the backend reads it from
    // either request.META['HTTP_X_ORGANISATION_ID'] or request.GET['org'].
    config.params = { ...config.params, org: orgId }
  } else {
    // Actively remove stale org context — do not let a previous session's
    // X-Organisation-ID or ?org= param leak into requests when no org is set.
    delete config.headers['X-Organisation-ID']
    if (config.params && (config.params as Record<string, unknown>).org !== undefined) {
      const { org: _removed, ...rest } = config.params as Record<string, unknown>
      config.params = rest
    }
  }
  // FormData must NOT have Content-Type set — the browser adds the correct
  // multipart/form-data boundary automatically. Remove the global JSON default
  // AND any boundary-less 'multipart/form-data' a caller may have set
  // explicitly (a real bug found live: messagingApi.uploadAttachment did this
  // and the server 415'd, unable to parse a multipart Content-Type with no
  // boundary parameter). config.headers is an AxiosHeaders instance — its
  // header-name matching is case-insensitive via .delete()/.has(), but plain
  // `delete config.headers['Content-Type']` bracket access is NOT guaranteed
  // to hit the same case-normalized slot, so use the real API instead of
  // relying on the exact casing a caller happened to use.
  if (config.data instanceof FormData) {
    config.headers.delete('Content-Type')
  }

  // ── Offline optimistic mutations ────────────────────────────────────────────
  // When device is offline (or effectively offline), mutations get an immediate
  // synthetic success response so the UI updates right away.  The real request
  // is queued in syncEngine and replayed when connectivity is restored.
  //
  // SECURITY: auth endpoints (/auth/*) are NEVER handled offline.  A login or
  // token operation requires real server verification — a synthetic success
  // response would return undefined tokens, silently break finishLogin, and
  // redirect the user to /onboarding.  Auth failures must throw so the catch
  // block in LoginPage shows the correct "cannot connect" error.
  const isRetry = (config.headers as Record<string, string>)?.['X-Offline-Retry'] === '1'
  const isMutation = ['post', 'put', 'patch', 'delete'].includes(config.method?.toLowerCase() ?? '')
  const isAuthUrl = (config.url ?? '').includes('/auth/')
  // Account-level actions must NEVER be queued for later replay: creating an
  // organisation, billing/subscription changes, partner links, legal acceptance.
  // These aren't shop-floor data entry — replaying e.g. a queued "create
  // tenancy" hours later silently creates a duplicate organisation. If the
  // network is down they should FAIL VISIBLY instead.
  const NEVER_QUEUE = ['/tenancy/', '/subscriptions/', '/platform/', '/audit-log/']
  const isAccountLevel = NEVER_QUEUE.some((p) => (config.url ?? '').includes(p))
  // An offline grace session (PBKDF2 unlock) has NO tokens — any request that
  // reaches the network 401s and the refresh handler would tear the session
  // down. So while isOfflineSession is true the app stays in cache/queue mode
  // even if connectivity has returned; only /auth/* (the re-login) goes out.
  const isOfflineGraceSession = useAuthStore.getState().isOfflineSession
  const treatAsOffline = !navigator.onLine || _effectivelyOffline || (isOfflineGraceSession && !isAuthUrl)
  if (treatAsOffline && isMutation && !isRetry && !isAuthUrl && !isAccountLevel) {
    config.adapter = _buildOfflineMutationAdapter(config)
    return config
  }

  // ── Fresh-cache gate + in-flight deduplication for GET requests ─────────────
  // 1. If cached data is < 5 min old → serve instantly, skip network entirely.
  // 2. If the same URL is already in-flight → share the existing promise.
  // Both save bandwidth on slow/intermittent connections.
  const FRESH_MS = 5 * 60 * 1000
  const isBypassCache = (config.headers as Record<string, string>)?.['X-Bypass-Cache'] === '1'
  type ExtConfig = InternalAxiosRequestConfig & { _fromCache?: boolean; _dedupeKey?: string }
  if (!isMutation && !isBypassCache) {
    const cacheUrl = (config.url ?? '') + (config.params ? '?' + new URLSearchParams(config.params as Record<string, string>).toString() : '')
    // Check time-based bypass (manual Refresh buttons) and pending-invalidation bypass
    const isBypassWindow = Date.now() < _bypassCacheUntil
    const isPendingInvalidation = [..._pendingCacheBypass].some((prefix) => cacheUrl.startsWith(prefix))

    // 1. Fresh-cache: serve without hitting the network
    if (navigator.onLine && !_effectivelyOffline && !isBypassWindow && !isPendingInvalidation) {
      try {
        const entry = await offlineCache.get(cacheUrl)
        if (entry && Date.now() - entry.cachedAt < FRESH_MS) {
          (config as ExtConfig)._fromCache = true
          config.adapter = async (): Promise<AxiosResponse> => ({
            data: entry.data, status: 200, statusText: 'OK (fresh cache)', headers: {}, config,
          } as AxiosResponse)
          return config
        }
      } catch { /* non-fatal — fall through */ }
    }

    // 2. In-flight deduplication: join an existing request instead of firing a new one
    const inflight = _inflightGets.get(cacheUrl)
    if (inflight) {
      (config as ExtConfig)._fromCache = true   // skip re-caching the shared response
      config.adapter = () => inflight.promise
      return config
    }

    // Register a deferred for this URL so subsequent identical requests can join it
    const deferred = makeDeferred()
    _inflightGets.set(cacheUrl, deferred)
    ;(config as ExtConfig)._dedupeKey = cacheUrl
  }

  // ── Offline cache: serve cached GET responses when network is unavailable ──
  // (or when running an offline grace session — see treatAsOffline above)
  if (treatAsOffline && !isMutation) {
    const cacheUrl = (config.url ?? '') + (config.params ? '?' + new URLSearchParams(config.params as Record<string, string>).toString() : '')
    config.adapter = async (): Promise<AxiosResponse> => {
      const orgId = getStoredOrgId() ?? 'anonymous'
      // Try offlineCache first (has full paginated response structure)
      const entry = await offlineCache.get(cacheUrl)
      if (entry) {
        // Merge in any optimistic local records if the cache looks like a list
        const merged = await _mergeLocalStore(orgId, config.url ?? '', entry.data)
        return { data: merged, status: 200, statusText: 'OK (cached)', headers: {}, config } as AxiosResponse
      }
      // Fallback: assemble from localStore entities if we have them
      const entityType = _extractEntityType(config.url ?? '')
      if (entityType) {
        const records = await localStore.getAll(orgId, entityType)
        if (records.length > 0) {
          const cleaned = records.map(_stripMetaFields)
          return {
            data: { count: cleaned.length, next: null, previous: null, results: cleaned },
            status: 200, statusText: 'OK (local store)', headers: {}, config,
          } as AxiosResponse
        }
      }
      throw new AxiosError('No cached data available offline', 'ERR_NETWORK', config)
    }
  }

  return config
})

// ─── Response interceptor ─────────────────────────────────────────────────────
let isRefreshing = false
let failedQueue: Array<{ resolve: (v: unknown) => void; reject: (r: unknown) => void }> = []

const processQueue = (error: AxiosError | null, token: string | null = null) => {
  failedQueue.forEach(({ resolve, reject }) => {
    if (error) reject(error)
    else resolve(token)
  })
  failedQueue = []
}

type ExtConfig = InternalAxiosRequestConfig & { _fromCache?: boolean; _dedupeKey?: string; _retry?: boolean }

api.interceptors.response.use(
  async (res) => {
    const cfg = res.config as ExtConfig

    if (!cfg._fromCache) {
      // Backend flags any superuser request resolved against an org the user
      // isn't a member of (platform-admin "support access"). Surface it so
      // the UI shows a persistent banner — this must never be silent. Cached
      // responses are skipped (the outer guard) since they're fabricated
      // locally and never carry real headers.
      useAuthStore.getState().setSupportAccess(res.headers?.['x-support-access'] === 'true')
      const method = cfg.method?.toLowerCase() ?? ''
      const url = cfg.url ?? ''

      // ── Cache every real network GET so it's available offline later ──
      if (method === 'get' && url && res.data !== undefined) {
        const params = cfg.params
        const cacheUrl = url + (params ? '?' + new URLSearchParams(params as Record<string, string>).toString() : '')
        offlineCache.set(cacheUrl, res.data)
        // Resolve any in-flight deduplication waiters
        if (cfg._dedupeKey) {
          _inflightGets.get(cfg._dedupeKey)?.resolve(res)
          _inflightGets.delete(cfg._dedupeKey)
        }
        // Also seed localStore from list responses for richer offline reads
        const orgId = getStoredOrgId() ?? 'anonymous'
        const entityType = _extractEntityType(url)
        if (entityType && res.data) {
          const records: unknown[] = Array.isArray(res.data)
            ? res.data
            : (res.data as { results?: unknown[] })?.results ?? []
          if (records.length > 0) {
            localStore.upsertMany(orgId, entityType, records as Array<Record<string, unknown>>)
          }
        }
      }

      // ── Cache write-through for mutations ───────────────────────────────────
      // After a successful online mutation, patch the cached list so offline
      // reads stay current without waiting for a full list refresh.
      //
      // MUST be awaited here, not fired-and-forgotten: callers do
      // `await api.post(...); await load()` (see e.g. LeavePage.submitRequest),
      // and load() immediately re-GETs the same list URL. _writeThroughCache
      // does an async localStore.upsert BEFORE it sets the cache-bypass flag
      // (_pendingCacheBypass), so if this response resolves before that flag
      // is set, the component's very next GET can win the race and read the
      // fresh-cache gate's still-stale (pre-mutation) entry — the create/edit/
      // delete silently doesn't appear until the next unrelated cache expiry
      // or manual refresh. Awaiting it guarantees the bypass flag (and the
      // cache invalidation itself) is in place before this promise — and thus
      // any `await`ing caller — resolves.
      const isOnlineMutation = ['post', 'put', 'patch', 'delete'].includes(method)
      const isRetry = (cfg.headers as Record<string, string>)?.['X-Offline-Retry'] === '1'
      if (isOnlineMutation && !isRetry && !isActionEndpoint(url)) {
        await _writeThroughCache(url, method, res.data, cfg.data).catch(() => {/* non-fatal */})
      }

      _signalOnline()
    }
    return res
  },
  async (error: AxiosError) => {
    const original = error.config as ExtConfig

    // ── True network failure — no HTTP response received ─────────────────────
    // Handles the Tauri/WebView2 case where navigator.onLine stays `true` even
    // when the internet is cut and the Railway backend is unreachable.
    if (!error.response && original) {
      const method = original.method?.toLowerCase() ?? ''
      const url = original.url ?? ''
      const isRetry = (original.headers as Record<string, string>)?.['X-Offline-Retry'] === '1'
      const isMut = ['post', 'put', 'patch', 'delete'].includes(method)

      // Resolve (not reject) any in-flight dedup waiters for this URL with the
      // fabricated offline response. These early returns bypass the success
      // interceptor, so without this the deferred registered in the request
      // interceptor is never settled — the next identical GET joins a dead
      // promise and hangs forever (skeleton stuck / repeated re-fetch churn).
      const _settleDedupe = (resp: AxiosResponse) => {
        if (original._dedupeKey) {
          _inflightGets.get(original._dedupeKey)?.resolve(resp)
          _inflightGets.delete(original._dedupeKey)
        }
      }

      if (!isMut) {
        // GET: try cache fallback, then silent empty response when already offline
        const params = original.params
        const cacheUrl = url + (params ? '?' + new URLSearchParams(params as Record<string, string>).toString() : '')
        try {
          const orgId = getStoredOrgId() ?? 'anonymous'
          const entry = await offlineCache.get(cacheUrl)
          if (entry) {
            _signalOffline()
            const merged = await _mergeLocalStore(orgId, url, entry.data)
            const cachedResp = { data: merged, status: 200, statusText: 'OK (cached)', headers: {}, config: original } as AxiosResponse
            _settleDedupe(cachedResp)
            return cachedResp
          }
        } catch { /* non-fatal */ }
        // No cache — return empty data silently instead of rejecting when we're
        // in any offline-ish mode: truly offline, OR an offline grace session
        // (which deliberately serves from cache even when online, until the
        // user re-authenticates). Otherwise a fresh offline unlock with an empty
        // cache would surface "Connection failed: No cached data available
        // offline" on every dashboard request.
        // Mark _fromCache=true so the success interceptor does NOT write this
        // empty placeholder into IndexedDB — otherwise the 5-min fresh-cache gate
        // would serve { results: [] } for 5 minutes after connectivity is restored,
        // breaking membership parsing and keeping the sidebar blank.
        if (_effectivelyOffline || useAuthStore.getState().isOfflineSession) {
          (original as ExtConfig)._fromCache = true
          const emptyResp = { data: { results: [] }, status: 200, statusText: 'OK (offline)', headers: {}, config: original } as AxiosResponse
          _settleDedupe(emptyResp)
          return emptyResp
        }
      } else if (!isRetry && !url.includes('/auth/') &&
                 !['/tenancy/', '/subscriptions/', '/platform/', '/audit-log/'].some((p) => url.includes(p))) {
        // Mutation failed on the wire — treat optimistically (same as request interceptor).
        // Auth endpoints are excluded: a timed-out login must throw so LoginPage shows
        // the correct "cannot connect" error rather than receiving undefined tokens.
        // Account-level endpoints (tenancy/subscriptions/…) are excluded too:
        // replaying a queued "create organisation" later duplicates orgs — they
        // must fail visibly instead (matches the request-interceptor gate).
        _signalOffline()
        const adapter = _buildOfflineMutationAdapter(original)
        // adapter is async — call it directly to get the response
        try {
          const optimisticResp = await (adapter as () => Promise<AxiosResponse>)()
          return optimisticResp
        } catch {
          // If optimistic handling itself fails, fall through to the reject below
        }
      }

      // Reject any in-flight deduplication waiters for this URL
      if (original._dedupeKey) {
        _inflightGets.get(original._dedupeKey)?.reject(error)
        _inflightGets.delete(original._dedupeKey)
      }

      // Only show "Connection failed" on the first failure — once the amber
      // offline banner is visible, further network error toasts are noise.
      // Also suppressed during an offline grace session (the blue "sign in to
      // sync" banner already explains the state; a cache miss there is expected,
      // not a connection failure).
      if (!_effectivelyOffline && !useAuthStore.getState().isOfflineSession) {
        toast.error(`Connection failed: ${error.message ?? 'Network error'}`, {
          id: 'offline-network-err',
          duration: 6000,
        })
      }
      _signalOffline()
      return Promise.reject(error)
    }

    // Never attempt a token refresh for auth endpoints — a 401 there is a real credential
    // failure, not an expired token. Bypassing these prevents isRefreshing from getting stuck.
    const isAuthEndpoint = original.url?.includes('/auth/login/') ||
                           original.url?.includes('/auth/token/')

    if (error.response?.status === 401 && !original._retry && !isAuthEndpoint) {
      if (isRefreshing) {
        return new Promise((resolve, reject) => {
          failedQueue.push({ resolve, reject })
        }).then((token) => {
          original.headers.Authorization = `Bearer ${token}`
          return api(original)
        })
      }

      original._retry = true
      isRefreshing = true

      const auth = getStoredAuth()
      if (!auth.refresh) {
        // No refresh token — reset flag, drain queue, clear state.
        // clearSession (not logout): an expired session must not destroy the
        // offline verifier/cache — the user re-authenticates and continues.
        isRefreshing = false
        processQueue(error, null)
        useAuthStore.getState().clearSession()
        return Promise.reject(error)
      }

      try {
        const { data } = await api.post('/auth/token/refresh/', { refresh: auth.refresh })
        // IMPORTANT: ROTATE_REFRESH_TOKENS=True means Django returns a NEW refresh token.
        // We must save it — otherwise the next refresh attempt uses a blacklisted token → logout.
        const newAuth = {
          ...auth,
          access: data.access,
          refresh: data.refresh ?? auth.refresh,  // save rotated refresh token
        }
        // Write rotated tokens back into Zustand persisted state
        useAuthStore.getState().updateTokens({ access: newAuth.access, refresh: newAuth.refresh })
        // Re-wrap the stored offline-resume copy: BLACKLIST_AFTER_ROTATION
        // means the previously wrapped refresh token just died server-side.
        import('@/lib/offlineResume').then(({ onTokensRotated }) => onTokensRotated(newAuth.refresh)).catch(() => {})
        api.defaults.headers.common.Authorization = `Bearer ${data.access}`
        processQueue(null, data.access)
        original.headers.Authorization = `Bearer ${data.access}`
        return api(original)
      } catch (refreshError) {
        processQueue(refreshError as AxiosError, null)
        // Only end the session when the SERVER rejected the refresh token
        // (4xx = invalid/blacklisted/expired). A network failure or timeout —
        // e.g. the machine just woke from sleep, or the serverless backend is
        // cold-starting — must NOT log the user out: their refresh token is
        // still perfectly valid and the next attempt will succeed. This was
        // silently signing out users who "left the app for a few minutes"
        // regardless of their inactivity-timeout preference.
        const rStatus = (refreshError as AxiosError)?.response?.status
        if (rStatus && rStatus >= 400 && rStatus < 500) {
          toast.error('Your session expired — please sign in again.', { id: 'session-expired', duration: 5000 })
          // clearSession (not logout) — see the no-refresh-token branch above.
          useAuthStore.getState().clearSession()
        } else {
          // Transient failure: keep the session; allow a future retry to refresh.
          original._retry = false
          _signalOffline()
        }
        return Promise.reject(refreshError)
      } finally {
        isRefreshing = false
      }
    }

    // ── Clean up in-flight deduplication for HTTP errors ─────────────────────
    // The cleanup inside the !error.response block above only fires for network
    // failures. For real HTTP errors (401, 403, 500 …) the deferred must also be
    // rejected & removed, otherwise the next request for the same URL will join
    // the dead deferred and hang forever.
    if (original?._dedupeKey) {
      _inflightGets.get(original._dedupeKey)?.reject(error)
      _inflightGets.delete(original._dedupeKey)
    }

    // 402 — plan limit reached: show upgrade prompt
    if (error.response?.status === 402) {
      const errMsg = (error.response.data as any)?.error
      const msg = typeof errMsg === 'string' ? errMsg : 'Plan limit reached.'
      toast.error(`${msg} Upgrade your plan to continue.`, {
        id: 'plan-limit',
        duration: 6000,
        icon: '⚡',
      })
      return Promise.reject(error)
    }

    // Show toast for API errors (deduplicate using toast ID so poll loops don't spam)
    // Skip: 401 (handled by refresh logic), 403 (handled at component level),
    // auth endpoints (LoginPage/StaffLoginPage handle their own error toasts).
    const errData = (error.response?.data as any)?.error
    const status = error.response?.status
    const isAuthUrl = original.url?.includes('/auth/login/') ||
                      original.url?.includes('/auth/staff-login/')
    if (status === 500 && !isAuthUrl) {
      const msg = (typeof errData === 'string' ? errData : errData?.message) ?? 'Server error (500)'
      toast.error(`Server error: ${msg}`, { id: `500-${original.url}`, duration: 8000 })
    } else if (
      status === 403 && !isAuthUrl &&
      !window.location.pathname.startsWith('/onboarding') &&
      !window.location.pathname.startsWith('/platform-admin')
    ) {
      const forbiddenMsg = (typeof errData === 'string' ? errData : errData?.message)
        ?? (error.response?.data as any)?.detail
        ?? 'Access denied'
      const isOrgHeaderError = /organisation.*header|x-organisation/i.test(forbiddenMsg)
      // Org-header 403: retry once with Zustand org injected directly into headers.
      // This recovers mid-session org-header drift without user intervention.
      if (isOrgHeaderError && !(original as any)._orgRetry) {
        const orgId = getStoredOrgId()
        const originalOrg = original.headers?.['X-Organisation-ID'] as string | undefined
        // Only retry when we have a DIFFERENT (potentially valid) org ID — retrying
        // with the same invalid value would just get another 403 in a tight loop.
        if (orgId && orgId !== originalOrg) {
          (original as any)._orgRetry = true
          original.headers['X-Organisation-ID'] = orgId
          original.params = { ...(original.params ?? {}), org: orgId }
          return api(original)
        }
      }
      if (!isOrgHeaderError) {
        // Use message-based ID so multiple endpoints returning the same 403 message
        // (e.g. all partner endpoints failing with "subscription expired") show ONE toast.
        const toastId = `403-${forbiddenMsg.slice(0, 60)}`
        toast.error(forbiddenMsg, { id: toastId, duration: 6000 })
      }
    } else if (status === 402) {
      const msg = typeof errData === 'string' ? errData : errData?.message ?? 'Plan limit reached'
      toast.error(msg, { id: 'plan-limit', duration: 8000 })
    } else if (errData?.message && status !== 401 && !isAuthUrl) {
      const toastId = `api-err-${status}-${original.url}`
      toast.error(errData.message, { id: toastId, duration: 4000 })
    }

    return Promise.reject(error)
  },
)

// ─── Tauri-aware media fetch ──────────────────────────────────────────────────
// Use this instead of native fetch() to load images/files in the Tauri desktop
// app — native fetch() to http://localhost is blocked by WebView2.
export async function tauriFetch(url: string): Promise<Response> {
  try {
    return await tauriHttpFetch(url)
  } catch {
    return fetch(url)
  }
}

/**
 * Fetch a remote URL and return it as a base-64 data URL suitable for
 * <img src=...> or jsPDF.addImage().
 *
 * Returns null on any failure (network error, non-2xx status, non-image body)
 * so callers never receive a broken data: URI of an HTML error page.
 */
export async function urlToDataUrl(url: string | null | undefined): Promise<string | null> {
  if (!url) return null
  try {
    // Backend-relative paths (e.g. "/media/org_logos/...") resolve against
    // the Tauri webview's own origin (tauri://localhost), not the API host —
    // make them absolute against the API's origin first.
    let resolved = url
    if (/^\/(?!\/)/.test(url)) {
      const apiOrigin = new URL(API_BASE, window.location.href).origin
      resolved = apiOrigin + url
    }
    const res = await tauriFetch(resolved)
    if (!res.ok) return null          // 404/403/etc. → skip, don't convert error HTML
    const blob = await res.blob()
    return await new Promise<string>((resolve, reject) => {
      const reader = new FileReader()
      reader.onloadend = () => resolve(reader.result as string)
      reader.onerror = reject
      reader.readAsDataURL(blob)
    })
  } catch {
    return null
  }
}

// ─── Binary file upload (bypasses Tauri FormData/multipart bug) ───────────────
// Tauri's IPC layer serialises FormData as application/x-www-form-urlencoded
// instead of multipart/form-data. This helper sends the file as raw binary with
// an explicit Content-Type so the Django backend receives it correctly.
export async function uploadFileDirect(
  urlPath: string,   // e.g. '/tenancy/organisations/abc/upload_logo/'
  file: File,
): Promise<Response> {
  const base = API_BASE.startsWith('http')
    ? API_BASE.replace(/\/$/, '')
    : 'http://localhost:8000/api/v1'
  const { access } = getStoredAuth()
  const orgId = getStoredOrgId()
  const ab = await file.arrayBuffer()
  try {
    return await tauriHttpFetch(`${base}${urlPath}`, {
      method: 'POST',
      headers: {
        ...(access ? { Authorization: `Bearer ${access}` } : {}),
        ...(orgId ? { 'X-Organisation-ID': orgId } : {}),
        'Content-Type': file.type || 'application/octet-stream',
      },
      body: ab,
    } as RequestInit)
  } catch {
    return fetch(`${base}${urlPath}`, {
      method: 'POST',
      headers: {
        ...(access ? { Authorization: `Bearer ${access}` } : {}),
        ...(orgId ? { 'X-Organisation-ID': orgId } : {}),
        'Content-Type': file.type || 'application/octet-stream',
      },
      body: ab,
    })
  }
}

// ─── Typed helpers ────────────────────────────────────────────────────────────
export const authApi = {
  login: (email: string, password: string) =>
    api.post('/auth/login/', { email, password }),
  register: (data: object) => api.post('/auth/register/', data),
  logout: (refresh: string) => api.post('/auth/logout/', { refresh }),
  profile: () => api.get('/auth/profile/'),
  updateProfile: (data: object) => api.patch('/auth/profile/', data),
  acceptTerms: () => api.post('/auth/accept-terms/'),
  uploadAvatar: (file: File) => uploadFileDirect('/auth/upload_avatar/', file),
  requestPasswordReset: (email: string) =>
    api.post('/auth/password-reset/', { email }),
  confirmPasswordReset: (data: { email: string; code: string; new_password: string; confirm_password: string }) =>
    api.post('/auth/password-reset/confirm/', data),
  verifyEmail: (token: string) =>
    api.get('/auth/verify-email/', { params: { token } }),
  checkVerification: (email: string, pollingToken?: string) =>
    api.post('/auth/check-verification/', { email, ...(pollingToken ? { polling_token: pollingToken } : {}) }),
  resendVerification: (email: string) =>
    api.post('/auth/resend-verification/', { email }),
  mfaSetup: () => api.post('/auth/mfa/setup/'),
  mfaConfirmSetup: (code: string) => api.post('/auth/mfa/confirm-setup/', { code }),
  mfaVerify: (mfa_token: string, code: string) => api.post('/auth/mfa/verify/', { mfa_token, code }),
  mfaDisable: (code: string, currentPassword: string) => api.post('/auth/mfa/disable/', { code, current_password: currentPassword }),
  staffLogin: (username: string, orgSlug: string, password: string) =>
    api.post('/auth/staff-login/', { username, org_slug: orgSlug, password }),
  changePassword: (currentPassword: string, newPassword: string, confirmPassword?: string) =>
    api.post('/auth/change-password/', { current_password: currentPassword, new_password: newPassword, confirm_password: confirmPassword ?? newPassword }),
  issueOfflineVerifier: (password: string, deviceLabel?: string) =>
    api.post('/auth/offline-verifier/', { password, ...(deviceLabel ? { device_label: deviceLabel } : {}) }),
  getOfflineVerifierStatus: () =>
    api.get('/auth/offline-verifier/status/'),
  revokeOfflineVerifier: () =>
    api.delete('/auth/offline-verifier/'),
}

export const orgApi = {
  list: () => api.get('/tenancy/organisations/'),
  create: (data: object) => api.post('/tenancy/organisations/', data),
  update: (id: string, data: FormData | object) => api.patch(`/tenancy/organisations/${id}/`, data),
  getEmailConfig: (id: string) => api.get(`/tenancy/organisations/${id}/email_config/`),
  saveEmailConfig: (id: string, data: object) => api.patch(`/tenancy/organisations/${id}/email_config/`, data),
  myMembership: (orgId: string) => api.get(`/tenancy/organisations/${orgId}/my_membership/`),
  invite: (orgId: string, data: object) => api.post(`/tenancy/organisations/${orgId}/invite/`, data),
  listInvitations: (orgId: string) => api.get(`/tenancy/organisations/${orgId}/invitations/`),
  cancelInvitation: (orgId: string, invitationId: string) => api.post(`/tenancy/organisations/${orgId}/cancel_invitation/`, { invitation_id: invitationId }),
  acceptInvitation: (token: string) => api.post('/tenancy/organisations/accept_invitation/', { token }),
  rejectInvitation: (token: string) => api.post('/tenancy/organisations/reject_invitation/', { token }),
  previewInvitation: (token: string) => api.get('/tenancy/organisations/preview_invitation/', { params: { token } }),
  myInvitations: () => api.get('/tenancy/organisations/my_invitations/'),
  createSubaccount: (orgId: string, data: object) => api.post(`/tenancy/organisations/${orgId}/create_subaccount/`, data),
  resolveBankAccount: (accountNumber: string, bankCode: string) =>
    api.get('/tenancy/organisations/resolve_bank_account/', { params: { account_number: accountNumber, bank_code: bankCode } }),
  removeLogo: (id: string) => api.post(`/tenancy/organisations/${id}/remove_logo/`),
  removeStamp: (id: string) => api.post(`/tenancy/organisations/${id}/remove_stamp/`),
  uploadLogo: (id: string, file: File) => uploadFileDirect(`/tenancy/organisations/${id}/upload_logo/`, file),
  uploadStamp: (id: string, file: File) => uploadFileDirect(`/tenancy/organisations/${id}/upload_stamp/`, file),
  listEntities: (orgId: string) =>
    api.get(`/tenancy/organisations/${orgId}/entities/`),
  createEntity: (orgId: string, data: { name: string; entity_group_name?: string; country?: string; currency?: string }) =>
    api.post(`/tenancy/organisations/${orgId}/create_entity/`, data),
  reseedCoa: (orgId: string) =>
    api.post(`/tenancy/organisations/${orgId}/reseed_coa/`),
  // Partner consent — org-owner side
  listPartnerRequests: (orgId: string) =>
    api.get(`/tenancy/organisations/${orgId}/partner-requests/`),
  approvePartnerRequest: (orgId: string, reqId: string, permissions?: Partial<Record<string, string>>) =>
    api.post(`/tenancy/organisations/${orgId}/partner-requests/${reqId}/approve/`, permissions ? { permissions } : {}),
  rejectPartnerRequest: (orgId: string, reqId: string, reason?: string) =>
    api.post(`/tenancy/organisations/${orgId}/partner-requests/${reqId}/reject/`, { reason: reason ?? '' }),
  listPartnerAccess: (orgId: string) =>
    api.get(`/tenancy/organisations/${orgId}/partner-access/`),
  revokePartnerAccess: (orgId: string, linkId: string) =>
    api.delete(`/tenancy/organisations/${orgId}/partner-access/${linkId}/`),
  generatePartnerInvite: (orgId: string, partnerEmail: string) =>
    api.post(`/tenancy/organisations/${orgId}/generate-partner-invite/`, { partner_email: partnerEmail }),
}

export const teamApi = {
  members: () => api.get('/tenancy/memberships/'),
  updateMember: (id: string, data: object) => api.patch(`/tenancy/memberships/${id}/`, data),
  deleteMember: (id: string) => api.delete(`/tenancy/memberships/${id}/`),
  setPermissions: (id: string, permissions: { module: string; access_level: string }[]) =>
    api.post(`/tenancy/memberships/${id}/set_permissions/`, { permissions }),
}

export const inventoryApi = {
  products: (params?: object) =>
    // slim=1 → backend sends the lightweight list payload (this build hydrates
    // the edit form from the detail endpoint, so the slim list is safe for it).
    api.get('/inventory/products/', { params: { slim: '1', ...(params ?? {}) } }),
  product: (id: string) => api.get(`/inventory/products/${id}/`),
  /** Modifier groups to ask about when this product is added to a sale. */
  modifierGroupsFor: (productId: string) =>
    api.get('/inventory/modifier-groups/for_product/', { params: { product: productId } }),
  modifierGroups: (params?: object) => api.get('/inventory/modifier-groups/', { params }),
  createModifierGroup: (data: object) => api.post('/inventory/modifier-groups/', data),
  updateModifierGroup: (id: string, data: object) => api.patch(`/inventory/modifier-groups/${id}/`, data),
  deleteModifierGroup: (id: string) => api.delete(`/inventory/modifier-groups/${id}/`),
  createModifierOption: (data: object) => api.post('/inventory/modifier-options/', data),
  updateModifierOption: (id: string, data: object) => api.patch(`/inventory/modifier-options/${id}/`, data),
  deleteModifierOption: (id: string) => api.delete(`/inventory/modifier-options/${id}/`),
  createProduct: (data: object) => api.post('/inventory/products/', data),
  updateProduct: (id: string, data: object) => api.patch(`/inventory/products/${id}/`, data),
  deleteProduct: (id: string) => api.delete(`/inventory/products/${id}/`),
  bulkDeleteProducts: (ids?: string[]) => api.delete('/inventory/products/bulk-delete/', { data: { ids: ids ?? [] } }),
  stock: (params?: object) => api.get('/inventory/stock/', { params }),
  lowStock: (params?: object) => api.get('/inventory/products/low-stock/', { params }),
  valuation: () => api.get('/inventory/products/valuation/'),
  movements: (params?: object) => api.get('/inventory/movements/', { params }),
  categories: () => api.get('/inventory/categories/'),
  warehouses: () => api.get('/inventory/warehouses/'),
  createWarehouse: (data: object) => api.post('/inventory/warehouses/', data),
  updateWarehouse: (id: string, data: object) => api.patch(`/inventory/warehouses/${id}/`, data),
  deleteWarehouse: (id: string) => api.delete(`/inventory/warehouses/${id}/`),
  adjustStock: (data: object) => api.post('/inventory/movements/adjust/', data),
  transferStock: (data: object) => api.post('/inventory/movements/transfer/', data),
  deleteStockItem: (id: string) => api.delete(`/inventory/stock/${id}/`),
  batches: (params?: object) => api.get('/inventory/batches/', { params }),
  createBatch: (data: object) => api.post('/inventory/batches/', data),
  deleteBatch: (id: string) => api.delete(`/inventory/batches/${id}/`),
}

export const salesApi = {
  invoices: (params?: object) => api.get('/sales/invoices/', { params }),
  invoice: (id: string) => api.get(`/sales/invoices/${id}/`),
  create: (data: object) => api.post('/sales/invoices/', data),
  updateInvoice: (id: string, data: object) => api.patch(`/sales/invoices/${id}/`, data),
  editLines: (id: string, data: object) => api.patch(`/sales/invoices/${id}/edit_lines/`, data),
  deleteInvoice: (id: string) => api.delete(`/sales/invoices/${id}/`),
  pay: (id: string, data: object) => api.post(`/sales/invoices/${id}/pay/`, data),
  paySplit: (id: string, tenders: object[]) => api.post(`/sales/invoices/${id}/pay_split/`, { tenders }),
  void: (id: string) => api.post(`/sales/invoices/${id}/void/`),
  processReturn: (invoiceId: string, data: object) =>
    api.post(`/sales/invoices/${invoiceId}/process_return/`, data),
  listReturns: (params?: object) => api.get('/sales/returns/', { params }),
  sendEmail: (invoiceId: string, data: object) =>
    api.post(`/sales/invoices/${invoiceId}/send_email/`, data),
  confirmProforma: (invoiceId: string) =>
    api.post(`/sales/invoices/${invoiceId}/confirm_proforma/`),
  fulfillInvoice: (invoiceId: string) =>
    api.post(`/sales/invoices/${invoiceId}/fulfill/`),
  deleteInvoiceReversed: (invoiceId: string) =>
    api.post(`/sales/invoices/${invoiceId}/delete_invoice/`),
  extendDueDate: (invoiceId: string, data: { new_due_date: string; reason?: string }) =>
    api.post(`/sales/invoices/${invoiceId}/extend_due_date/`, data),
  productHistory: (productId: string, params?: { date_from?: string; date_to?: string }) =>
    api.get('/sales/invoices/product_history/', { params: { product_id: productId, ...params } }),
  warehouseSales: (period?: string) =>
    api.get('/sales/invoices/warehouse_sales/', { params: { period } }),
  ownerAnalytics: (period?: string) =>
    api.get('/sales/invoices/owner_analytics/', { params: { period } }),
}

export const customerApi = {
  list: (params?: object) => api.get('/customers/', { params }),
  get: (id: string) => api.get(`/customers/${id}/`),
  create: (data: object) => api.post('/customers/', data),
  update: (id: string, data: object) => api.patch(`/customers/${id}/`, data),
  delete: (id: string) => api.delete(`/customers/${id}/`),
  statement: (id: string, params?: object) => api.get(`/customers/${id}/statement/`, { params }),
  recordDebit: (id: string, data: object) => api.post(`/customers/${id}/record_debit/`, data),
}

export const expenseApi = {
  list: (params?: object) => api.get('/expenses/', { params }),
  create: (data: object) => api.post('/expenses/', data),
  update: (id: string, data: object) => api.patch(`/expenses/${id}/`, data),
  delete: (id: string) => api.delete(`/expenses/${id}/`),
  categories: () => api.get('/expenses/categories/'),
  // Folders / groups
  groups: (params?: object) => api.get('/expenses/groups/', { params }),
  createGroup: (data: object) => api.post('/expenses/groups/', data),
  updateGroup: (id: string, data: object) => api.patch(`/expenses/groups/${id}/`, data),
  deleteGroup: (id: string) => api.delete(`/expenses/groups/${id}/`),
  groupContents: (id: string) => api.get(`/expenses/groups/${id}/contents/`),
}

export const creditApi = {
  list: (params?: object) => api.get('/credits/', { params }),
  recordPayment: (data: object) => api.post('/credits/record_payment/', data),
  agingReport: () => api.get('/credits/aging_report/'),
}

export const purchaseApi = {
  list: (params?: object) => api.get('/purchases/orders/', { params }),
  create: (data: object) => api.post('/purchases/orders/', data),
  patch: (id: string, data: object) => api.patch(`/purchases/orders/${id}/`, data),
  uploadReceipt: (id: string, file: File) => _multipartPatch(`/purchases/orders/${id}/`, file, 'receipt'),
  delete: (id: string) => api.delete(`/purchases/orders/${id}/`),
  removeReceipt: (id: string) => api.post(`/purchases/orders/${id}/clear_receipt/`),
  receive: (id: string, items: object[]) => api.post(`/purchases/orders/${id}/receive/`, { items }),
  quickReceive: (id: string) => api.post(`/purchases/orders/${id}/quick-receive/`),
  etaAlerts: () => api.get('/purchases/orders/eta-alerts/'),
}

export const supplierApi = {
  list: (params?: object) => api.get('/suppliers/', { params }),
  create: (data: object) => api.post('/suppliers/', data),
  update: (id: string, data: object) => api.patch(`/suppliers/${id}/`, data),
  delete: (id: string) => api.delete(`/suppliers/${id}/`),
}

export const reportApi = {
  // Unified report engine (registry-backed): catalog + dispatch by key.
  catalog: () => api.get('/reports/catalog/'),
  run: (key: string, params?: object) => api.get(`/reports/r/${key}/`, { params }),
  pnl: (params: object) => api.get('/reports/pnl/', { params }),
  sales: (params: object) => api.get('/reports/sales/', { params }),
  topProducts: (params: object) => api.get('/reports/top-products/', { params }),
  topCustomers: (params: object) => api.get('/reports/top-customers/', { params }),
  inventory: (params?: object) => api.get('/reports/inventory/', { params }),
  cashFlow: (params: object) => api.get('/reports/cash-flow/', { params }),
  expenses: (params: object) => api.get('/reports/expenses/', { params }),
  arAging: (params?: object) => api.get('/reports/ar-aging/', { params }),
  apAging: (params?: object) => api.get('/reports/ap-aging/', { params }),
  vatSummary: (params: object) => api.get('/reports/vat-summary/', { params }),
  salesByCustomer: (params?: object) => api.get('/reports/sales-by-customer/', { params }),
  salesByProduct: (params?: object) => api.get('/reports/sales-by-product/', { params }),
  paymentMethods: (params?: object) => api.get('/reports/payment-methods/', { params }),
  customerBalance: (params?: object) => api.get('/reports/customer-balance/', { params }),
  paymentsByCustomer: (params?: object) => api.get('/reports/payments-by-customer/', { params }),
  customerPayments: (params: object) => api.get('/reports/customer-payments/', { params }),
  accountStatement: (params: object) => api.get('/reports/account-statement/', { params }),
  customerDetails: (params?: object) => api.get('/reports/customer-details/', { params }),
  productDetails: (params?: object) => api.get('/reports/product-details/', { params }),
  customerInvoices: (params: object) => api.get('/reports/customer-invoices/', { params }),

  /**
   * Download a report as Excel or PDF.
   * Returns a Blob — callers should pass it to saveBlobFile().
   */
  download: (endpoint: string, params: object) =>
    api.get(endpoint, { params, responseType: 'blob' }),

  /**
   * Export several reports at once (POST /reports/export-bulk/ — see
   * ReportBulkExportView in backend/apps/reports/views.py). `combine: true`
   * returns one .xlsx with a sheet per report; `combine: false` returns a
   * .zip of separate .xlsx files. Returns a Blob for saveBlobFile().
   */
  exportBulkDownload: (body: {
    keys: string[]; period: string; date_from?: string; date_to?: string; combine: boolean
  }) => api.post('/reports/export-bulk/', body, { responseType: 'blob' }),

  /** Same as exportBulkDownload, but emails the file via the org's configured
   * SMTP instead of returning it — pass `email_to`. Returns a normal JSON
   * {message} / {error} response, not a blob. */
  exportBulkEmail: (body: {
    keys: string[]; period: string; date_from?: string; date_to?: string; combine: boolean; email_to: string
  }) => api.post('/reports/export-bulk/', body),
}

export const taxApi = {
  // VAT Classes
  classes: () => api.get('/tax/classes/'),
  createClass: (data: object) => api.post('/tax/classes/', data),
  updateClass: (id: string, data: object) => api.patch(`/tax/classes/${id}/`, data),
  deleteClass: (id: string) => api.delete(`/tax/classes/${id}/`),
  // Tax Configs (income/corporate)
  configs: () => api.get('/tax/configs/'),
  createConfig: (data: object) => api.post('/tax/configs/', data),
  updateConfig: (id: string, data: object) => api.patch(`/tax/configs/${id}/`, data),
  deleteConfig: (id: string) => api.delete(`/tax/configs/${id}/`),
  setBrackets: (configId: string, brackets: object[]) =>
    api.put(`/tax/configs/${configId}/brackets/`, brackets),
  calculateIncomeTax: (data: object) => api.post('/tax/configs/calculate_income_tax/', data),
  vatReport: (data: object) => api.post('/tax/configs/vat_report/', data),
  // WHT certificates
  whtCertificates: (params?: object) => api.get('/tax/wht-certificates/', { params }),
  remitWht: (id: string, data: object) => api.post(`/tax/wht-transactions/${id}/remit/`, data),
  whtCertificatePdf: (id: string) =>
    api.get(`/tax/wht-transactions/${id}/certificate_pdf/`, { responseType: 'blob' }),
  // VAT transactions
  vatTransactions: (params?: object) => api.get('/tax/vat-transactions/', { params }),
  createVatTransaction: (data: object) => api.post('/tax/vat-transactions/', data),
  syncVatFromPeriod: (data: { period_start: string; period_end: string }) =>
    api.post('/tax/vat-transactions/sync_from_period/', data),
  // Tax obligations (compliance calendar)
  obligations: (params?: object) => api.get('/tax/obligations/', { params }),
  createObligation: (data: object) => api.post('/tax/obligations/', data),
  updateObligation: (id: string, data: object) => api.patch(`/tax/obligations/${id}/`, data),
  deleteObligation: (id: string) => api.delete(`/tax/obligations/${id}/`),
  markObligationFiled: (id: string, data: object) => api.post(`/tax/obligations/${id}/mark_filed/`, data),
  markObligationPaid: (id: string, data: object) => api.post(`/tax/obligations/${id}/mark_paid/`, data),
  upcomingObligations: () => api.get('/tax/obligations/upcoming/'),
  generateObligationsNow: () => api.post('/tax/obligations/generate_now/'),
  // Capital allowances
  capitalAllowances: (params?: object) => api.get('/tax/capital-allowances/', { params }),
  createCapitalAllowance: (data: object) => api.post('/tax/capital-allowances/', data),
  updateCapitalAllowance: (id: string, data: object) => api.patch(`/tax/capital-allowances/${id}/`, data),
  deleteCapitalAllowance: (id: string) => api.delete(`/tax/capital-allowances/${id}/`),
  capitalAllowanceSummary: () => api.get('/tax/capital-allowances/summary/'),
  // Deferred tax
  deferredTax: (params?: object) => api.get('/tax/deferred-tax/', { params }),
  createDeferredTax: (data: object) => api.post('/tax/deferred-tax/', data),
  updateDeferredTax: (id: string, data: object) => api.patch(`/tax/deferred-tax/${id}/`, data),
  deleteDeferredTax: (id: string) => api.delete(`/tax/deferred-tax/${id}/`),
  deferredTaxBalanceSheet: () => api.get('/tax/deferred-tax/balance_sheet_impact/'),
  // Transfer pricing
  transferPricing: (params?: object) => api.get('/tax/transfer-pricing/', { params }),
  createTransferPricing: (data: object) => api.post('/tax/transfer-pricing/', data),
  updateTransferPricing: (id: string, data: object) => api.patch(`/tax/transfer-pricing/${id}/`, data),
  deleteTransferPricing: (id: string) => api.delete(`/tax/transfer-pricing/${id}/`),
  tpDisclosureSummary: () => api.get('/tax/transfer-pricing/disclosure_summary/'),
}

export const quoteApi = {
  list: (params?: object) => api.get('/quotes/', { params }),
  create: (data: object) => api.post('/quotes/', data),
  update: (id: string, data: object) => api.patch(`/quotes/${id}/`, data),
  send: (id: string) => api.post(`/quotes/${id}/send/`),
  accept: (id: string) => api.post(`/quotes/${id}/accept/`),
  reject: (id: string) => api.post(`/quotes/${id}/reject/`),
  convert: (id: string) => api.post(`/quotes/${id}/convert/`),
  sendEmail: (id: string, data: object) => api.post(`/quotes/${id}/send_email/`, data),
}

export const billApi = {
  list: (params?: object) => api.get('/bills/', { params }),
  create: (data: object) => api.post('/bills/', data),
  update: (id: string, data: object) => api.put(`/bills/${id}/`, data),
  approve: (id: string) => api.post(`/bills/${id}/approve/`),
  pay: (id: string, data: object) => api.post(`/bills/${id}/pay/`, data),
  void: (id: string) => api.post(`/bills/${id}/void/`),
  folders: (params?: object) => api.get('/bills/folders/', { params }),
  createFolder: (data: object) => api.post('/bills/folders/', data),
  updateFolder: (id: string, data: object) => api.patch(`/bills/folders/${id}/`, data),
  deleteFolder: (id: string) => api.delete(`/bills/folders/${id}/`),
  folderContents: (id: string) => api.get(`/bills/folders/${id}/contents/`),
}

export const invoiceFolderApi = {
  list: (params?: object) => api.get('/sales/folders/', { params }),
  create: (data: object) => api.post('/sales/folders/', data),
  update: (id: string, data: object) => api.patch(`/sales/folders/${id}/`, data),
  delete: (id: string) => api.delete(`/sales/folders/${id}/`),
  contents: (id: string) => api.get(`/sales/folders/${id}/contents/`),
}

export const locationApi = {
  list: (params?: object) => api.get('/sales/locations/', { params }),
  create: (data: object) => api.post('/sales/locations/', data),
  update: (id: string, data: object) => api.patch(`/sales/locations/${id}/`, data),
  delete: (id: string) => api.delete(`/sales/locations/${id}/`),
  salesAnalytics: (period?: string) => api.get('/sales/locations/sales_analytics/', { params: { period } }),
}

export const stockReportApi = {
  availability: (params?: object) => api.get('/inventory/products/stock-availability/', { params }),
  usage: (params?: object) => api.get('/inventory/products/usage-report/', { params }),
  transfers: (params?: object) => api.get('/inventory/products/transfer-report/', { params }),
  stockCard: (params: object) => api.get('/inventory/products/stock-card/', { params }),
}

export const partnerApi = {
  profile: ()                                       => api.get('/tenancy/partner/profile/'),
  updateProfile: (data: object)                     => api.put('/tenancy/partner/profile/', data),
  clients: ()                                       => api.get('/tenancy/partner/clients/'),
  addClient: (data: object)                         => api.post('/tenancy/partner/clients/', data),
  removeClient: (id: string)                        => api.delete(`/tenancy/partner/${id}/clients/`),
  consolidated: ()                                  => api.get('/tenancy/partner/consolidated/'),
  // Consent flow — partner-initiated
  requestAccess: (data: { organisation_id: string; message?: string }) =>
    api.post('/tenancy/partner/request-access/', data),
  listAccessRequests: ()                            => api.get('/tenancy/partner/access-requests/'),
  withdrawRequest: (id: string)                     => api.delete(`/tenancy/partner/${id}/access-requests/`),
  // Client-initiated invite flow
  acceptInvite: (token: string)                     => api.post('/tenancy/partner/accept-invite/', { token }),
  // Commission credit wallet
  commission: ()                                    => api.get('/tenancy/partner/commission/'),
  applyCredit: (data: { subscription_id: string; amount_to_apply: string }) =>
    api.post('/tenancy/partner/commission/apply/', data),
  // Partner invoices
  listInvoices: (params?: object)                   => api.get('/tenancy/partner-invoices/', { params }),
  createInvoice: (data: object)                     => api.post('/tenancy/partner-invoices/', data),
  getInvoice: (id: string)                          => api.get(`/tenancy/partner-invoices/${id}/`),
  updateInvoice: (id: string, data: object)         => api.patch(`/tenancy/partner-invoices/${id}/`, data),
  sendInvoice: (id: string)                         => api.post(`/tenancy/partner-invoices/${id}/send/`),
  markInvoicePaid: (id: string, data: object)       => api.post(`/tenancy/partner-invoices/${id}/mark_paid/`, data),
  voidInvoice: (id: string)                         => api.post(`/tenancy/partner-invoices/${id}/void/`),
  // White-label config (Agency)
  getWhiteLabel: ()                                 => api.get('/tenancy/partner/white-label-mgmt/white-label/'),
  saveWhiteLabel: (data: object)                    => api.put('/tenancy/partner/white-label-mgmt/white-label/', data),
  verifyDomain: ()                                  => api.post('/tenancy/partner/white-label-mgmt/white-label/verify_domain/'),
}

export const accountingApi = {
  // Default a large page size: every caller needs the WHOLE chart (tree rendering,
  // journal-line pickers, type counts). Without it DRF's 25-row default silently
  // truncated the list at the 3xxx accounts, hiding all revenue/expense/COGS.
  accounts: (params?: object) => api.get('/accounting/accounts/', { params: { page_size: 1000, ...params } }),
  accountsSummary: (params?: object) => api.get('/accounting/accounts/summary/', { params }),
  createAccount: (data: object) => api.post('/accounting/accounts/', data),
  updateAccount: (id: string, data: object) => api.patch(`/accounting/accounts/${id}/`, data),
  deleteAccount: (id: string) => api.delete(`/accounting/accounts/${id}/`),
  trialBalance: (params?: object) => api.get('/accounting/accounts/trial_balance/', { params }),
  balanceSheet: (params?: object) => api.get('/accounting/accounts/balance_sheet/', { params }),
  seedCoa: () => api.post('/accounting/accounts/seed/'),
  accountLedger: (id: string, params?: object) => api.get(`/accounting/accounts/${id}/ledger/`, { params }),
  generalLedger: (params?: object) => api.get('/accounting/accounts/general_ledger/', { params }),
  // Account taxonomy + sub-types (COA classification)
  accountTaxonomy: () => api.get('/accounting/accounts/taxonomy/'),
  accountSubTypes: (params?: object) => api.get('/accounting/account-sub-types/', { params }),
  createAccountSubType: (data: object) => api.post('/accounting/account-sub-types/', data),
  updateAccountSubType: (id: string, data: object) => api.patch(`/accounting/account-sub-types/${id}/`, data),
  deleteAccountSubType: (id: string) => api.delete(`/accounting/account-sub-types/${id}/`),
  // Take-On / opening balances
  setOpeningBalances: (data: object) => api.post('/accounting/accounts/opening_balances/', data),
  setAccountOpeningBalance: (id: string, data: object) => api.post(`/accounting/accounts/${id}/set_opening_balance/`, data),
  setSubledgerOpeningBalances: (data: object) => api.post('/accounting/accounts/subledger_opening_balances/', data),
  beginningBalancesSummary: () => api.get('/accounting/beginning-balances/summary/'),
  journal: (params?: object) => api.get('/accounting/journal/', { params }),
  createJournalEntry: (data: object) => api.post('/accounting/journal/', data),
  updateJournalEntry: (id: string, data: object) => api.patch(`/accounting/journal/${id}/`, data),
  deleteJournalEntry: (id: string) => api.delete(`/accounting/journal/${id}/`),
  postJournalEntry: (id: string) => api.post(`/accounting/journal/${id}/post_entry/`),
  reverseJournalEntry: (id: string, data?: object) => api.post(`/accounting/journal/${id}/reverse/`, data ?? {}),
  importJournalEntries: (data: object) => api.post('/accounting/journal/import_entries/', data),
  submitJournalForApproval: (id: string) => api.post(`/accounting/journal/${id}/submit_for_approval/`),
  approveJournalEntry: (id: string, data?: object) => api.post(`/accounting/journal/${id}/approve/`, data ?? {}),
  rejectJournalEntry: (id: string, data?: object) => api.post(`/accounting/journal/${id}/reject/`, data ?? {}),
  signJournalEntry: (id: string, data: FormData | object) => api.post(`/accounting/journal/${id}/sign/`, data),
  assets: () => api.get('/accounting/assets/'),
  createAsset: (data: object) => api.post('/accounting/assets/', data),
  updateAsset: (id: string, data: object) => api.patch(`/accounting/assets/${id}/`, data),
  runDepreciation: (data: object) => api.post('/accounting/assets/run_depreciation/', data),
  postDepreciationBatch: (data: object) => api.post('/accounting/assets/post_depreciation_batch/', data),
  assetTypes: () => api.get('/accounting/asset-types/'),
  createAssetType: (data: object) => api.post('/accounting/asset-types/', data),
  updateAssetType: (id: string, data: object) => api.patch(`/accounting/asset-types/${id}/`, data),
  deleteAssetType: (id: string) => api.delete(`/accounting/asset-types/${id}/`),
  assetReconciliation: () => api.get('/accounting/assets/reconciliation/'),
  disposeAsset: (id: string, data: object) => api.post(`/accounting/assets/${id}/dispose/`, data),
  transferAsset: (id: string, data: object) => api.post(`/accounting/assets/${id}/transfer/`, data),
  revalueAsset: (id: string, data: object) => api.post(`/accounting/assets/${id}/revalue/`, data),
  recordAssetUsage: (id: string, data: object) => api.post(`/accounting/assets/${id}/record_usage/`, data),
  assetRegisterReport: () => api.get('/accounting/assets/register_report/'),
  assetsByCategory: () => api.get('/accounting/assets/by_category/'),
  assetsByLocation: () => api.get('/accounting/assets/by_location/'),
  assetDisposalReport: (params?: string) => api.get(`/accounting/assets/disposal_report/${params ?? ''}`),
  assetTransferReport: (params?: string) => api.get(`/accounting/assets/transfer_report/${params ?? ''}`),
  assetDepreciationSchedule: (id: string, forecast = false) =>
    api.get(`/accounting/assets/${id}/depreciation_schedule/${forecast ? '?forecast=true' : ''}`),
  // Financial Periods
  periods: () => api.get('/accounting/periods/'),
  createPeriod: (data: object) => api.post('/accounting/periods/', data),
  lockPeriod: (id: string, force = false) => api.post(`/accounting/periods/${id}/lock/`, force ? { force: true } : {}),
  unlockPeriod: (id: string, reason: string) => api.post(`/accounting/periods/${id}/unlock/`, { reason }),
  periodCloseChecklist: (id: string) => api.get(`/accounting/periods/${id}/close_checklist/`),
  generateFiscalYear: (data: object) => api.post('/accounting/periods/generate_fiscal_year/', data),
  periodGrants: (id: string) => api.get(`/accounting/periods/${id}/grants/`),
  grantPeriodAccess: (id: string, data: object) => api.post(`/accounting/periods/${id}/grants/`, data),
  revokePeriodGrant: (id: string, grantId: string) => api.post(`/accounting/periods/${id}/revoke_grant/`, { grant_id: grantId }),
  closeYear: (fiscalYear: number) => api.post('/accounting/year-end-close/', { fiscal_year: fiscalYear }),
  // Bank Reconciliation
  reconciliations: () => api.get('/accounting/reconciliations/'),
  createReconciliation: (data: object) => api.post('/accounting/reconciliations/', data),
  markReconciled: (id: string) => api.post(`/accounting/reconciliations/${id}/mark_reconciled/`),
  addReconLine: (id: string, data: object) => api.post(`/accounting/reconciliations/${id}/add_line/`, data),
  updateReconLine: (id: string, data: object) => api.patch(`/accounting/reconciliations/${id}/update_line/`, data),
  importStatement: (id: string, file: File) => _importPost(`/accounting/reconciliations/${id}/import_statement/`, file),
  autoMatch: (id: string) => api.post(`/accounting/reconciliations/${id}/auto_match/`),
  aiReconcile: (id: string) => api.post(`/accounting/reconciliations/${id}/ai_reconcile/`),
  confirmMatch: (id: string, data: { match_id: string; action: 'confirm' | 'reject' }) =>
    api.post(`/accounting/reconciliations/${id}/confirm_match/`, data),
  // GL Health
  glHealth: () => api.get('/accounting/gl-health/'),
  glRetry: (modelType: string, objectId: string) =>
    api.post(`/accounting/gl-health/${modelType}/${objectId}/retry/`),
  glBulkRetry: () => api.post('/accounting/gl-health/retry-all/'),
  postConfirmedGL: (reconId: string) => api.post(`/accounting/reconciliations/${reconId}/post_confirmed_gl/`),
  // Account Mapping
  getAccountMapping: () => api.get('/accounting/account-mapping/'),
  updateAccountMapping: (data: object) => api.put('/accounting/account-mapping/', data),
  getAccountMappingSuggestions: () => api.get('/accounting/account-mapping/suggestions/'),
}

export const payrollApi = {
  employees: (params?: object) => api.get('/payroll/employees/', { params }),
  createEmployee: (data: object) => api.post('/payroll/employees/', data),
  updateEmployee: (id: string, data: object) => api.patch(`/payroll/employees/${id}/`, data),
  deleteEmployee: (id: string) => api.delete(`/payroll/employees/${id}/`),
  runs: (params?: object) => api.get('/payroll/runs/', { params }),
  runPayroll: (data: object) => api.post('/payroll/runs/', data),
  approvePayroll: (id: string) => api.post(`/payroll/runs/${id}/approve/`),
  markPaid: (id: string, data: object) => api.post(`/payroll/runs/${id}/mark_paid/`, data),
  initiateTransfers: (id: string) => api.post(`/payroll/runs/${id}/initiate_transfers/`),
  eligibleApprovers: () => api.get('/payroll/runs/eligible_approvers/'),
  submitForApproval: (id: string, data?: object) => api.post(`/payroll/runs/${id}/submit_for_approval/`, data ?? {}),
  retryFailed: (id: string) => api.post(`/payroll/runs/${id}/retry_failed/`),
  exportBankFile: (id: string) => api.get(`/payroll/runs/${id}/export_bank_file/`, { responseType: 'blob' }),
  pendingApprovals: () => api.get('/payroll/runs/pending_approvals/'),
  resolveAccount: (account_number: string, bank_code: string) =>
    api.post('/payroll/employees/resolve_account/', { account_number, bank_code }),
  // Bonuses
  bonuses: (params?: object) => api.get('/payroll/bonuses/', { params }),
  createBonus: (data: object) => api.post('/payroll/bonuses/', data),
  deleteBonus: (id: string) => api.delete(`/payroll/bonuses/${id}/`),
  // Attendance
  attendance: (params?: object) => api.get('/payroll/attendance/', { params }),
  markAttendance: (data: object) => api.post('/payroll/attendance/', data),
  bulkMarkAttendance: (data: object) => api.post('/payroll/attendance/bulk_mark/', data),
  updateAttendance: (id: string, data: object) => api.patch(`/payroll/attendance/${id}/`, data),
  // Penalties
  penalties: (employeeId: string) =>
    api.get('/payroll/penalties/', { params: { employee: employeeId } }),
  createPenalty: (data: object) => api.post('/payroll/penalties/', data),
  waivePenalty: (id: string) => api.post(`/payroll/penalties/${id}/waive/`),
  deletePenalty: (id: string) => api.delete(`/payroll/penalties/${id}/`),
  // Loans
  loans: (employeeId: string) =>
    api.get('/payroll/loans/', { params: { employee: employeeId } }),
  createLoan: (data: object) => api.post('/payroll/loans/', data),
  cancelLoan: (id: string) => api.post(`/payroll/loans/${id}/cancel/`),
  // Employee documents
  documents: (employeeId: string) =>
    api.get('/payroll/documents/', { params: { employee: employeeId } }),
  uploadDocument: (file: File, fields: { employee: string; name: string; document_type: string }) =>
    _multipartPost('/payroll/documents/', file, 'file', fields),
  deleteDocument: (id: string) => api.delete(`/payroll/documents/${id}/`),
  // Employee tax profiles
  taxProfile: (employeeId: string) =>
    api.get(`/payroll/tax-profiles/by_employee/`, { params: { employee_id: employeeId } }),
  saveTaxProfile: (employeeId: string, data: object) =>
    api.put(`/payroll/tax-profiles/by_employee/`, { ...data, employee_id: employeeId }),
  // ── Statutory & benefit remittances ──────────────────────────────────────
  // Replaces the old paye-remittances tracker. PAYE is now split per State IRS
  // and pension per PFA, so one run produces several obligations.
  remittances: (params?: object) => api.get('/payroll/remittances/', { params }),
  remittanceSummary: () => api.get('/payroll/remittances/summary/'),
  markRemitted: (id: string, data: object) =>
    api.post(`/payroll/remittances/${id}/mark_remitted/`, data),
  remittanceSchedule: (params: { type: string; year?: number; month?: number }) =>
    api.get('/payroll/remittances/schedule/', { params }),

  // ── Tax authorities (State IRS registry) ─────────────────────────────────
  taxAuthorities: () => api.get('/payroll/tax-authorities/'),
  updateTaxAuthority: (id: string, data: object) =>
    api.patch(`/payroll/tax-authorities/${id}/`, data),

  // ── Compensation history (effective-dated pay) ───────────────────────────
  compensation: (employeeId: string) =>
    api.get('/payroll/compensation/', { params: { employee: employeeId } }),
  createCompensation: (data: object) => api.post('/payroll/compensation/', data),

  // ── Arrears / back-pay ───────────────────────────────────────────────────
  adjustments: (params?: object) => api.get('/payroll/adjustments/', { params }),
  createAdjustment: (data: object) => api.post('/payroll/adjustments/', data),
  cancelAdjustment: (id: string) => api.post(`/payroll/adjustments/${id}/cancel/`),

  // ── Org chart & portal access ────────────────────────────────────────────
  orgChart: () => api.get('/payroll/employees/org_chart/'),
  invitePortal: (id: string) => api.post(`/payroll/employees/${id}/invite_portal/`),
  revokePortal: (id: string) => api.post(`/payroll/employees/${id}/revoke_portal/`),

  // ── Payroll run extras ───────────────────────────────────────────────────
  recalculateRun: (id: string) => api.post(`/payroll/runs/${id}/recalculate/`),
  sendPayslips: (id: string, data: object) =>
    api.post(`/payroll/runs/${id}/send_payslips/`, data),
  payslipDeliveries: (id: string) => api.get(`/payroll/runs/${id}/deliveries/`),

  // ── Leave ────────────────────────────────────────────────────────────────
  leaveTypes: () => api.get('/payroll/leave-types/'),
  createLeaveType: (data: object) => api.post('/payroll/leave-types/', data),
  updateLeaveType: (id: string, data: object) => api.patch(`/payroll/leave-types/${id}/`, data),
  deleteLeaveType: (id: string) => api.delete(`/payroll/leave-types/${id}/`),
  leaveBalances: (params?: object) => api.get('/payroll/leave-balances/', { params }),
  accrueLeave: (data?: object) => api.post('/payroll/leave-balances/accrue/', data ?? {}),
  leaveRequests: (params?: object) => api.get('/payroll/leave-requests/', { params }),
  createLeaveRequest: (data: object) => api.post('/payroll/leave-requests/', data),
  approveLeave: (id: string, data?: object) =>
    api.post(`/payroll/leave-requests/${id}/approve/`, data ?? {}),
  rejectLeave: (id: string, data?: object) =>
    api.post(`/payroll/leave-requests/${id}/reject/`, data ?? {}),
  cancelLeave: (id: string) => api.post(`/payroll/leave-requests/${id}/cancel/`),
  pendingLeaveCount: () => api.get('/payroll/leave-requests/pending_count/'),

  // ── Benefits ─────────────────────────────────────────────────────────────
  benefitPlans: () => api.get('/payroll/benefit-plans/'),
  createBenefitPlan: (data: object) => api.post('/payroll/benefit-plans/', data),
  updateBenefitPlan: (id: string, data: object) => api.patch(`/payroll/benefit-plans/${id}/`, data),
  deleteBenefitPlan: (id: string) => api.delete(`/payroll/benefit-plans/${id}/`),
  employeeBenefits: (params?: object) => api.get('/payroll/employee-benefits/', { params }),
  enrolBenefit: (data: object) => api.post('/payroll/employee-benefits/', data),
  updateEmployeeBenefit: (id: string, data: object) =>
    api.patch(`/payroll/employee-benefits/${id}/`, data),
  removeEmployeeBenefit: (id: string) => api.delete(`/payroll/employee-benefits/${id}/`),

  // ── Salary advances (earned wage access) ─────────────────────────────────
  advances: (params?: object) => api.get('/payroll/advances/', { params }),
  advanceEligibility: (employeeId: string) =>
    api.get(`/payroll/advances/eligibility/${employeeId}/`),
  createAdvance: (data: object) => api.post('/payroll/advances/', data),
  approveAdvance: (id: string, data?: object) =>
    api.post(`/payroll/advances/${id}/approve/`, data ?? {}),
  rejectAdvance: (id: string, data?: object) =>
    api.post(`/payroll/advances/${id}/reject/`, data ?? {}),
  advancePolicy: () => api.get('/payroll/advance-policy/current/'),
  saveAdvancePolicy: (data: object) => api.patch('/payroll/advance-policy/current/', data),

  // ── Org-level payroll settings ───────────────────────────────────────────
  settings: () => api.get('/payroll/settings/current/'),
  saveSettings: (data: object) => api.patch('/payroll/settings/current/', data),
}

/**
 * Employee self-service portal.
 *
 * Every endpoint resolves the caller's own Employee record server-side, so no
 * employee id is ever sent from the client.
 */
export const essApi = {
  summary: () => api.get('/me/summary/'),
  profile: () => api.get('/me/profile/'),
  updateProfile: (data: object) => api.patch('/me/profile/', data),
  payslips: () => api.get('/me/payslips/'),
  leaveBalances: (year?: number) => api.get('/me/leave-balances/', { params: { year } }),
  leaveTypes: () => api.get('/me/leave-types/'),
  leaveRequests: () => api.get('/me/leave-requests/'),
  createLeaveRequest: (data: object) => api.post('/me/leave-requests/', data),
  cancelLeaveRequest: (id: string) => api.post(`/me/leave-requests/${id}/cancel/`),
  documents: () => api.get('/me/documents/'),
  loans: () => api.get('/me/loans/'),
  benefits: () => api.get('/me/benefits/'),
  attendance: (year?: number, month?: number) =>
    api.get('/me/attendance/', { params: { year, month } }),
  advances: () => api.get('/me/advances/'),
  advanceEligibility: () => api.get('/me/advances/eligibility/'),
  requestAdvance: (data: object) => api.post('/me/advances/', data),
}

export const budgetApi = {
  list: () => api.get('/budgets/'),
  create: (data: object) => api.post('/budgets/', data),
  update: (id: string, data: object) => api.patch(`/budgets/${id}/`, data),
  variance: (id: string) => api.get(`/budgets/${id}/variance/`),
  addLine: (id: string, data: object) => api.post(`/budgets/${id}/add_line/`, data),
}

export const recurringApi = {
  list: () => api.get('/sales/recurring/'),
  create: (data: object) => api.post('/sales/recurring/', data),
  update: (id: string, data: object) => api.patch(`/sales/recurring/${id}/`, data),
  delete: (id: string) => api.delete(`/sales/recurring/${id}/`),
  generateNow: (id: string) => api.post(`/sales/recurring/${id}/generate_now/`),
}

export const settlementApi = {
  batches: (params?: object) => api.get('/payments/settlement-batches/', { params }),
  /** Imports the terminal export AND matches it in one call.
   *  Posted as raw text, not FormData: the desktop build routes through Tauri,
   *  whose IPC layer turns FormData into form-urlencoded and the file never
   *  arrives. The backend accepts either shape. */
  upload: (csv: string, filename = '') =>
    api.post('/payments/settlement-batches/upload/', csv, {
      headers: { 'Content-Type': 'text/csv', ...(filename ? { 'X-File-Name': filename } : {}) },
      transformRequest: [(d) => d],   // keep the string as-is
    }),
  rematch: (id: string) => api.post(`/payments/settlement-batches/${id}/rematch/`),
  lines: (params?: object) => api.get('/payments/settlements/', { params }),
  summary: () => api.get('/payments/settlements/summary/'),
  candidates: () => api.get('/payments/settlements/candidates/'),
  assign: (id: string, payment: string, note = '') =>
    api.post(`/payments/settlements/${id}/assign/`, { payment, note }),
  otherIncome: (id: string, note = '') =>
    api.post(`/payments/settlements/${id}/other_income/`, { note }),
  ignore: (id: string, note = '') => api.post(`/payments/settlements/${id}/ignore/`, { note }),
  unmatch: (id: string) => api.post(`/payments/settlements/${id}/unmatch/`),
}

export const storefrontApi = {
  /** The org's shop settings — created on first call so the page always has one. */
  mine: () => api.get('/storefront/settings/mine/'),
  update: (id: string, data: object) => api.patch(`/storefront/settings/${id}/`, data),
  orders: (params?: object) => api.get('/storefront/orders/', { params }),
  accept: (id: string) => api.post(`/storefront/orders/${id}/accept/`),
  setStatus: (id: string, status: string) =>
    api.post(`/storefront/orders/${id}/set_status/`, { status }),
}

export const tillApi = {
  sessions: (params?: object) => api.get('/pos/till-sessions/', { params }),
  /** The signed-in cashier's open till + live expected figures (never the count). */
  current: () => api.get('/pos/till-sessions/current/'),
  open: (data: object) => api.post('/pos/till-sessions/open/', data),
  close: (id: string, data: object) => api.post(`/pos/till-sessions/${id}/close/`, data),
  zReport: (id: string) => api.get(`/pos/till-sessions/${id}/z_report/`),
}

export const paymentGatewayApi = {
  configs: () => api.get('/payments/gateways/'),
  createConfig: (data: object) => api.post('/payments/gateways/', data),
  updateConfig: (id: string, data: object) => api.patch(`/payments/gateways/${id}/`, data),
  createLink: (invoiceId: string) => api.post('/payments/links/create_link/', { invoice_id: invoiceId }),
  links: (params?: object) => api.get('/payments/links/', { params }),

  /** What this merchant can currently collect with (card / one-time account / transfer). */
  options: () => api.get('/payments/options/'),

  // Merchant's own bank accounts — for customers who just transfer directly.
  bankAccounts: () => api.get('/payments/bank-accounts/'),
  createBankAccount: (data: object) => api.post('/payments/bank-accounts/', data),
  updateBankAccount: (id: string, data: object) => api.patch(`/payments/bank-accounts/${id}/`, data),
  deleteBankAccount: (id: string) => api.delete(`/payments/bank-accounts/${id}/`),

  // One-time account numbers, confirmed automatically by the provider.
  issueVirtualAccount: (invoiceId: string) =>
    api.post('/payments/virtual-accounts/issue/', { invoice_id: invoiceId }),
  virtualAccountStatus: (id: string) => api.get(`/payments/virtual-accounts/${id}/status/`),

  // Transfers into the merchant's own account, confirmed by a person.
  transferClaims: (params?: object) => api.get('/payments/transfer-claims/', { params }),
  claimTransfer: (data: object) => api.post('/payments/transfer-claims/', data),
  confirmTransfer: (id: string, note = '') =>
    api.post(`/payments/transfer-claims/${id}/confirm/`, { note }),
  rejectTransfer: (id: string, note = '') =>
    api.post(`/payments/transfer-claims/${id}/reject/`, { note }),
}

export const exciseApi = {
  list: () => api.get('/tax/excise/'),
  create: (data: object) => api.post('/tax/excise/', data),
  update: (id: string, data: object) => api.patch(`/tax/excise/${id}/`, data),
  delete: (id: string) => api.delete(`/tax/excise/${id}/`),
}

export const whtApi = {
  rates: () => api.get('/tax/wht-rates/'),
  createRate: (data: object) => api.post('/tax/wht-rates/', data),
  updateRate: (id: string, data: object) => api.patch(`/tax/wht-rates/${id}/`, data),
  deleteRate: (id: string) => api.delete(`/tax/wht-rates/${id}/`),
  transactions: (params?: object) => api.get('/tax/wht-transactions/', { params }),
  createTransaction: (data: object) => api.post('/tax/wht-transactions/', data),
  deleteTransaction: (id: string) => api.delete(`/tax/wht-transactions/${id}/`),
}

export const auditLogApi = {
  list: (params?: object) => api.get('/audit-log/', { params }),
}

export const platformAdminApi = {
  stats: () => api.get('/platform/stats/'),
  users: () => api.get('/platform/users/'),
  setUserActive: (id: string, isActive: boolean) => api.patch(`/platform/users/${id}/`, { is_active: isActive }),
  // Cross-org support inbox (superuser only)
  tickets: (params?: object) => api.get('/platform/tickets/', { params }),
  ticketReply: (id: string, body: string) => api.post(`/platform/tickets/${id}/reply/`, { body }),
  ticketStatus: (id: string, status: string) => api.post(`/platform/tickets/${id}/set_status/`, { status }),
  ticketAssign: (id: string, userId?: string) => api.post(`/platform/tickets/${id}/assign/`, userId ? { user_id: userId } : {}),
}

export const subscriptionApi = {
  plans: () => api.get('/subscriptions/plans/'),
  current: () => api.get('/subscriptions/current/'),
  payments: () => api.get('/subscriptions/payments/'),
  initiatePayment: (planId: string) => api.post('/subscriptions/initiate-payment/', { plan_id: planId }),
  verifyPayment: (reference: string) => api.post('/subscriptions/verify-payment/', { reference }),
  cancel: () => api.post('/subscriptions/cancel/'),
  recommendPlan: (answers: Record<string, string>) => api.post('/subscriptions/recommend-plan/', { answers }),
  checkPayment: (reference: string) => api.get('/subscriptions/check-payment/', { params: { reference } }),
  startTrial: (planId: string, orgId?: string) => api.post('/subscriptions/start-trial/', { plan_id: planId, ...(orgId ? { org_id: orgId } : {}) }),
  downgradeFree: () => api.post('/subscriptions/downgrade-to-free/'),
}

export const aiApi = {
  status: () => api.get('/ai/status/'),
  chat: (message: string) => api.post('/ai/chat/', { message }),
  support: (message: string) => api.post('/ai/support/', { message }),
}

// ── FIRS e-invoicing API ───────────────────────────────────────────────────────
// All routes live under /einvoicing/.
// Credentials (app_api_key) are write-only — the server never returns them;
// use has_api_key to check whether a key has been stored.
export const einvoicingApi = {
  /** GET /einvoicing/config/ — returns (or auto-creates) the org's FirsConfig. */
  getConfig: () => api.get('/einvoicing/config/'),

  /** PATCH /einvoicing/config/ — partial update; owner/admin only. */
  updateConfig: (data: Record<string, unknown>) => api.patch('/einvoicing/config/', data),

  /**
   * POST /einvoicing/config/test_connection/
   * Calls the DigiTax /resources endpoint and updates last_test_at/ok.
   * Returns { ok, tested_at, message }.
   */
  testConnection: () => api.post('/einvoicing/config/test_connection/'),

  /** GET /einvoicing/submissions/ — paginated audit log. Supports ?status ?invoice ?kind filters. */
  submissions: (params?: Record<string, unknown>) =>
    api.get('/einvoicing/submissions/', { params }),

  /** GET /einvoicing/submissions/<id>/ — full detail including payload_json. */
  submissionDetail: (id: string) => api.get(`/einvoicing/submissions/${id}/`),

  /** GET /einvoicing/stats/ — enrollment flag + counts by status. */
  stats: () => api.get('/einvoicing/stats/'),

  /**
   * POST /einvoicing/submit/<invoice_id>/
   * Owner/admin manual re-submit for a failed or skipped invoice.
   */
  manualSubmit: (invoiceId: string) => api.post(`/einvoicing/submit/${invoiceId}/`),

  // ── Phase 7: Sandbox certification ────────────────────────────────────────

  /**
   * GET /einvoicing/sandbox/progress/
   * Returns pass_count, fail_count and recent SandboxTestRun records.
   */
  sandboxProgress: () => api.get('/einvoicing/sandbox/progress/'),

  /**
   * POST /einvoicing/sandbox/run/
   * Triggers an async certification batch. Owner/admin only.
   * Body: { mode: 'pass' | 'fail', count?: number }
   */
  sandboxRun: (mode: 'pass' | 'fail', count = 50) =>
    api.post('/einvoicing/sandbox/run/', { mode, count }),

  /**
   * GET /einvoicing/go_live_checklist/
   * Returns the structured pre-production readiness checklist.
   */
  goLiveChecklist: () => api.get('/einvoicing/go_live_checklist/'),
}

// Tauri's HTTP plugin re-encodes FormData as application/x-www-form-urlencoded
// when proxying through Rust/reqwest. Build the multipart body manually as raw
// bytes so the plugin passes it through unchanged, with the boundary intact.
async function _buildMultipartForm(
  file: File,
  fileFieldName = 'file',
  textFields: Record<string, string> = {},
  fileMimeType?: string,
): Promise<{ body: Uint8Array; contentType: string }> {
  const boundary = `----AudityBoundary${Date.now()}`
  const enc = new TextEncoder()
  const fileBytes = new Uint8Array(await file.arrayBuffer())
  const mime = fileMimeType ?? (file.type || 'application/octet-stream')

  const parts: Uint8Array[] = []
  for (const [name, value] of Object.entries(textFields)) {
    parts.push(enc.encode(`--${boundary}\r\nContent-Disposition: form-data; name="${name}"\r\n\r\n${value}\r\n`))
  }
  parts.push(enc.encode(`--${boundary}\r\nContent-Disposition: form-data; name="${fileFieldName}"; filename="${file.name}"\r\nContent-Type: ${mime}\r\n\r\n`))
  parts.push(fileBytes)
  parts.push(enc.encode(`\r\n--${boundary}--\r\n`))

  const totalLength = parts.reduce((acc, p) => acc + p.byteLength, 0)
  const body = new Uint8Array(totalLength)
  let offset = 0
  for (const p of parts) { body.set(p, offset); offset += p.byteLength }
  return { body, contentType: `multipart/form-data; boundary=${boundary}` }
}

async function _importPost(url: string, file: File, mapping?: Record<string, string>) {
  const extra: Record<string, string> = (mapping && Object.keys(mapping).length > 0)
    ? { column_mapping: JSON.stringify(mapping) }
    : {}
  const { body, contentType } = await _buildMultipartForm(file, 'file', extra, 'text/csv')
  return api.post(url, body, {
    headers: { 'Content-Type': contentType },
    transformRequest: [(d: unknown) => d], // prevent Axios re-serialising the Uint8Array
  })
}

async function _multipartPost(url: string, file: File, fileFieldName: string, textFields?: Record<string, string>) {
  const { body, contentType } = await _buildMultipartForm(file, fileFieldName, textFields)
  return api.post(url, body, {
    headers: { 'Content-Type': contentType },
    transformRequest: [(d: unknown) => d],
  })
}

async function _multipartPatch(url: string, file: File, fileFieldName: string, textFields?: Record<string, string>) {
  const { body, contentType } = await _buildMultipartForm(file, fileFieldName, textFields)
  return api.patch(url, body, {
    headers: { 'Content-Type': contentType },
    transformRequest: [(d: unknown) => d],
  })
}

export const importApi = {
  products: (file: File, mapping?: Record<string, string>) => _importPost('/import/products/', file, mapping),
  customers: (file: File) => _importPost('/import/customers/', file),
  accounts: (file: File) => _importPost('/import/accounts/', file),
  // Employee bulk import — same shape as customers/accounts (no AI column
  // mapping needed for this one), see ImportEmployeesView on the backend.
  employees: (file: File) => _importPost('/import/employees/', file),
  /** POST /import/suggest-mapping/ — AI column name mapper */
  suggestMapping: (entity: string, headers: string[]) =>
    api.post('/import/suggest-mapping/', { entity, headers }),
  /** GET /import/template/<entity>/ — download CSV template */
  templateUrl: (entity: 'products' | 'customers' | 'accounts' | 'employees') =>
    `/import/template/${entity}/`,
}

// ─── Help Desk / Tickets ─────────────────────────────────────────────────────
export const helpdeskApi = {
  tickets: (params?: object) => api.get('/helpdesk/tickets/', { params }),
  getTicket: (id: string) => api.get(`/helpdesk/tickets/${id}/`),
  createTicket: (data: object) => api.post('/helpdesk/tickets/', data),
  addComment: (id: string, body: string) => api.post(`/helpdesk/tickets/${id}/comment/`, { body }),
  setStatus: (id: string, status: string) => api.post(`/helpdesk/tickets/${id}/set_status/`, { status }),
}

// ─── Hospitality POS (tables, orders, KOT) ───────────────────────────────────
export const posApi = {
  tables: (params?: object) => api.get('/pos/tables/', { params }),
  createTable: (data: object) => api.post('/pos/tables/', data),
  updateTable: (id: string, data: object) => api.patch(`/pos/tables/${id}/`, data),
  deleteTable: (id: string) => api.delete(`/pos/tables/${id}/`),
  orders: (params?: object) => api.get('/pos/orders/', { params }),
  getOrder: (id: string) => api.get(`/pos/orders/${id}/`),
  createOrder: (data: object) => api.post('/pos/orders/', data),
  addItems: (id: string, items: object[]) => api.post(`/pos/orders/${id}/add_items/`, { items }),
  setOrderStatus: (id: string, status: string) => api.post(`/pos/orders/${id}/set_status/`, { status }),
  generateKot: (id: string, section?: string) => api.post(`/pos/orders/${id}/generate_kot/`, { section }),
  splitBill: (id: string, data: object) => api.post(`/pos/orders/${id}/split_bill/`, data),
  finalizeOrder: (id: string, tenders: object[]) => api.post(`/pos/orders/${id}/finalize/`, { tenders }),
  kots: (params?: object) => api.get('/pos/kots/', { params }),
  setKotStatus: (id: string, status: string) => api.post(`/pos/kots/${id}/set_status/`, { status }),
}

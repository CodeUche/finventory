/**
 * useDataRefresh — re-runs a load function whenever any offline mutation completes
 * (or is applied optimistically).
 *
 * Usage — add one line to any page that has a `load` function:
 *
 *   useDataRefresh(load)
 *
 * The hook uses a ref to track the latest function reference, so it's safe to pass
 * a non-memoised function without causing infinite re-renders.
 *
 * Debounced on purpose: a page's own mutation handler typically calls load()
 * itself right after a write (often via bypassNextGets() for a guaranteed-fresh
 * read), and this hook's 'audity:data-changed' listener fires for the SAME
 * write a moment later — two independent load() calls in flight at once, with
 * no guarantee the later-dispatched one resolves last. On a fast, consistent
 * connection the ordering usually works out, but a slower or more variable
 * transport (confirmed live over Tauri's IPC-routed HTTP layer) can let the
 * second call resolve behind the first and overwrite fresh data with stale —
 * a freshly created record then needs a manual refresh to appear. Debouncing
 * this hook's own trigger lets the page's explicit, immediate call settle
 * first in the common case, and also coalesces bursts of the event (e.g. a
 * bulk import firing many mutations) into one trailing reload instead of a
 * pile of redundant ones.
 */

import { useEffect, useRef } from 'react'

const DEFAULT_DEBOUNCE_MS = 400

export function useDataRefresh(fn: () => void, debounceMs = DEFAULT_DEBOUNCE_MS): void {
  const fnRef = useRef(fn)
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Always keep the ref pointing at the latest function
  useEffect(() => {
    fnRef.current = fn
  })

  useEffect(() => {
    const handler = () => {
      if (timeoutRef.current) clearTimeout(timeoutRef.current)
      timeoutRef.current = setTimeout(() => {
        timeoutRef.current = null
        fnRef.current()
      }, debounceMs)
    }
    window.addEventListener('audity:data-changed', handler)
    return () => {
      window.removeEventListener('audity:data-changed', handler)
      if (timeoutRef.current) clearTimeout(timeoutRef.current)
    }
  }, [debounceMs])
}

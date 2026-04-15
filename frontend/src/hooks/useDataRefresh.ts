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
 */

import { useEffect, useRef } from 'react'

export function useDataRefresh(fn: () => void): void {
  const fnRef = useRef(fn)

  // Always keep the ref pointing at the latest function
  useEffect(() => {
    fnRef.current = fn
  })

  useEffect(() => {
    const handler = () => fnRef.current()
    window.addEventListener('audity:data-changed', handler)
    return () => window.removeEventListener('audity:data-changed', handler)
  }, [])
}

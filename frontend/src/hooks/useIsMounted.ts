import { useEffect, useRef } from 'react'

/**
 * Ref that is true while the component is on screen. A page's load error toast checks it,
 * so a slow request started on one page cannot pop its error up on another page the user
 * has since moved to.
 */
export function useIsMounted() {
  const mounted = useRef(true)
  useEffect(() => {
    mounted.current = true
    return () => { mounted.current = false }
  }, [])
  return mounted
}

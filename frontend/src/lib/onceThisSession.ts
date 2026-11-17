/**
 * "Tell the user once per browser session" guard.
 *
 * Returns true the first time a key is seen in this session, false afterwards. It remembers in
 * sessionStorage, so a page reload (which restarts the notifications poll) does not repeat a
 * message the user already saw. If storage is blocked it falls back to memory for the page's life.
 */
const memory = new Set<string>()

export function onceThisSession(key: string): boolean {
  const full = `audity-once:${key}`
  try {
    if (sessionStorage.getItem(full)) return false
    sessionStorage.setItem(full, '1')
    memory.add(full)
    return true
  } catch {
    if (memory.has(full)) return false
    memory.add(full)
    return true
  }
}

/** For tests. */
export function _forgetOnceKeys(): void {
  memory.clear()
  try {
    Object.keys(sessionStorage).filter((k) => k.startsWith('audity-once:')).forEach((k) => sessionStorage.removeItem(k))
  } catch { /* storage blocked: nothing to forget */ }
}

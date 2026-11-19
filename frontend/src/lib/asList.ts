/**
 * Turn whatever an API call (or the offline copy of it) handed back into a plain list.
 * Accepts a bare list, a paged answer ({ results: [...] }) or anything else
 * (null, an object, a string); the last one gives an empty list instead of a crash.
 * Offline with nothing saved, the app answers with { results: [] } even for
 * endpoints that normally return a bare list, so every list page must tolerate both.
 */
export function asList<T>(data: unknown): T[] {
  if (Array.isArray(data)) return data as T[]
  if (data && typeof data === 'object') {
    const results = (data as { results?: unknown }).results
    if (Array.isArray(results)) return results as T[]
  }
  return []
}

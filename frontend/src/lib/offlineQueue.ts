/**
 * Offline mutation queue.
 *
 * Stores failed API mutations (POST/PUT/PATCH/DELETE) in localStorage while the
 * device is offline, then replays them in order when connectivity is restored.
 *
 * Each queue item is serialisable — all request data is stored as plain JSON.
 */

const STORAGE_KEY = 'finventory_offline_queue'

export interface QueuedRequest {
  id: string
  method: string
  url: string
  data?: unknown
  timestamp: number
  /** Human-readable label shown in the sync toast (derived from method + url) */
  label: string
}

function load(): QueuedRequest[] {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) ?? '[]')
  } catch {
    return []
  }
}

function save(queue: QueuedRequest[]) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(queue))
}

export const offlineQueue = {
  enqueue(req: Omit<QueuedRequest, 'id' | 'timestamp' | 'label'>) {
    const queue = load()
    const label = `${req.method.toUpperCase()} ${req.url.split('?')[0]}`
    queue.push({ ...req, id: crypto.randomUUID(), timestamp: Date.now(), label })
    save(queue)
  },

  peek(): QueuedRequest[] {
    return load()
  },

  clear() {
    localStorage.removeItem(STORAGE_KEY)
  },

  /** Replay all queued requests. Returns counts of succeeded / failed. */
  async flush(): Promise<{ succeeded: number; failed: number }> {
    const queue = load()
    if (queue.length === 0) return { succeeded: 0, failed: 0 }

    // Clear immediately — if re-queueing happens during flush it would create dupes
    offlineQueue.clear()

    let succeeded = 0
    let failed = 0

    // Import api lazily to avoid circular-dependency at module load time
    const { api } = await import('@/services/api')

    for (const item of queue) {
      try {
        await api({
          method: item.method,
          url: item.url,
          data: item.data,
          // Flag so the request interceptor won't re-queue this retry
          headers: { 'X-Offline-Retry': '1' },
        })
        succeeded++
      } catch {
        failed++
      }
    }

    return { succeeded, failed }
  },
}

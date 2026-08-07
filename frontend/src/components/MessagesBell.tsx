/**
 * TopBar messaging entry point — unread badge + slide-over quick-reply panel.
 *
 * Modeled on NotificationBell.tsx's open/close + outside-click pattern.
 * Polls /messaging/unread_count/ every 20-30s (global badge cadence per the
 * Track B spec — mirrors the payroll pending_approvals/pending_count
 * badge-polling convention: plain interval polling, no WebSockets).
 */

import { useEffect, useRef, useState, useCallback } from 'react'
import { MessageSquare } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { messagingApi, type Conversation } from '@/services/messagingApi'
import { useAuthStore } from '@/store/authStore'
import { cn } from '@/lib/utils'

const UNREAD_POLL_MS = 25_000
const LIST_POLL_MS = 25_000

export default function MessagesBell() {
  const [open, setOpen] = useState(false)
  const [unreadCount, setUnreadCount] = useState(0)
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [loading, setLoading] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const navigate = useNavigate()
  const user = useAuthStore((s) => s.user)

  const refreshUnread = useCallback(async () => {
    try {
      const { data } = await messagingApi.unreadCount()
      setUnreadCount(data.unread_count ?? 0)
    } catch {
      /* silent — badge just won't update this cycle */
    }
  }, [])

  const refreshList = useCallback(async () => {
    setLoading(true)
    try {
      const { data } = await messagingApi.conversations()
      const list = Array.isArray(data) ? data : data.results ?? []
      setConversations(list.slice(0, 5))
    } catch {
      /* silent */
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    refreshUnread()
    const id = setInterval(refreshUnread, UNREAD_POLL_MS)
    return () => clearInterval(id)
  }, [refreshUnread])

  useEffect(() => {
    if (!open) return
    refreshList()
    const id = setInterval(refreshList, LIST_POLL_MS)
    return () => clearInterval(id)
  }, [open, refreshList])

  useEffect(() => {
    if (!open) return
    const onPointerDown = (e: PointerEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('pointerdown', onPointerDown, true)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('pointerdown', onPointerDown, true)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  const go = (path: string) => { setOpen(false); navigate(path) }

  const isCrossOrgThread = (conv: Conversation) => {
    // A conversation is "with the accountant/client" if one of the other
    // participants is not the logged-in user AND the caller reached this org
    // via a partner (accountant) membership — surfaced via managing_firm_name
    // on organisation, or the caller's own has_partner_profile flag combined
    // with participants outside the caller's normal team. We keep this
    // simple and visual-only: any conversation whose OTHER participant email
    // domain differs is flagged — but the reliable signal is participant
    // role, so check role='partner_contact' among participants.
    return conv.participants.some((p) => p.role === 'partner_contact')
  }

  return (
    <div ref={ref} className="relative">
      <button
        aria-label="Messages"
        title="Messages"
        onClick={() => setOpen((v) => !v)}
        className={cn('btn-ghost relative p-2 text-slate-300 hover:text-white', open && 'bg-surface-700')}
      >
        <MessageSquare size={18} />
        {unreadCount > 0 && (
          <span className="absolute top-1 right-1 min-w-[16px] h-4 px-0.5 bg-red-500 rounded-full text-[10px] font-bold text-always-white flex items-center justify-center leading-none">
            {unreadCount > 99 ? '99+' : unreadCount}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 top-full mt-2 w-80 bg-surface-800 border border-surface-700 rounded-2xl shadow-2xl z-[200] overflow-hidden">
          <div className="flex items-center justify-between px-4 py-3 border-b border-surface-700">
            <span className="text-sm font-semibold text-white">
              Messages {unreadCount > 0 && <span className="text-brand-400">({unreadCount})</span>}
            </span>
            <button onClick={() => go('/messages')} className="text-xs text-slate-500 hover:text-slate-300 transition-colors">
              Open inbox
            </button>
          </div>

          <div className="max-h-[420px] overflow-y-auto">
            {!loading && conversations.length === 0 ? (
              <div className="py-8 text-center">
                <MessageSquare size={24} className="mx-auto mb-2 text-slate-600" />
                <p className="text-sm text-slate-500">No conversations yet</p>
              </div>
            ) : (
              conversations.map((conv) => {
                const crossOrg = isCrossOrgThread(conv)
                const other = conv.participants.find((p) => p.user !== user?.id)
                return (
                  <button
                    key={conv.id}
                    onClick={() => go(`/messages?c=${conv.id}`)}
                    className="w-full flex items-start gap-3 px-4 py-3 border-b border-surface-700/60 hover:bg-surface-700/30 transition-colors text-left"
                  >
                    <div className="w-7 h-7 rounded-lg bg-sky-500/10 flex items-center justify-center shrink-0 mt-0.5">
                      <MessageSquare size={13} className="text-sky-400" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-1.5">
                        <p className="text-xs font-medium text-white truncate">
                          {other?.user_email ?? 'Conversation'}
                        </p>
                        {crossOrg && (
                          <span className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-400 shrink-0 uppercase tracking-wide">
                            CLIENT
                          </span>
                        )}
                      </div>
                      <p className="text-xs text-slate-500 truncate">
                        {conv.last_message_preview || 'No messages yet'}
                      </p>
                    </div>
                    {conv.unread_count > 0 && (
                      <span className="shrink-0 min-w-[16px] h-4 px-1 bg-red-500 rounded-full text-[10px] font-bold text-white flex items-center justify-center leading-none mt-0.5">
                        {conv.unread_count}
                      </span>
                    )}
                  </button>
                )
              })
            )}
          </div>
        </div>
      )}
    </div>
  )
}

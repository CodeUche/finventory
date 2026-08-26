/**
 * MessagesPage — Track B isolated in-app instant messaging.
 *
 * Two-pane list+thread view on desktop; single-pane (list OR thread) on
 * narrow/mobile widths, matching the existing responsive pattern used by
 * other master-detail pages in this app.
 *
 * Polling only — no WebSockets/Channels anywhere in this codebase. Thread
 * messages poll every 5-8s while open; the conversation list polls every
 * 20-30s, matching MessagesBell's global-badge cadence.
 *
 * v1 non-goals (deliberately NOT built): typing indicators, per-message read
 * receipts (unread badge only), presence indicators.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { MessageSquare, Send, Search, ArrowLeft, Upload, X, FileText, Plus } from 'lucide-react'
import toast from 'react-hot-toast'
import {
  messagingApi,
  newClientNonce,
  type Conversation,
  type Message,
  type MessageAttachment,
} from '@/services/messagingApi'
import { teamApi } from '@/services/api'
import { useAuthStore } from '@/store/authStore'
import { cn, formatDate } from '@/lib/utils'
import { useSearchParams } from 'react-router-dom'

interface TeamMember {
  id: string
  user: string
  user_email: string | null
  user_full_name: string | null
  is_active: boolean
}

const THREAD_POLL_MS = 6_000
const LIST_POLL_MS = 25_000
const MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

/** Chat-bubble timestamp: local time-of-day for today's messages, a date
 *  (via the shared formatDate) plus time for anything older. */
function formatMessageTime(iso: string): string {
  const d = new Date(iso)
  if (isNaN(d.getTime())) return ''
  const time = d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
  const isToday = d.toDateString() === new Date().toDateString()
  return isToday ? time : `${formatDate(iso)} ${time}`
}

type FilterTab = 'team' | 'accountant'

function isCrossOrgThread(conv: Conversation): boolean {
  return conv.participants.some((p) => p.role === 'partner_contact')
}

function otherParticipant(conv: Conversation, userId?: string) {
  return conv.participants.find((p) => p.user !== userId)
}

export default function MessagesPage() {
  const user = useAuthStore((s) => s.user)
  const [searchParams, setSearchParams] = useSearchParams()
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(searchParams.get('c'))
  const [messages, setMessages] = useState<Message[]>([])
  const [draft, setDraft] = useState('')
  const [sending, setSending] = useState(false)
  const [filter, setFilter] = useState<FilterTab>('team')
  const [searchQuery, setSearchQuery] = useState('')
  const [loadingList, setLoadingList] = useState(false)
  const [loadingThread, setLoadingThread] = useState(false)
  const [mobileShowThread, setMobileShowThread] = useState(!!searchParams.get('c'))
  const [pendingAttachment, setPendingAttachment] = useState<MessageAttachment | null>(null)
  const [uploading, setUploading] = useState(false)
  const [showNewConversation, setShowNewConversation] = useState(false)
  const [teamMembers, setTeamMembers] = useState<TeamMember[]>([])
  const [loadingTeam, setLoadingTeam] = useState(false)
  const [startingWith, setStartingWith] = useState<string | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const isPartner = !!user?.has_partner_profile

  const refreshList = useCallback(async () => {
    setLoadingList(true)
    try {
      const { data } = await messagingApi.conversations()
      const list = Array.isArray(data) ? data : data.results ?? []
      setConversations(list)
    } catch {
      toast.error('Failed to load conversations')
    } finally {
      setLoadingList(false)
    }
  }, [])

  const refreshThread = useCallback(async (conversationId: string, silent = false) => {
    if (!silent) setLoadingThread(true)
    try {
      const { data } = await messagingApi.messages(conversationId, { limit: 50 })
      setMessages(data.results ?? [])
    } catch {
      if (!silent) toast.error('Failed to load messages')
    } finally {
      if (!silent) setLoadingThread(false)
    }
  }, [])

  // Initial + periodic conversation list refresh
  useEffect(() => {
    refreshList()
    const id = setInterval(refreshList, LIST_POLL_MS)
    return () => clearInterval(id)
  }, [refreshList])

  // Thread refresh + polling while a conversation is open
  useEffect(() => {
    if (!selectedId) { setMessages([]); return }
    refreshThread(selectedId)
    messagingApi.markRead(selectedId).catch(() => {})
    const id = setInterval(() => refreshThread(selectedId, true), THREAD_POLL_MS)
    return () => clearInterval(id)
  }, [selectedId, refreshThread])

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight })
  }, [messages])

  const selectConversation = (id: string) => {
    setSelectedId(id)
    setMobileShowThread(true)
    setPendingAttachment(null)
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev)
      next.set('c', id)
      return next
    })
  }

  const handleFileSelected = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file || !selectedId) return
    if (file.size > MAX_ATTACHMENT_BYTES) {
      toast.error(`File too large — max ${formatBytes(MAX_ATTACHMENT_BYTES)}`)
      return
    }
    setUploading(true)
    try {
      const { data } = await messagingApi.uploadAttachment(selectedId, file)
      setPendingAttachment(data)
    } catch (err: unknown) {
      const apiErr = (err as { response?: { data?: { error?: unknown } } })?.response?.data?.error
      const msg = typeof apiErr === 'string' ? apiErr : (apiErr as { message?: string })?.message ?? 'Failed to upload attachment'
      toast.error(msg)
    } finally {
      setUploading(false)
    }
  }

  const handleSend = async () => {
    const body = draft.trim()
    const attachment = pendingAttachment
    if ((!body && !attachment) || !selectedId || sending) return
    setSending(true)
    const nonce = newClientNonce()
    // Optimistic append so the UI feels instant even when the request is
    // queued offline by the shared api.ts interceptor.
    const optimistic: Message = {
      id: `tmp-${nonce}`,
      conversation: selectedId,
      sender: user?.id ?? null,
      sender_email: user?.email ?? null,
      body,
      seq: (messages[messages.length - 1]?.seq ?? 0) + 1,
      client_nonce: nonce,
      attachments: attachment ? [attachment] : [],
      is_deleted: false,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    }
    setMessages((prev) => [...prev, optimistic])
    setDraft('')
    setPendingAttachment(null)
    try {
      const { data } = await messagingApi.send(
        selectedId, body, nonce, attachment ? [attachment.id] : undefined
      )
      setMessages((prev) => prev.map((m) => (m.id === optimistic.id ? data : m)))
      refreshList()
    } catch (err: unknown) {
      // If this was queued offline, api.ts's interceptor already resolved it
      // silently (no exception) — an exception here means a real failure.
      setMessages((prev) => prev.filter((m) => m.id !== optimistic.id))
      const apiErr = (err as { response?: { data?: { error?: unknown } } })?.response?.data?.error
      const msg = typeof apiErr === 'string' ? apiErr : (apiErr as { message?: string })?.message ?? 'Failed to send message'
      toast.error(msg)
    } finally {
      setSending(false)
    }
  }

  const openNewConversation = async () => {
    setShowNewConversation(true)
    if (teamMembers.length > 0) return
    setLoadingTeam(true)
    try {
      const { data } = await teamApi.members()
      const list: TeamMember[] = Array.isArray(data) ? data : (data as { results?: TeamMember[] }).results ?? []
      setTeamMembers(list.filter((m) => m.is_active && m.user !== user?.id))
    } catch {
      toast.error('Failed to load team members')
    } finally {
      setLoadingTeam(false)
    }
  }

  const startConversationWith = async (otherUserId: string) => {
    setStartingWith(otherUserId)
    try {
      const { data } = await messagingApi.getOrCreateDirect(otherUserId)
      setShowNewConversation(false)
      await refreshList()
      selectConversation(data.id)
    } catch (err: unknown) {
      const apiErr = (err as { response?: { data?: { error?: unknown } } })?.response?.data?.error
      const msg = typeof apiErr === 'string' ? apiErr : (apiErr as { message?: string })?.message ?? 'Failed to start conversation'
      toast.error(msg)
    } finally {
      setStartingWith(null)
    }
  }

  const filtered = conversations.filter((c) =>
    filter === 'accountant' ? isCrossOrgThread(c) : !isCrossOrgThread(c)
  )

  const selectedConv = conversations.find((c) => c.id === selectedId) ?? null

  return (
    <div className="flex flex-col h-[calc(100vh-8rem)] bg-surface-900 rounded-2xl border border-surface-700 overflow-hidden">
      <div className="flex items-center gap-2 px-5 py-4 border-b border-surface-700">
        <MessageSquare size={18} className="text-brand-400" />
        <h1 className="text-base font-bold text-white">Messages</h1>
        <button
          onClick={openNewConversation}
          className="ml-auto flex items-center gap-1.5 text-xs font-semibold px-3 py-1.5 rounded-lg bg-brand-500 text-white hover:bg-brand-600 transition-colors"
        >
          <Plus size={14} /> New conversation
        </button>
      </div>

      <div className="flex flex-1 min-h-0">
        {/* Conversation list pane */}
        <div className={cn(
          'w-full md:w-80 shrink-0 border-r border-surface-700 flex flex-col',
          mobileShowThread && 'hidden md:flex'
        )}>
          <div className="p-3 border-b border-surface-700">
            <div className="flex items-center gap-1.5 bg-surface-800 rounded-lg p-1">
              <button
                onClick={() => setFilter('team')}
                className={cn(
                  'flex-1 text-xs font-semibold py-1.5 rounded-md transition-colors',
                  filter === 'team' ? 'bg-brand-500 text-white' : 'text-slate-400 hover:text-white'
                )}
              >
                My Team
              </button>
              <button
                onClick={() => setFilter('accountant')}
                className={cn(
                  'flex-1 text-xs font-semibold py-1.5 rounded-md transition-colors',
                  filter === 'accountant' ? 'bg-amber-500 text-white' : 'text-slate-400 hover:text-white'
                )}
              >
                {isPartner ? 'Clients' : 'Accountant'}
              </button>
            </div>
            <div className="relative mt-2">
              <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-500" />
              <input
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search messages…"
                className="w-full text-xs bg-surface-800 border border-surface-700 rounded-lg pl-8 pr-2 py-1.5 text-white placeholder:text-slate-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
              />
            </div>
          </div>

          <div className="flex-1 overflow-y-auto">
            {loadingList && filtered.length === 0 ? (
              <p className="text-xs text-slate-500 text-center py-8">Loading…</p>
            ) : filtered.length === 0 ? (
              <div className="py-10 text-center">
                <MessageSquare size={22} className="mx-auto mb-2 text-slate-600" />
                <p className="text-xs text-slate-500">
                  {filter === 'accountant' ? 'No accountant conversations yet' : 'No team conversations yet'}
                </p>
              </div>
            ) : (
              filtered.map((conv) => {
                const other = otherParticipant(conv, user?.id)
                const crossOrg = isCrossOrgThread(conv)
                return (
                  <button
                    key={conv.id}
                    onClick={() => selectConversation(conv.id)}
                    className={cn(
                      'w-full flex items-start gap-2.5 px-4 py-3 border-b border-surface-800 hover:bg-surface-800/60 transition-colors text-left',
                      selectedId === conv.id && 'bg-surface-800'
                    )}
                  >
                    <div className={cn(
                      'w-8 h-8 rounded-full flex items-center justify-center shrink-0 text-xs font-bold',
                      crossOrg ? 'bg-amber-500/20 text-amber-400' : 'bg-brand-500/20 text-brand-400'
                    )}>
                      {(other?.user_email ?? '?')[0]?.toUpperCase()}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-1.5">
                        <p className="text-xs font-semibold text-white truncate">
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

        {/* Thread pane */}
        <div className={cn('flex-1 flex flex-col min-w-0', !mobileShowThread && 'hidden md:flex')}>
          {!selectedConv ? (
            <div className="flex-1 flex flex-col items-center justify-center text-center px-8">
              <MessageSquare size={32} className="text-slate-700 mb-3" />
              <p className="text-sm text-slate-500">Select a conversation to start messaging</p>
            </div>
          ) : (
            <>
              <div className="flex items-center gap-2 px-4 py-3 border-b border-surface-700">
                <button
                  onClick={() => setMobileShowThread(false)}
                  className="md:hidden p-1 text-slate-400 hover:text-white"
                  aria-label="Back to conversation list"
                >
                  <ArrowLeft size={16} />
                </button>
                <div>
                  <p className="text-sm font-semibold text-white">
                    {otherParticipant(selectedConv, user?.id)?.user_email ?? 'Conversation'}
                  </p>
                  {isCrossOrgThread(selectedConv) && (
                    <span className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-400 uppercase tracking-wide">
                      CLIENT
                    </span>
                  )}
                </div>
              </div>

              <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-3 space-y-2">
                {loadingThread ? (
                  <p className="text-xs text-slate-500 text-center py-6">Loading messages…</p>
                ) : messages.length === 0 ? (
                  <p className="text-xs text-slate-500 text-center py-6">No messages yet — say hello.</p>
                ) : (
                  messages.map((msg, idx) => {
                    const mine = msg.sender === user?.id
                    // "Seen" — single mark on the most recent read message,
                    // WhatsApp-style. Only makes sense on the LAST message in
                    // the thread when it's mine, checked against the other
                    // participant's last_read_seq (already on every
                    // conversation via ConversationSerializer.participants —
                    // no per-message receipt scheme, deliberately).
                    const isLastMessage = idx === messages.length - 1
                    const other = selectedConv ? otherParticipant(selectedConv, user?.id) : undefined
                    const seen = mine && isLastMessage && (other?.last_read_seq ?? 0) >= msg.seq
                    return (
                      <div key={msg.id} className={cn('flex flex-col', mine ? 'items-end' : 'items-start')}>
                        <div className={cn(
                          'max-w-[75%] rounded-2xl px-3.5 py-2 text-sm',
                          mine ? 'bg-brand-500 text-white' : 'bg-surface-800 text-slate-200'
                        )}>
                          {msg.is_deleted ? (
                            <em className="text-slate-400">Message deleted</em>
                          ) : (
                            <>
                              {msg.body && <p>{msg.body}</p>}
                              {msg.attachments.map((att) => (
                                <a
                                  key={att.id}
                                  href={att.download_url ?? undefined}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  className={cn(
                                    'mt-1.5 flex items-center gap-1.5 rounded-lg px-2 py-1.5 text-xs font-medium underline-offset-2 hover:underline',
                                    mine ? 'bg-white/10 text-white' : 'bg-surface-700 text-slate-100'
                                  )}
                                >
                                  <FileText size={13} className="shrink-0" />
                                  <span className="truncate">{att.file_name}</span>
                                  <span className="shrink-0 opacity-70">{formatBytes(att.file_size)}</span>
                                </a>
                              ))}
                            </>
                          )}
                        </div>
                        <div className="flex items-center gap-1 mt-0.5 px-1">
                          <span className="text-[10px] text-slate-500">{formatMessageTime(msg.created_at)}</span>
                          {seen && <span className="text-[10px] text-brand-400">Seen</span>}
                        </div>
                      </div>
                    )
                  })
                )}
              </div>

              <div className="border-t border-surface-700">
                {pendingAttachment && (
                  <div className="flex items-center gap-2 px-4 pt-2.5">
                    <div className="flex items-center gap-1.5 bg-surface-800 border border-surface-700 rounded-lg px-2.5 py-1.5 text-xs text-slate-200">
                      <FileText size={13} className="shrink-0 text-slate-400" />
                      <span className="truncate max-w-[200px]">{pendingAttachment.file_name}</span>
                      <span className="shrink-0 text-slate-500">{formatBytes(pendingAttachment.file_size)}</span>
                      <button
                        type="button"
                        onClick={() => setPendingAttachment(null)}
                        aria-label="Remove attachment"
                        className="shrink-0 text-slate-500 hover:text-white"
                      >
                        <X size={13} />
                      </button>
                    </div>
                  </div>
                )}
                {/* pr-16 on md+ clears the fixed SupportChat bubble (bottom-5
                    right-5, 52px) — without it the Send button sits directly
                    underneath the chat widget and is unclickable. Only
                    needed at wider breakpoints: on narrow/mobile widths the
                    composer already stacks full-bleed above the widget. */}
                <div className="flex items-center gap-2 px-4 py-3 md:pr-20">
                  <input
                    ref={fileInputRef}
                    type="file"
                    onChange={handleFileSelected}
                    className="hidden"
                  />
                  <button
                    type="button"
                    onClick={() => fileInputRef.current?.click()}
                    disabled={uploading || !!pendingAttachment}
                    title={pendingAttachment ? 'Remove the current attachment to add another' : 'Attach a file'}
                    aria-label="Attach a file"
                    className="p-2 rounded-lg text-slate-400 hover:text-white hover:bg-surface-800 disabled:opacity-40 disabled:hover:bg-transparent transition-colors"
                  >
                    <Upload size={16} />
                  </button>
                  <input
                    value={draft}
                    onChange={(e) => setDraft(e.target.value)}
                    onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend() } }}
                    placeholder={uploading ? 'Uploading attachment…' : 'Type a message…'}
                    disabled={uploading}
                    className="flex-1 text-sm bg-surface-800 border border-surface-700 rounded-lg px-3 py-2 text-white placeholder:text-slate-500 focus:outline-none focus:ring-1 focus:ring-brand-500 disabled:opacity-60"
                  />
                  <button
                    onClick={handleSend}
                    disabled={(!draft.trim() && !pendingAttachment) || sending || uploading}
                    className="p-2 rounded-lg bg-brand-500 text-white disabled:opacity-40 hover:bg-brand-600 transition-colors"
                    aria-label="Send message"
                  >
                    <Send size={16} />
                  </button>
                </div>
              </div>
            </>
          )}
        </div>
      </div>

      {showNewConversation && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
          <div className="card w-full max-w-md p-5 space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="font-semibold text-white">New conversation</h2>
              <button
                type="button"
                onClick={() => setShowNewConversation(false)}
                className="text-slate-400 hover:text-white"
                aria-label="Close"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            {loadingTeam ? (
              <p className="text-sm text-slate-400 text-center py-6">Loading team members…</p>
            ) : teamMembers.length === 0 ? (
              <p className="text-sm text-slate-400 text-center py-6">No other team members to message yet.</p>
            ) : (
              <div className="max-h-80 overflow-y-auto space-y-1">
                {teamMembers.map((m) => (
                  <button
                    key={m.id}
                    onClick={() => startConversationWith(m.user)}
                    disabled={startingWith === m.user}
                    className="w-full flex items-center gap-2.5 px-3 py-2.5 rounded-lg hover:bg-surface-800 transition-colors text-left disabled:opacity-50"
                  >
                    <div className="w-8 h-8 rounded-full bg-brand-500/20 text-brand-400 flex items-center justify-center shrink-0 text-xs font-bold">
                      {(m.user_full_name || m.user_email || '?')[0]?.toUpperCase()}
                    </div>
                    <div className="min-w-0">
                      <p className="text-sm text-white truncate">{m.user_full_name || m.user_email}</p>
                      {m.user_full_name && <p className="text-xs text-slate-500 truncate">{m.user_email}</p>}
                    </div>
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

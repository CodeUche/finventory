/**
 * Messaging API client — Track B (isolated in-app instant messaging).
 *
 * Imports the shared `api` axios instance from `./api` (JWT + org header
 * injection, offline mutation queue, token refresh already wired there —
 * see api.ts's request/response interceptors). This file adds NO new axios
 * instance and does not modify api.ts.
 *
 * Offline behaviour: POST .../messages/ matches api.ts's isActionEndpoint()
 * pattern (…/{uuid}/messages/), so a send made while offline is transparently
 * queued by the existing syncEngine and replayed on reconnect — no
 * messaging-specific offline code is needed here. client_nonce is generated
 * client-side (see newClientNonce()) so a queued retry can never double-post.
 */

import { api } from './api'

export interface ConversationParticipant {
  id: string
  conversation: string
  user: string
  user_email: string | null
  user_full_name: string | null
  role: string
  joined_at: string
  last_read_seq: number
  muted: boolean
  left_at: string | null
}

export interface Conversation {
  id: string
  kind: 'direct'
  subject: string
  created_by: string | null
  is_archived: boolean
  last_message_at: string | null
  last_message_preview: string
  last_seq: number
  participants: ConversationParticipant[]
  unread_count: number
  created_at: string
  updated_at: string
}

export interface MessageAttachment {
  id: string
  message: string | null
  /** Authenticated, participant-gated download URL — never a raw storage URL. */
  download_url: string | null
  file_name: string
  file_size: number
  content_type: string
  checksum: string
  created_at: string
}

export interface Message {
  id: string
  conversation: string
  sender: string | null
  sender_email: string | null
  sender_name: string | null
  body: string
  seq: number
  client_nonce: string | null
  attachments: MessageAttachment[]
  is_deleted: boolean
  created_at: string
  updated_at: string
}

export interface MessagePage {
  results: Message[]
  next_before: number | null
  has_more: boolean
}

export interface PartnerInboxRow {
  organisation_id: string
  organisation_name: string
  unread_count: number
  last_message_preview: string
  last_message_at: string | null
  conversation_id: string | null
}

/** Generates a client-side idempotency token for a new message send. */
export function newClientNonce(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    return crypto.randomUUID()
  }
  return `nonce-${Date.now()}-${Math.random().toString(36).slice(2)}`
}

// api.ts caches every GET for 5 minutes by default (a genuinely fresh-cache
// gate meant for list/detail pages) — with no per-endpoint exemption. That
// silently broke polling here: the FIRST unread_count/conversations/messages
// response got served back unchanged for the next 5 minutes regardless of
// what happened server-side, so the unread badge, the Seen indicator, and
// even new messages arriving in an open thread never updated until the
// window expired. Found the hard way — see api.ts's own `X-Bypass-Cache`
// check, which existed but had no caller anywhere in the codebase before
// this. These three calls are the ones this feature's polling depends on;
// this file does not attempt to fix the cache gate for every other poller.
const BYPASS_CACHE = { headers: { 'X-Bypass-Cache': '1' } }

export const messagingApi = {
  conversations: (params?: { archived?: boolean }) =>
    api.get<{ results: Conversation[] } | Conversation[]>('/messaging/conversations/', { params, ...BYPASS_CACHE }),

  getOrCreateDirect: (otherUserId: string) =>
    api.post<Conversation>('/messaging/conversations/get_or_create_direct/', {
      other_user_id: otherUserId,
    }),

  messages: (conversationId: string, opts?: { before?: number; limit?: number }) =>
    api.get<MessagePage>(`/messaging/conversations/${conversationId}/messages/`, {
      params: opts,
      ...BYPASS_CACHE,
    }),

  /**
   * Sends a message. Always pass a client_nonce (use newClientNonce()) so an
   * offline-queued retry cannot create a duplicate — the backend returns the
   * existing message (200) rather than erroring on a repeat nonce.
   */
  send: (conversationId: string, body: string, clientNonce: string, attachmentIds?: string[]) =>
    api.post<Message>(`/messaging/conversations/${conversationId}/messages/`, {
      body,
      client_nonce: clientNonce,
      ...(attachmentIds?.length ? { attachment_ids: attachmentIds } : {}),
    }),

  markRead: (conversationId: string) =>
    api.post<{ conversation_id: string; last_read_seq: number; last_seq: number }>(
      `/messaging/conversations/${conversationId}/read/`
    ),

  uploadAttachment: (conversationId: string, file: File) => {
    const form = new FormData()
    form.append('file', file)
    // Do NOT set Content-Type here — a FormData body needs the multipart
    // boundary the browser (or api.ts's Tauri-aware adapter) generates
    // automatically. An explicit 'multipart/form-data' with no boundary
    // parameter is what the server actually received (confirmed live: a
    // real browser upload 415'd with "Unsupported media type
    // application/x-www-form-urlencoded" — Django's parser couldn't make
    // sense of a boundary-less multipart Content-Type and fell through to
    // its default). See api.ts's request interceptor, which already strips
    // any Content-Type when config.data is a FormData instance for exactly
    // this reason — this call was fighting that safeguard instead of
    // relying on it.
    return api.post<MessageAttachment>(
      `/messaging/conversations/${conversationId}/attachments/`,
      form,
    )
  },

  unreadCount: () => api.get<{ unread_count: number }>('/messaging/unread_count/', BYPASS_CACHE),

  partnerInbox: () => api.get<{ results: PartnerInboxRow[] }>('/messaging/partner_inbox/'),

  search: (q: string) => api.get<{ results: Message[] }>('/messaging/search/', { params: { q } }),
}

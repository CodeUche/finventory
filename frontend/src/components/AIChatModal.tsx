/**
 * AIChatModal — "Explain My Money" AI Financial Assistant
 *
 * Surfaces Audity's AI-powered insights. Sends user questions to the backend
 * which queries Claude with the organisation's real financial data.
 *
 * Features:
 * - Pre-built quick-question chips for common queries
 * - Streaming-style typing effect for AI responses
 * - Full conversation history within the session
 * - Smart alerts section (auto-generated on open)
 */

import { useEffect, useRef, useState } from 'react'
import { X, Bot, Send, Loader2, Sparkles, TrendingUp, AlertTriangle, MessageSquare } from 'lucide-react'
import { aiApi } from '@/services/api'
import { useAuthStore } from '@/store/authStore'

interface Message {
  role: 'user' | 'assistant'
  content: string
  loading?: boolean
}

/** Render AI markdown response as clean React elements without any extra package */
function MarkdownMessage({ text }: { text: string }) {
  const lines = text.split('\n')
  const elements: React.ReactNode[] = []
  let listItems: string[] = []
  let key = 0

  const flushList = () => {
    if (listItems.length) {
      elements.push(
        <ul key={key++} className="list-none space-y-1 my-2">
          {listItems.map((item, i) => (
            <li key={i} className="flex gap-2">
              <span className="text-brand-400 mt-0.5 shrink-0">•</span>
              <span>{renderInline(item)}</span>
            </li>
          ))}
        </ul>
      )
      listItems = []
    }
  }

  const renderInline = (line: string): React.ReactNode => {
    // Replace **bold** and *italic* inline
    const parts = line.split(/(\*\*[^*]+\*\*|\*[^*]+\*)/g)
    return parts.map((part, i) => {
      if (part.startsWith('**') && part.endsWith('**'))
        return <strong key={i} className="text-white font-semibold">{part.slice(2, -2)}</strong>
      if (part.startsWith('*') && part.endsWith('*'))
        return <em key={i}>{part.slice(1, -1)}</em>
      return part
    })
  }

  for (const raw of lines) {
    const line = raw.trim()

    // Bullet lines: * item or - item
    if (/^[*-]\s+/.test(line)) {
      listItems.push(line.replace(/^[*-]\s+/, ''))
      continue
    }

    // Numbered list: 1. item
    if (/^\d+\.\s+/.test(line)) {
      listItems.push(line.replace(/^\d+\.\s+/, ''))
      continue
    }

    flushList()

    if (!line) {
      elements.push(<div key={key++} className="h-2" />)
    } else if (line.startsWith('### ')) {
      elements.push(<p key={key++} className="font-semibold text-white text-sm mt-3 mb-1">{renderInline(line.slice(4))}</p>)
    } else if (line.startsWith('## ') || line.startsWith('# ')) {
      elements.push(<p key={key++} className="font-bold text-white text-sm mt-3 mb-1">{renderInline(line.replace(/^#+\s/, ''))}</p>)
    } else {
      elements.push(<p key={key++} className="leading-relaxed">{renderInline(line)}</p>)
    }
  }

  flushList()
  return <div className="space-y-0.5 text-sm">{elements}</div>
}

const QUICK_QUESTIONS = [
  'Am I making profit?',
  'Where am I losing money?',
  'Explain my finances this month',
  'What are my biggest expenses?',
  'How is my cash flow?',
  'Do I have overdue invoices?',
  'Am I spending more than last month?',
  'What should I focus on to grow?',
]

interface Props {
  open: boolean
  onClose: () => void
}

export default function AIChatModal({ open, onClose }: Props) {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [available, setAvailable] = useState<boolean | null>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const organisation = useAuthStore((s) => s.organisation)

  useEffect(() => {
    if (!open) return
    // Check if AI is configured on the server
    aiApi.status()
      .then(({ data }) => setAvailable(data.available))
      .catch(() => setAvailable(false))
    // Auto-focus input
    setTimeout(() => inputRef.current?.focus(), 100)
  }, [open])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const sendMessage = async (text: string) => {
    const msg = text.trim()
    if (!msg || sending) return

    setInput('')
    setMessages((prev) => [
      ...prev,
      { role: 'user', content: msg },
      { role: 'assistant', content: '', loading: true },
    ])
    setSending(true)

    try {
      const { data } = await aiApi.chat(msg)
      setMessages((prev) => [
        ...prev.slice(0, -1),
        { role: 'assistant', content: data.response },
      ])
    } catch (err: any) {
      const apiErr = err?.response?.data?.error
      const errMsg = typeof apiErr === 'string' ? apiErr : (apiErr?.message ?? 'AI assistant is unavailable right now.')
      setMessages((prev) => [
        ...prev.slice(0, -1),
        { role: 'assistant', content: `⚠️ ${errMsg}` },
      ])
      if (err?.response?.status === 503) setAvailable(false)
    } finally {
      setSending(false)
      setTimeout(() => inputRef.current?.focus(), 100)
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendMessage(input)
    }
  }

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center p-0 sm:p-4">
      <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={onClose} />
      <div className="relative bg-surface-800 border border-surface-700 rounded-t-2xl sm:rounded-2xl w-full sm:max-w-xl shadow-2xl flex flex-col"
        style={{ height: '85vh', maxHeight: '680px' }}>

        {/* Header */}
        <div className="flex items-center gap-3 p-4 border-b border-surface-700 shrink-0">
          <div className="w-9 h-9 rounded-xl bg-brand-500/20 flex items-center justify-center">
            <Bot size={18} className="text-brand-400" />
          </div>
          <div className="flex-1 min-w-0">
            <h2 className="font-semibold text-white text-sm">Audity AI — Financial Assistant</h2>
            <p className="text-xs text-slate-400 truncate">
              {organisation?.name ?? 'Your business'} · Ask anything about your finances
            </p>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-white transition-colors">
            <X size={18} />
          </button>
        </div>

        {/* Messages area */}
        <div className="flex-1 overflow-y-auto p-4 space-y-4 min-h-0">
          {available === false && available !== null && (
            <div className="p-4 rounded-xl bg-amber-500/10 border border-amber-500/30 text-center">
              <AlertTriangle size={20} className="text-amber-400 mx-auto mb-2" />
              <p className="text-sm font-semibold text-amber-400">AI not configured</p>
              <p className="text-xs text-slate-400 mt-1">
                Add your <code className="text-amber-300">GROQ_API_KEY</code> to the server environment to enable the AI assistant.
                Get a free key at <span className="text-amber-300">console.groq.com/keys</span>.
              </p>
            </div>
          )}

          {messages.length === 0 && available !== false && available !== null && (
            <div className="space-y-4">
              {/* Welcome */}
              <div className="flex gap-3">
                <div className="w-7 h-7 rounded-lg bg-brand-500/20 flex items-center justify-center shrink-0 mt-0.5">
                  <Sparkles size={13} className="text-brand-400" />
                </div>
                <div className="bg-surface-700/50 rounded-2xl rounded-tl-sm px-4 py-3 text-sm text-slate-200 leading-relaxed">
                  Hi! I'm your Audity AI financial assistant. I have access to your real business data —
                  ask me anything about your finances and I'll explain it in plain English. 💡
                </div>
              </div>

              {/* Quick questions */}
              <div>
                <p className="text-xs text-slate-500 mb-2 flex items-center gap-1.5">
                  <TrendingUp size={11} /> Quick questions
                </p>
                <div className="flex flex-wrap gap-2">
                  {QUICK_QUESTIONS.map((q) => (
                    <button
                      key={q}
                      onClick={() => sendMessage(q)}
                      disabled={sending}
                      className="text-xs px-3 py-1.5 rounded-full bg-surface-700 hover:bg-surface-600 text-slate-300 hover:text-white border border-surface-600 hover:border-surface-500 transition-all disabled:opacity-40"
                    >
                      {q}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          )}

          {messages.map((msg, i) => (
            <div key={i} className={`flex gap-3 ${msg.role === 'user' ? 'flex-row-reverse' : ''}`}>
              <div className={`w-7 h-7 rounded-lg flex items-center justify-center shrink-0 mt-0.5 ${
                msg.role === 'user'
                  ? 'bg-brand-500'
                  : 'bg-surface-700'
              }`}>
                {msg.role === 'user'
                  ? <MessageSquare size={13} className="text-white" />
                  : <Bot size={13} className="text-slate-400" />
                }
              </div>
              <div className={`max-w-[82%] rounded-2xl px-4 py-3 text-sm leading-relaxed ${
                msg.role === 'user'
                  ? 'bg-brand-500 text-white rounded-tr-sm'
                  : 'bg-surface-700/50 text-slate-200 rounded-tl-sm'
              }`}>
                {msg.loading
                  ? <span className="flex items-center gap-2 text-slate-400">
                      <Loader2 size={13} className="animate-spin" />
                      Analysing your finances…
                    </span>
                  : msg.role === 'assistant'
                    ? <MarkdownMessage text={msg.content} />
                    : <span>{msg.content}</span>
                }
              </div>
            </div>
          ))}
          <div ref={bottomRef} />
        </div>

        {/* Input */}
        <div className="p-4 border-t border-surface-700 shrink-0">
          <div className="flex gap-2 items-center">
            <input
              ref={inputRef}
              type="text"
              className="input flex-1 text-sm"
              placeholder={available === false ? 'AI not configured…' : 'Ask about your finances…'}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              disabled={sending || available === false}
              maxLength={1000}
            />
            <button
              onClick={() => sendMessage(input)}
              disabled={!input.trim() || sending || available === false}
              className="btn-primary px-3 py-2.5 disabled:opacity-40"
            >
              {sending ? <Loader2 size={15} className="animate-spin" /> : <Send size={15} />}
            </button>
          </div>
          <p className="text-xs text-slate-600 mt-1.5 text-center">
            Powered by Groq · Llama 3.1 · Responses based on your live financial data
          </p>
        </div>
      </div>
    </div>
  )
}
